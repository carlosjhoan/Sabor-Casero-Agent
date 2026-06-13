from .manager import ConversationStateManager
from analyze_msg_with_llm import analyze_message_with_llm
from .menu_state import MenuInteraction

class StateAwareAssistant:
    """Main assistant with state tracking"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.state_manager = ConversationStateManager()
        
    def process_message(self, user_id: str, message: str) -> str:
        """Process a user message with state tracking"""
        
        # 1. Get session ID
        session_id = self.state_manager.get_session_id(user_id)
        
        # 2. Get current state
        current_state = self.state_manager.get_or_create_state(session_id)
        print(f"📊 Current state:\n{current_state.to_checklist()}")
        
        # 3. Analyze new message with LLM
        print(f"🔍 Analyzing message: {message}")
        analysis = analyze_message_with_llm(
            message=message,
            previous_state=current_state,
            llm_client=self.llm_client
        )
        
        # 4. Update state with analysis
        updated_state = self.state_manager.update_from_analysis(session_id, analysis)
        print(f"📊 Updated state:\n{updated_state.to_checklist()}")
        
        # 5. Determine response based on updated state
        if updated_state.is_consulting:
            response = self._handle_consultation(updated_state, message)
        elif updated_state.is_ordering:
            response = self._handle_ordering(updated_state, message)
        else:
            response = ""
        
        return response
    
    def _handle_consultation(self, state: MenuInteraction, message: str) -> str:
        """Handle consultation queries"""
        # You would integrate with your RAG system here
        # if state.consulting_topic == "price":
        #     return "La Bandeja Mixta cuesta $15,000 COP. ¿Te gustaría ordenarla?"
        # elif state.consulting_topic == "menu":
        #     return "Te comparto nuestro menú... ¿Te gustaría ordenar algo?"
        # else:
        #     return "Con gusto te ayudo con esa información. ¿Algo más en lo que pueda asistirte?"
        if state.consulting_topic == "unknown":
            return state.consulting_topic

        elif state.consulting_topic == "menu":
            return "Comentarle al cliente que quedas atento/a a tomarle el pedido"

        else:
            return "No hay pregunta sugerida. El asistente puede responder con la información suministrada"
    
    def _handle_ordering(self, state: MenuInteraction, message: str) -> str:
        """Handle ordering flow"""
        # Acknowledge what was provided
        acknowledgment = ""
        if state.ordering_field:
            field_name = state.ordering_field.value
            value = state.get_field_value(state.ordering_field)
            acknowledgment = f"✅ {field_name}: {value} registrado. "
        
        # Add next question
        next_q = state.get_next_question()
        
        # If order is complete, offer confirmation
        if not state.missing_info:
            order_summary = self._format_order_summary(state)
            return f"{acknowledgment}Tu pedido está completo:\n\n{order_summary}\n\n¿Confirmas este pedido?"
        
        return f"{acknowledgment}{next_q}"
    
    def _format_order_summary(self, state: MenuInteraction) -> str:
        """Format order summary"""
        lines = []
        if state.dish_name:
            lines.append(f"🍽️ **Plato:** {state.dish_name}")
        if state.size_value:
            lines.append(f"📏 **Tamaño:** {state.size_value.value}")
        if state.side_value:
            lines.append(f"🥗 **Acompañamiento:** {state.side_value.value}")
        if state.beverage_value:
            lines.append(f"🥤 **Bebida:** {state.beverage_value}")
        if state.method_value:
            lines.append(f"🚚 **Método:** {state.method_value}")
        if state.address_value and state.method_value == "delivery":
            lines.append(f"📍 **Dirección:** {state.address_value}")
        if state.payment_value:
            lines.append(f"💳 **Pago:** {state.payment_value}")
        if state.observation_value:
            lines.append(f"📝 **Observación:** {state.observation_value}")
        
        return "\n".join(lines)
    
    def reset_conversation(self, user_id: str):
        """Reset conversation for a user"""
        session_id = self.state_manager.get_session_id(user_id)
        self.state_manager.clear_state(session_id)
        return "Conversación reiniciada. ¿En qué puedo ayudarte?"