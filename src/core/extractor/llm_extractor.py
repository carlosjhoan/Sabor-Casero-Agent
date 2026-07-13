from typing import Optional, Dict, List
from openai import OpenAI
import logging
import json
from .retriever_interface import RetrieverInterface
from src.core.classifier.intent import Detail
import asyncio
from src.infrastructure.llm_client import LLMClient, get_llm_client_for_stage

logger = logging.getLogger(__name__)

class InformationLlmExtractor(RetrieverInterface):
    """
    Extract relevant information from documents using LLM
    """
    
    def __init__(
        self,
        model: str = None,
        temperature: float = 0.0,
        max_tokens: int = 400,
        client: LLMClient = None
    ):
        """
        Initialize the extractor
        
        Args:
            model: LLM model to use (optional, defaults to settings)
            temperature: Sampling temperature (lower = more deterministic)
            max_tokens: Maximum tokens in response
            client: LLM client instance (optional, will create based on settings if not provided)
        """
        from src.config.environment import settings
        from src.infrastructure.llm_client import get_model_for_stage
        
        if client is None:
            client = get_llm_client_for_stage("retriever")
        
        self.client = client
        self.config = settings
        self.model = model if model else get_model_for_stage("retriever", settings)
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # System prompt for consistent behavior
        self.system_prompt = """You are an information extractor. 
        Given a customer query and a document, extract ONLY the relevant information 
        that answers the query. Be concise and accurate."""
    
    def _build_prompt_to_single(self, query: str, file_content: str) -> str:
        """
        Build the extraction prompt
        
        Args:
            query: Customer query
            file_content: Document content
            
        Returns:
            Formatted prompt string
        """
        max_content_length = 4000
        if len(file_content) > max_content_length:
            file_content = file_content[:max_content_length] + "... [truncated]"
        
        prompt = "CUSTOMER QUERY: " + query + "\n\nDOCUMENT CONTENT:\n" + file_content + "\n\nExtract ONLY the information relevant to answering the query. If the document does not contain the answer, say 'No se encuentra informacion sobre lo que el usuario pregunta'. Be concise and accurate. Respond in spanish and in a non-personal way, as you were a knowledge base."
        
        return prompt
    
    def _build_prompt_to_batch(self, queries: list[str], file_content: str) -> str:
        """
        Build the batch extraction prompt
        
        Args:
            queries: List of customer queries
            file_content: Document content
            
        Returns:
            Formatted prompt string
        """
        # Truncate content if too long (adjust as needed)
        max_content_length = 6000
        if len(file_content) > max_content_length:
            last_newline = file_content.rfind('\n', 0, max_content_length)
            file_content = file_content[:last_newline] + "\n\n[AVISO: El documento ha sido truncado por longitud.]"
        
        prompt = f"""
            SYSTEM ROLE: Expert Knowledge Extractor
            CUSTOMER QUERIES: {queries}

            DOCUMENT CONTENT:
            {file_content}

            INSTRUCTIONS:
            1. Extract ONLY information found in the document.
            2. If the answer is missing, return: "No se encuentra información sobre lo que el usuario pregunta".
            3. Use a neutral, knowledge-base tone (Spanish).
            4. Maintain the order of the queries provided.

            OUTPUT FORMAT (Strict JSON List):
            [
                {{
                    "query": "<original_query_text>",
                    "extracted_info": "<concise_answer_from_document>"
                }}
            ]

            EXAMPLES:
            [
                {{
                    "query": "¿Tienen domicilio?",
                    "extracted_info": "Servicio de domicilio disponible de 11:30am a 9:00pm."
                }},
                {{
                    "query": "¿Venden pizza?",
                    "extracted_info": "No se encuentra información sobre lo que el usuario pregunta."
                }}
            ]

            Provide ONLY the JSON list. No conversational filler.
        """
        
        return prompt

    async def extract(self, query: str, file_content: str) -> str:
        """
        Extract relevant information from document based on query
        
        Args:
            query: Customer query/question
            file_content: Document/text content to search
            
        Returns:
            Extracted relevant information or "Information not found"
        """
        try:
            prompt = self._build_prompt_to_single(query, file_content)
            
            response = await self.client.chat_completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Error extracting information: {e}")
            return f"Error processing request: {str(e)}"

    async def _batch_extract(self, doc_name:str, queries: list[str]) -> list[Dict[str, str]]:
        """
        Extract information for multiple queries from a same file
        
        Args:
            queries: List of customer queries
            file_contents: Document content to search

        Returns:
            List of extracted information
        """

        import re

        file_content = self._load_document(doc_name)

        prompt = self._build_prompt_to_batch(queries, file_content)

        try:

            response_raw = await self.client.chat_completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False
            )

            # 1. Clean Markdown backticks if they exist
            clean_json = re.sub(r"```json|```", "", response_raw).strip()

            # 2. Parse JSON
            results = json.loads(clean_json)

            # 3. Structural Validation (Scalability safety)
            if not isinstance(results, list):
                # Fallback if LLM returns a single object instead of a list
                results = [results]

            # 4. Fill missing segments if LLM missed one (Alignment safety)
            if len(results) < len(queries):
                print(f"⚠️ Warning: LLM returned {len(results)} answers for {len(queries)} queries.")
                # Logic here to pad the list or handle mismatch

            return results

        except json.JSONDecodeError as e:
            logger.error(f"Error in batch extraction: {e}")
            return [{"query": q, "extracted_info": "Error processing request"} for q in queries]

        
        except Exception as e:
            print(f"❌ Unexpected Error in batch_extract: {e}")
            raise

    def _load_document(self, doc_name: str) -> str:
        """Load document content by name"""
        # Placeholder: In real implementation, load from file or database
        documents_path = self.config.documents_path
        print (f"Loading document from path: {documents_path}/{doc_name}")
        try:
            with open(f"{documents_path}/{doc_name}", 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return "No se encontró el documento para extraer información"
    
    async def retrieve(self, group_by_doc: Dict[str, List[Detail]]) -> list[Detail]:
        """
        Retrieve relevant documents based on the query

        Args:
            grouped_details (Dict[str, List[Detail]]): The grouped topic details to retrieve information for

        Returns:
            List[Detail]: List of updated topic details with retrieved information
        """
        # Placeholder implementation
        extractor_tasks = []
        doc_order = [] # To keep track of which result belongs to which document
        print("\n", 30*" - = - ")
        print("🚀 Starting LLM-based extraction for documents...")
        print(" ", 30*" - = - ", "\n")

        for doc_name, details in group_by_doc.items():
            logger.debug(f"📂 Grouped {len(details)} queries for document: {doc_name}")
            doc_order.append(doc_name)
            extractor_tasks.append(self._batch_extract(doc_name, queries=[d.segment for d in details]))

        # 3. Concurrent Execution
        results = await asyncio.gather(*extractor_tasks, return_exceptions=True)

        print ("\n", 30*" - = - ")
        print("✅ LLM-based extraction completed!")
        print(" ", 30*" - = - ", "\n")

        #4. Map results back to the original objects
        for i, extracted_list in enumerate(results):
            doc_name = doc_order[i]
            original_details = group_by_doc[doc_name]
            print(f"Extracted info for document {doc_name}: {extracted_list}")

            if isinstance(extracted_list, Exception):
                print(f"❌ Critical Error in Batch for {doc_name}: {extracted_list}")
                logger.error(f"❌ Batch extraction failed for {doc_name}. Error: {str(extracted_list)}", exc_info=True)
                for d in original_details:
                    d.info_extracted = "Error al extraer información"
                continue

            #LLM data alignment check
            #'extracted_list' should be your list of dictionaries: [{"query": "...", "extracted_info": "..."}]
            for j, original_detail in enumerate(original_details):
                print(f"Processing detail: {original_detail} in pos {j} related to {doc_name} for query {extracted_list[j]['extracted_info']}")
                try:
                    # We match by index - this is why strict prompt formatting is key
                    original_detail.info_extracted = extracted_list[j]['extracted_info']
                    logger.debug(f"✅ Successfully extracted info for query: {original_detail.segment}")
                except (IndexError, AttributeError):
                    print(f"⚠️ Alignment mismatch in {doc_name}. Using fallback.")
                    logger.error(f"⚠️ Alignment mismatch in {doc_name}. Using fallback.")
                    original_detail.info_extracted = "No se pudo extraer información específica."

        return [detail for details in group_by_doc.values() for detail in details]

    async def get_context(self, query: str, doc_name: str) -> str:
        """
        Retrieve relevant context using LLM extraction.

        Loads the document and delegates to ``extract()`` for
        LLM-powered Q&A over the content.

        Args:
            query: The user's search query.
            doc_name: Target document filename.

        Returns:
            Extracted text relevant to the query, or empty string
            if the document is not found or extraction fails.
        """
        try:
            file_content = self._load_document(doc_name)
            if not file_content or "no se encontró" in file_content.lower():
                return ""
            return await self.extract(query, file_content)
        except Exception as e:
            logger.error("Error in LLM get_context for '%s': %s", doc_name, e)
            return ""

# Usage Example
if __name__ == "__main__":
    # Initialize extractor
    extractor = InformationLlmExtractor(
        model="deepseek-v4-flash",
        temperature=0.1,
        max_tokens=500
    )
    
    # Example usage
    query = "What are the restaurant's opening hours?"
    document = """
    Restaurant Information:
    Name: Bella Italia
    Opening Hours: Monday-Friday 11:00-22:00, Saturday-Sunday 10:00-23:00
    Address: 123 Main Street
    Phone: "555-0123"
    Specialty: Italian cuisine, pizza, pasta
    Delivery: Available through Uber Eats and DoorDash
    """
    
    # Extract relevant information
    result = extractor.extract(query, document)
    print(f"Query: {query}")
    print(f"Extracted: {result}")
    # Output: "Opening Hours: Monday-Friday 11:00-22:00, Saturday-Sunday 10:00-23:00"