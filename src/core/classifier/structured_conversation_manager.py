from .intent import UserQueryClassifier, QueryType, QueryTopic
from typing import Dict, Any
import time

class StructuredConversationManager:
    """
    Manages conversations using intent classification
    """
    
    def __init__(self, classifier):
        self.classifier = classifier
        self.conversation_history = []
        self.current_context = {}
        
    def process_message(self, user_id: str, message: str) -> Dict[str, Any]:
        """Process message with structured conversation"""
        
        # 1. Classify the message
        classification = self.classifier.classify(message)
        
        # 2. Update conversation history
        self.conversation_history.append({
            'user_id': user_id,
            'message': message,
            'classification': classification.dict(),
            'timestamp': time.time()
        })
        
        # 3. Get conversation strategy
        strategy = classification.get_conversation_strategy()
        
        # 4. Generate response based on classification
        response_data = {
            'response': self._generate_response(classification, strategy),
            'classification': classification.dict(),
            'strategy': strategy,
            'next_action': strategy['next_step'],
            'requires_documents': classification.required_documents,
            'should_clarify': classification.should_ask_clarifying_question()
        }
        
        # 5. If clarification needed, adjust response
        if response_data['should_clarify']:
            clarifying_q = classification.get_clarifying_question()
            if clarifying_q:
                response_data['response'] = clarifying_q
                response_data['next_action'] = 'await_clarification'
        
        return response_data
    
    def _generate_response(self, classification: UserQueryClassifier, strategy: Dict) -> str:
        """Generate response based on classification"""
        response_parts = []
        
        # Check for specific combinations
        if QueryType.ORDERING in classification.query_type and QueryType.CONSULTING in classification.query_type:
            response_parts.append("Veo que quieres ordenar y también tienes una consulta.")
            
            # Mention ordering first (usually the main intent)
            if classification.mentioned_dishes:
                dish = classification.mentioned_dishes[0]
                response_parts.append(f"Para {dish}, ¿lo prefieres en tamaño corriente o mini?")
            else:
                response_parts.append("¿Qué plato te gustaría ordenar?")
            
            # Then handle the consulting part
            if QueryTopic.PAYMENT in classification.primary_topics:
                response_parts.append("Y sobre el pago, aceptamos efectivo, tarjetas, Nequi y Daviplata.")
            elif QueryTopic.DELIVERY in classification.primary_topics:
                response_parts.append("Y sí, hacemos delivery. ¿Cuál es tu zona?")
        
        # Default multi-query response
        else:
            response_parts.append("Veo que tienes varias solicitudes. Permíteme ayudarte con cada una:")
            
            # List the detected query types
            type_names = [qt.value for qt in classification.query_type]
            response_parts.append(f"Detecté {len(type_names)} tipos de consulta: {', '.join(type_names)}.")
        
        return " ".join(response_parts)

    
    def get_conversation_summary(self) -> Dict:
        """Get summary of current conversation"""
        if not self.conversation_history:
            return {"status": "empty", "message_count": 0}
        
        last_message = self.conversation_history[-1]
        
        return {
            "status": "active",
            "message_count": len(self.conversation_history),
            "last_intent": last_message['classification']['query_type'],
            "last_topic": last_message['classification']['primary_topic'],
            "has_dishes_mentioned": bool(last_message['classification']['mentioned_dishes']),
            "flow": self._determine_conversation_flow()
        }
    
    def _determine_conversation_flow(self) -> str:
        """Determine current conversation flow"""
        if not self.conversation_history:
            return "initial"
        
        intents = [msg['classification']['query_type'] for msg in self.conversation_history[-3:]]
        
        if QueryType.ORDERING in intents:
            return "ordering_flow"
        elif QueryType.CONSULTING in intents:
            return "consulting_flow"
        elif QueryType.GREETING in intents:
            return "greeting_phase"
        
        return "general_chat"