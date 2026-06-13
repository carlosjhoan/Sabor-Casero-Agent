from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any
from enum import Enum

# === ENUMS ===
class QueryTopic(str, Enum):
    """Main topics users can ask about"""
    MENU = "menu"                    # Dishes, prices, availability
    SERVICE_HOURS = "hours"  # Opening/closing times           # Cost-related queries 
    DELIVERY = "delivery"            # Delivery service info
    PAYMENT = "payment"              # Payment methods
    RESERVATION = "reservation"      # Table booking
    CUTLERY_REQUEST = "cutley_request"
    ADICIONAL_JUICE = "adicional_juice"
    ABOUT = "about"                  # Restaurant info, history
    COMPLAINT = "complaint"          # Issues, problems
    ORDER_STATUS = "order_status"    # Order tracking
    INGREDIENTS = "ingredients"      # Dish ingredients
    SPECIAL_OFFERS = "special_offers" # Promotions, deals
    GENERAL = "general"              # Other topics
    GREETING = "greeting"            # Hello, hi
    FAREWELL = "farewell"            # Goodbye, thanks
    UNKNOWN = "unknown"          # No topic about restaurant. Nothing related to
    DISREPECTFUL_CUSTOMER = "disrespectful_customer"  

class QueryType(str, Enum):
    """Type of query"""
    CONSULTING = "consulting"        # Asking for information
    ORDERING = "ordering"            # Placing/modifying order
    COMPLAINT = "complaint"          # Making complaint
    CONFIRMATION = "confirmation"    # Yes, no, confirm
    CLARIFICATION = "clarification"  # Asking for clarification
    DISRESPECTING = "disrespecting"    # Rude or inappropriate messages
    CANCELLATION = "cancellation"    # Canceling order or reservation

class DocumentSource(str, Enum):
    """Where to find information"""
    MENU_FILE = "menu.md"
    SERVICE_INFO = "service_info.txt"
    WAITER_GUIDE = "waiter_guide.txt"
    ABOUT_US = "about_us.txt"
    NONE = None             # No document needed

class Detail(BaseModel):
    """
    Detalle de clasificación para un segmento específico del mensaje del usuario.
    
    Representa la clasificación granular de cada parte del mensaje del usuario,
    identificando tipo de consulta, tema, foco y fuentes de información necesarias.
    """
    segment: str = Field(
        description="Segmento específico del mensaje del usuario que se está clasificando"
    )
    query_type: QueryType = Field(
        description="Tipo de consulta (consulting, ordering, complaint, etc.)"
    )
    topic: QueryTopic = Field(
        description="Tema principal de la consulta (menu, delivery, payment, etc.)"
    )
    focus: str = Field(
        description="Enfoque específico dentro del tema (ej: 'precio del lomo', 'horario de entrega'). Debe tener entre 3 y 20 palabras."
    )
    
    @field_validator('focus')
    @classmethod
    def validate_focus_length(cls, v: str) -> str:
        """
        Valida que el focus tenga una longitud adecuada.
        
        Args:
            v: El valor del campo focus
            
        Returns:
            El valor validado
            
        Raises:
            ValueError: Si el focus tiene menos de 3 palabras o más de 20 palabras
        """
        if not v:
            return v
            
        word_count = len(v.strip().split())
        
        if word_count < 3:
            raise ValueError(f"Focus debe tener al menos 3 palabras. Tiene {word_count} palabra(s).")
        
        if word_count > 20:
            raise ValueError(f"Focus no debe exceder 20 palabras. Tiene {word_count} palabras.")
        
        return v
    file_source: str = Field(
        default="",
        description="Nombre del archivo/documento donde buscar información (ej: 'menu.md', 'service_info.txt'). Vacío inicialmente, se llena durante la extracción."
    )
    info_extracted: str = Field(
        default="",
        description="Información extraída del documento para responder a la consulta. Vacío inicialmente, se llena durante la extracción."
    )

# === MAIN CLASSIFIER MODEL ===
class UserQueryClassifier(BaseModel):
    """
    Respuesta completa del clasificador con todos los detalles segmentados.
    
    Este modelo representa la salida estructurada del proceso de clasificación,
    conteniendo todos los segmentos identificados en el mensaje del usuario.
    Es el modelo principal que se utiliza en todo el sistema para representar
    la clasificación de consultas de usuarios.
    """
    topic_details: List[Detail] = Field(
        default_factory=list,
        description="Lista de detalles de clasificación para cada segmento del mensaje"
    )

    requires_RAG: bool = Field(
        default=False,
        description="Indica si se requiere Retrieval Augmented Generation (RAG) para responder"
    )

    requires_reconcilier: bool = Field(
        default=False,
        description="Indica si se requiere el reconciliador para procesar la consulta"
    )
    
    # Configuración del modelo
    model_config = ConfigDict(
        extra='ignore',  # Ignorar campos extra en el JSON
        validate_assignment=True  # Validar asignaciones a los campos
    )
    
    # === VALIDATORS ===
    # @field_validator('primary_topics', mode='before')
    # @classmethod
    # def detect_topics(cls, v: Optional[List[QueryTopic]], values):
    #     """Detect all topics in the message"""
    #     data = values.data if values.data else {}
    #     print("\n", 50*"=")
    #     print ("DETECTED TOPICS WENT WELL...")
    #     print(50*"=", "\n")
    #     if 'original_message' not in data:
    #         return v or [QueryTopic.GENERAL]
        
    #     message = data['original_message'].lower()
    #     topics_found = []
        
    #     # Topic detection rules - collect all matches
    #     topic_keywords = {
    #         QueryTopic.MENU: ['menú', 'carta', 'plato', 'comida', 'sopa', 'ensalada', 'entrada'],
    #         QueryTopic.SERVICE_HOURS: ['hora', 'abren', 'cierran', 'horario', 'días'],
    #         QueryTopic.DELIVERY: ['domicilio', 'delivery', 'entrega', 'envi'],
    #         QueryTopic.PAYMENT: ['pago', 'tarjeta', 'efectivo', 'nequi', 'daviplata', 'transferencia', 'pagar'],
    #         QueryTopic.RESERVATION: ['reserva', 'mesa', 'cupo', 'reservar'],
    #         QueryTopic.COMPLAINT: ['queja', 'reclamo', 'problema', 'mal', 'error'],
    #         QueryTopic.INGREDIENTS: ['ingrediente', 'contiene', 'lleva', 'de qué es', 'hecho'],
    #         QueryTopic.ORDER_STATUS: ['estado', 'seguimiento', 'pedido', 'orden'],
    #         QueryTopic.SPECIAL_OFFERS: ['oferta', 'promoción', 'descuento', 'especial'],
    #         QueryTopic.ABOUT: ['historia', 'quienes', 'somos', 'restaurante', 'fundado']
    #     }
        
    #     # Check for each topic
    #     for topic, keywords in topic_keywords.items():
    #         for keyword in keywords:
    #             if keyword in message:
    #                 topics_found.append(topic)
    #                 break
        
    #     # If no topics found, use GENERAL
    #     if not topics_found:
    #         return [QueryTopic.GENERAL]
        
    #     return topics_found
    
    # @field_validator('required_documents', mode='before')
    # @classmethod
    # def set_required_documents(cls, v, values):
    #     """Determine which documents are needed"""
    #     info = values.data if values.data else {}
    #     print("\n", 50*"=")
    #     print(f" TOPIC_DETAILS: {info.get('topic_details', [])}")
    #     print(" ", 50*"=", "\n")
    #     if 'primary_topics' not in info:
    #         return []
        
    #     topics = info['primary_topics']
    #     documents_needed = set()
        
    #     document_mapping = {
    #         QueryTopic.MENU: [DocumentSource.MENU_FILE],
    #         QueryTopic.SERVICE_HOURS: [DocumentSource.SERVICE_INFO],
    #         QueryTopic.DELIVERY: [DocumentSource.SERVICE_INFO],
    #         QueryTopic.PAYMENT: [DocumentSource.SERVICE_INFO],
    #         QueryTopic.RESERVATION: [DocumentSource.WAITER_GUIDE],
    #         QueryTopic.ABOUT: [DocumentSource.ABOUT_US],
    #         QueryTopic.COMPLAINT: [DocumentSource.WAITER_GUIDE],
    #         QueryTopic.INGREDIENTS: [DocumentSource.MENU_FILE],
    #         QueryTopic.SPECIAL_OFFERS: [DocumentSource.MENU_FILE, DocumentSource.SERVICE_INFO],
    #     }
        
    #     for topic in topics:
    #         if topic in document_mapping:
    #             for doc in document_mapping[topic]:
    #                 documents_needed.add(doc)
        
    #     return list(documents_needed)
    
    # @field_validator('priority_document', mode='before')
    # @classmethod
    # def set_priority_document(cls, v, values):
    #     """Set primary document"""
    #     if 'required_documents' in values and values['required_documents']:
    #         return values['required_documents'][0]
    #     return None
    
    # @field_validator('query_type', mode='before')
    # @classmethod
    # def detect_query_type(cls, v, values):
    #     """Auto-detect ALL query types in the message"""
    #     info = values.data if values.data else {}
    #     if 'original_message' not in info:
    #         return v or [QueryType.CONSULTING]
        
    #     message = info['original_message'].lower()
    #     query_types = []
        
    #     # First, check if it's a simple single-type query
    #     # Greeting detection
    #     greetings = ['hola', 'buenos', 'buenas', 'hello', 'hi']
    #     if any(word in message for word in greetings) and len(message.split()) < 4:
    #         query_types.append(QueryType.GREETING)
        
    #     # Farewell detection (usually exclusive)
    #     farewells = ['adiós', 'gracias', 'chao', 'bye', 'nos vemos']
    #     if any(word in message for word in farewells) and len(message.split()) < 5:
    #         query_types.append(QueryType.FAREWELL)
        
    #     # Confirmation detection (usually exclusive)
    #     confirmations = ['sí', 'si', 'no', 'ok', 'vale', 'correcto', 'confirmo']
    #     if any(word == message.strip().lower().rstrip('?.!') for word in confirmations):
    #         query_types.append(QueryType.CONFIRMATION)
        
    #     # For multi-part messages, detect all types present
    #     # Check for ORDERING keywords
    #     ordering_keywords = ['quiero', 'deseo', 'ordenar', 'pedir', 'me gustaría', 'voy a tomar', 'me trae']
    #     if any(word in message for word in ordering_keywords):
    #         query_types.append(QueryType.ORDERING)
        
    #     # Check for CONSULTING (questions)
    #     if '?' in message or any(word in message for word in ['cuánto', 'qué', 'cómo', 'dónde', 'cuándo', 'quién', 'por qué']):
    #         query_types.append(QueryType.CONSULTING)
        
    #     # Check for ACTION requests
    #     action_keywords = ['necesito', 'puede', 'podría', 'haga', 'hacer', 'reservar', 'cancelar', 'modificar']
    #     if any(word in message for word in action_keywords):
    #         query_types.append(QueryType.ACTION)
        
    #     # Check for COMPLAINT
    #     complaint_keywords = ['queja', 'reclamo', 'problema', 'mal', 'error', 'insatisfecho', 'decepcionado']
    #     if any(word in message for word in complaint_keywords):
    #         query_types.append(QueryType.COMPLAINT)
        
    #     # Check for CLARIFICATION requests
    #     clarification_keywords = ['qué quiere decir', 'qué significa', 'puede explicar', 'aclarar', 'no entiendo']
    #     if any(word in message for word in clarification_keywords):
    #         query_types.append(QueryType.CLARIFICATION)
        
    #     # If no types detected, default to CONSULTING
    #     if not query_types:
    #         query_types.append(QueryType.CONSULTING)
        
    #     # Return as list, with CONSULTING first if it's present with others
    #     # result = list(query_types)
        
    #     # Sort for consistency: CONSULTING first, then others
    #     # if QueryType.CONSULTING in result:
    #     #     result.remove(QueryType.CONSULTING)
    #     #     result.insert(0, QueryType.CONSULTING)
        
    #     return query_types
    
    # === HELPER METHODS ===
    def get_conversation_strategy(self) -> Dict[str, Any]:
        """Get conversation strategy based on classification"""
        
        strategies = {
            QueryType.CONSULTING: {
                "action": "provide_information",
                "next_step": "retrieve_and_present",
                "tone": "informative",
                "requires_details": True
            },
            QueryType.ORDERING: {
                "action": "start_order_flow",
                "next_step": "ask_for_dish",
                "tone": "helpful",
                "requires_details": True
            },
            QueryType.GREETING: {
                "action": "greet_back",
                "next_step": "ask_how_can_help",
                "tone": "warm",
                "requires_details": False
            },
            QueryType.CONFIRMATION: {
                "action": "acknowledge",
                "next_step": "continue_flow",
                "tone": "confirming",
                "requires_details": False
            }
        }
        
        return strategies.get(self.query_type, {
            "action": "general_assistance",
            "next_step": "clarify",
            "tone": "neutral"
        })
    
    def get_response_template(self) -> str:
        """Get response template based on classification"""

        if len(self.primary_topics) > 1:
            topic_names = ", ".join([topic.value for topic in self.primary_topics])
            return f"Veo que tienes preguntas sobre {topic_names}. Permíteme responderte cada una:"
        
        templates = {
            (QueryType.CONSULTING, QueryTopic.MENU): 
                "Te comparto información sobre {dish}: {info}. ¿Te gustaría ordenarlo?",
            
            (QueryType.CONSULTING, QueryTopic.SERVICE_HOURS):
                "Nuestro horario es: {hours}. ¿Te gustaría reservar?",
            
            (QueryType.ORDERING, QueryTopic.MENU):
                "¡Perfecto! ¿{dish} en tamaño corriente o mini?",
            
            QueryType.GREETING:
                "¡Hola! Soy Luz Stella de Sabor Casero. ¿En qué puedo ayudarte hoy? 😊",
            
            QueryType.CONFIRMATION:
                "✅ Entendido. Continuemos: {next_question}"
        }
        
        # Try specific combination first
        key = (self.query_type, self.primary_topics)
        if key in templates:
            return templates[key]
        
        # Fallback to query type
        if self.query_type in templates:
            return templates[self.query_type]
        
        return "¿En qué más puedo ayudarte?"
    
    def should_ask_clarifying_question(self) -> bool:
        """Determine if clarification is needed"""
        if self.needs_clarification:
            return True
        
        # Ask for clarification if consulting about menu but no dish mentioned
        if (self.query_type == QueryType.CONSULTING and 
            self.primary_topics == QueryTopic.MENU and 
            not self.mentioned_dishes):
            return True
        
        return False
    
    def get_clarifying_question(self) -> Optional[str]:
        """Get appropriate clarifying question"""
        if self.query_type == QueryType.CONSULTING and self.primary_topics == QueryTopic.MENU:
            if not self.mentioned_dishes:
                return "¿Sobre qué plato específico te gustaría información?"
            if self.mentioned_prices:
                return "¿Quieres saber el precio de algún plato en particular?"
        
        return None