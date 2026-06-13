from .intent import UserQueryClassifier, Detail, QueryTopic, QueryType
from .rule_base import RuleBasedClassifier
from typing import List
from src.infrastructure.llm_client import LLMClient, get_llm_client_for_stage
from src.infrastructure.prompt_manager import get_prompt_manager
from ..knowledge.registry import DocumentRegistry
from langfuse import observe
import time

class HybridClassifier:
    """
    Hybrid classifier: rules first, LLM for ambiguous cases
    """
    
    def __init__(self, llm_client: LLMClient = None):
        if llm_client is None:
            from src.config.environment import settings
            llm_client = get_llm_client_for_stage("classifier")
        self.rule_classifier = RuleBasedClassifier()
        self.llm_client = llm_client
        self.confidence_threshold = 0.6
        self.doc_registry = DocumentRegistry()
    
    @observe(name="classify")
    async def classify(self, message: str, summary_order:str=None, summary_conversation:str=None, user_preferences_context:str="") -> UserQueryClassifier:
        """Classify using LLM"""
        return await self._classify_with_llm(message, summary_order, summary_conversation, user_preferences_context)
    
    async def _classify_with_llm(self, message: str, summary_order:str=None, summary_conversation:str=None, user_preferences_context:str="") -> UserQueryClassifier:
        """Use LLM for classification"""
        from src.config.environment import settings
        print("\n", 50*".")
        print ("  STARTING CLASSIFICATION STAGE...")
        print(50*".", "\n")

        start_time = time.time()

        docs_summaries = self.doc_registry.get_all_summaries()

        prompt = get_prompt_manager(settings.prompt_fallback_map).get(
            "classifier",
            message=message,
            docs_summaries=docs_summaries,
            summary_order=summary_order,
            summary_conversation=summary_conversation,
            user_preferences_context=user_preferences_context,
        )

        from src.config.environment import settings
        from src.infrastructure.llm_client import get_model_for_stage
        
        response: UserQueryClassifier = await self.llm_client.chat_completion(
            messages=[{"role": "system", "content": prompt}],
            temperature=0.0,
            model=get_model_for_stage("classifier", settings),
            output_format=UserQueryClassifier,
            stream=False
        )

        # End the timer
        end_time = time.time()
        execution_time = end_time - start_time

        print(f"⏱️ Execution classification time: {execution_time:.2f} seconds")
        
        user_query_classifier = response
        
        print("\n", 70*"=")
        print(f"    TOPIC_DETAILS (validados): {user_query_classifier.topic_details}")
        print(" ", 70*"=", "\n")

        # Determinar si se necesita RAG y Reconcilier basado en los topic_details
        requires_RAG = self._determine_if_RAG(user_query_classifier.topic_details)
        requires_reconcilier = self._determine_if_Reconcilier(user_query_classifier.topic_details)
        
        # Preparar datos para compatibilidad
        data = {
            'topic_details': user_query_classifier.topic_details,
            'requires_RAG': requires_RAG,
            'requires_reconcilier': requires_reconcilier,
            'original_message': message
        }
        
        topics_details_with_sources = []
        for detail in user_query_classifier.topic_details:
            # Determinar información extraída basada en el tipo de consulta
            if detail.topic == QueryTopic.GREETING:
                info_extracted = "El usuario está saludando"
            elif detail.topic == QueryTopic.FAREWELL:
                info_extracted = "El usuario se está despidiendo"
            elif detail.query_type == QueryType.DISRESPECTING:
                info_extracted = "El usuario está siendo irrespetuoso."
            else:
                info_extracted = "No hay información por el momento"
            
            # Crear un nuevo objeto Detail con los valores actualizados
            updated_detail = Detail(
                segment=detail.segment,
                query_type=detail.query_type,
                topic=detail.topic,
                focus=detail.focus,
                file_source=self._identify_source(topic_name=detail.topic),
                info_extracted=info_extracted
            )
            
            topics_details_with_sources.append(updated_detail)
            
        data['topic_details']= topics_details_with_sources
        
        return UserQueryClassifier(**data)
    
    def _determine_if_RAG(self, topic_details:List[Detail]) -> bool:
        "Determines if RAG is needed"

        counter_RAG_needed = 0

        topics = [topic.topic for topic in topic_details]

        if QueryTopic.DISREPECTFUL_CUSTOMER in topics:
            print("Detected disrespectful customer - no RAG needed")
            return False
        
        for topic in topics:
            if topic not in [QueryTopic.GREETING, QueryTopic.FAREWELL]:
                counter_RAG_needed += 1

        RAG_required_status = counter_RAG_needed > 0

        return RAG_required_status
    
    def _determine_if_Reconcilier(self, topic_details:List[Detail]) -> bool:
        "Determines if Reconcilier is needed"

        counter_reconcilier_needed = 0

        query_types = [topic.query_type for topic in topic_details]

        for q_type in query_types:
            if q_type in [QueryType.ORDERING, QueryType.CONFIRMATION, QueryType.CLARIFICATION, QueryType.CANCELLATION]:
                counter_reconcilier_needed += 1

        reconcilier_required_status = counter_reconcilier_needed > 0

        return reconcilier_required_status
    
    def _identify_source(self, topic_name: str) -> str:
        """Matching what a book should extract inforrmation from"""
        
        source_file = self.doc_registry.get_doc_for_topic(topic=topic_name)

        return source_file
    

