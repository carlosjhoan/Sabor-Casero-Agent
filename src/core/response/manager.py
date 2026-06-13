from .menu_state import MenuInteraction, OrderSize, SideDish
import json
import hashlib
from typing import Dict
import time

class ConversationStateManager:
    """
    Manages conversation states across multiple users/sessions
    """
    
    def __init__(self, storage_path: str = "Sabor_Casero_info/conversation_states.json"):
        self.storage_path = storage_path
        self.active_states: Dict[str, MenuInteraction] = {}
        self.load_states()
    
    def get_or_create_state(self, session_id: str) -> MenuInteraction:
        """Get existing state or create new one"""
        if session_id not in self.active_states:
            self.active_states[session_id] = MenuInteraction()
        return self.active_states[session_id]
    
    def update_state(self, session_id: str, new_state: MenuInteraction):
        """Update state for a session"""
        self.active_states[session_id] = new_state
        self.save_states()
    
    def update_from_analysis(self, session_id: str, analysis: MenuInteraction):
        """Merge analysis with existing state"""
        current = self.get_or_create_state(session_id)
        
        # Merge: Only update fields that have values in the analysis
        if analysis.is_consulting:
            current.is_consulting = True
            current.is_ordering = False
            if analysis.consulting_topic:
                current.consulting_topic = analysis.consulting_topic
        
        if analysis.is_ordering:
            current.is_ordering = True
            current.is_consulting = False
            
            # Update specific fields if provided
            if analysis.dish_name:
                current.dish_name = analysis.dish_name
            if analysis.size_value:
                current.size_value = analysis.size_value
            if analysis.side_value:
                current.side_value = analysis.side_value
            if analysis.beverage_value:
                current.beverage_value = analysis.beverage_value
            if analysis.method_value:
                current.method_value = analysis.method_value
            if analysis.address_value:
                current.address_value = analysis.address_value
            if analysis.payment_value:
                current.payment_value = analysis.payment_value
            if analysis.observation_value:
                current.observation_value = analysis.observation_value
        
        # Update metadata
        current.message_count += 1
        current.timestamp = time.time()
        
        # Recalculate next question and missing info
        current.next_question = current.get_next_question()
        current.update_missing_info()
        
        self.update_state(session_id, current)
        return current
    
    def clear_state(self, session_id: str):
        """Clear state for a session (e.g., after order completion)"""
        self.active_states[session_id] = MenuInteraction()
        self.save_states()
    
    def save_states(self):
        """Save states to disk"""
        try:
            # Convert to serializable format
            serializable = {
                session_id: state.dict() 
                for session_id, state in self.active_states.items()
            }
            
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(serializable, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving states: {e}")
    
    def load_states(self):
        """Load states from disk"""
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for session_id, state_data in data.items():
                # Convert string enums back to Enum instances
                if 'size_value' in state_data and state_data['size_value']:
                    state_data['size_value'] = OrderSize(state_data['size_value'])
                if 'side_value' in state_data and state_data['side_value']:
                    state_data['side_value'] = SideDish(state_data['side_value'])
                
                self.active_states[session_id] = MenuInteraction(**state_data)
        except FileNotFoundError:
            print(f"No existing state file found at {self.storage_path}")
        except Exception as e:
            print(f"Error loading states: {e}")
    
    def get_session_id(self, user_id: str, thread_id: str = "default") -> str:
        """Generate consistent session ID"""
        # Combine user and thread for unique session
        combined = f"{user_id}_{thread_id}"
        return hashlib.md5(combined.encode()).hexdigest()[:10]