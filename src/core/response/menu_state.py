from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
import time


# Enums for structured data
class OrderField(str, Enum):
    DISH = "dish"
    SIZE = "size" 
    SIDE = "side"
    BEVERAGE = "beverage"
    METHOD = "method"
    ADDRESS = "address"
    PAYMENT = "payment"
    OBSERVATION = "observation"

class OrderSize(str, Enum):
    CORRIENTE = "corriente"
    MINI = "mini"

class SideDish(str, Enum):
    MACARRON = "macarrón"
    GUISO_YOTA = "guiso de yota"
    MIXTO = "mixto"

# Main interaction model
class MenuInteraction(BaseModel):
    """
    Tracks menu-related interactions with the customer
    """
    # Intent classification
    is_consulting: bool = Field(
        default=False,
        description="True if user is asking about menu items"
    )
    is_ordering: bool = Field(
        default=False,
        description="True if user is ordering something"
    )
    
    # What specifically
    consulting_topic: Optional[str] = Field(
        default=None,
        description="What they're asking about (dish, price, ingredients, etc.)"
    )
    ordering_field: Optional[OrderField] = Field(
        default=None,
        description="Which order field they're specifying in THIS message"
    )
    
    # Extracted values (cumulative across conversation)
    dish_name: Optional[str] = Field(
        default=None,
        description="Dish name mentioned"
    )
    size_value: Optional[OrderSize] = Field(
        default=None,
        description="Size mentioned (corriente/mini)"
    )
    side_value: Optional[SideDish] = Field(
        default=None,
        description="Side dish mentioned"
    )
    beverage_value: Optional[str] = Field(
        default=None,
        description="Beverage mentioned"
    )
    method_value: Optional[str] = Field(
        default=None,
        description="Service method (delivery/recoger)"
    )
    address_value: Optional[str] = Field(
        default=None,
        description="Delivery address"
    )
    payment_value: Optional[str] = Field(
        default=None,
        description="Payment method"
    )
    observation_value: Optional[str] = Field(
        default=None,
        description="Special instructions"
    )
    
    # Context and flow
    next_question: Optional[str] = Field(
        default=None,
        description="What to ask next based on current state"
    )
    missing_info: List[OrderField] = Field(
        default_factory=list,
        description="What information is still missing"
    )
    
    # Metadata
    timestamp: float = Field(
        default_factory=time.time,
        description="When this interaction was created/updated"
    )
    message_count: int = Field(
        default=1,
        description="Number of messages in this conversation"
    )
    
    def get_field_value(self, field: OrderField) -> Optional[str]:
        """Get value for a specific field"""
        field_map = {
            OrderField.DISH: self.dish_name,
            OrderField.SIZE: self.size_value.value if self.size_value else None,
            OrderField.SIDE: self.side_value.value if self.side_value else None,
            OrderField.BEVERAGE: self.beverage_value,
            OrderField.METHOD: self.method_value,
            OrderField.ADDRESS: self.address_value,
            OrderField.PAYMENT: self.payment_value,
            OrderField.OBSERVATION: self.observation_value
        }
        return field_map.get(field)
    
    def set_field_value(self, field: OrderField, value: str):
        """Set value for a specific field"""
        if field == OrderField.DISH:
            self.dish_name = value
        elif field == OrderField.SIZE:
            self.size_value = OrderSize(value) if value in OrderSize._value2member_map_ else None
        elif field == OrderField.SIDE:
            self.side_value = SideDish(value) if value in SideDish._value2member_map_ else None
        elif field == OrderField.BEVERAGE:
            self.beverage_value = value
        elif field == OrderField.METHOD:
            self.method_value = value
        elif field == OrderField.ADDRESS:
            self.address_value = value
        elif field == OrderField.PAYMENT:
            self.payment_value = value
        elif field == OrderField.OBSERVATION:
            self.observation_value = value
    
    def update_missing_info(self):
        """Recalculate what information is still missing"""
        self.missing_info = []
        
        if not self.is_ordering:
            return
        
        # Define order workflow
        workflow = [
            OrderField.DISH,
            OrderField.SIZE,
            OrderField.SIDE,
            OrderField.BEVERAGE,
            OrderField.METHOD,
            OrderField.ADDRESS,  # Only if delivery
            OrderField.PAYMENT,
            OrderField.OBSERVATION  # Optional
        ]
        
        for field in workflow:
            # Address only required for delivery
            if field == OrderField.ADDRESS and self.method_value != "delivery":
                continue
            
            # Observation is optional
            if field == OrderField.OBSERVATION:
                continue
            
            if self.get_field_value(field) is None:
                self.missing_info.append(field)
    
    def get_next_question(self) -> str:
        """Determine what to ask next"""
        self.update_missing_info()
        
        if not self.missing_info:
            return "¿Confirmas este pedido?"
        
        next_field = self.missing_info[0]
        
        question_map = {
            OrderField.DISH: "Preguntar por la proteína",
            OrderField.SIZE: "Preguntar por el tamaño si el almuerzo tiene variante de tamaño",
            OrderField.SIDE: "Preguntar por el principio si el almuerzo tiene  variante de principio",
            OrderField.BEVERAGE: "Preguntar por el tipo de bebida si el almuerzo ofrece variante de bebida",
            OrderField.METHOD: "Preguntar por el método de servicio: Delivery o pasar a recoger (Pickup)",
            OrderField.ADDRESS: "Si el usuario que el pedido le sea entregado por delivery, hay que preguntar por alguna dirección de entrega",
            OrderField.PAYMENT: "Preguntar por el método de pago que prefiera el usuario entre las variantes disponibles",
            OrderField.OBSERVATION: "Preguntar por alguna observación que el usuario desea que se tenga en cuenta"
        }
        
        return question_map.get(next_field, "¿En qué más puedo ayudarte?")
    
    def to_checklist(self) -> str:
        """Convert to human-readable checklist"""
        lines = []
        
        if self.is_consulting:
            lines.append("📋 **CONSULTA**")
            if self.consulting_topic:
                lines.append(f"Tema: {self.consulting_topic}")
        
        elif self.is_ordering:
            lines.append("📋 **PEDIDO EN CURSO**")
            
            fields = [
                ("🍽️ Plato", OrderField.DISH, self.dish_name),
                ("📏 Tamaño", OrderField.SIZE, self.size_value.value if self.size_value else None),
                ("🥗 Acompañamiento", OrderField.SIDE, self.side_value.value if self.side_value else None),
                ("🥤 Bebida", OrderField.BEVERAGE, self.beverage_value),
                ("🚚 Método", OrderField.METHOD, self.method_value),
                ("📍 Dirección", OrderField.ADDRESS, self.address_value),
                ("💳 Pago", OrderField.PAYMENT, self.payment_value),
                ("📝 Observación", OrderField.OBSERVATION, self.observation_value)
            ]
            
            for label, field, value in fields:
                if field == OrderField.ADDRESS and self.method_value != "delivery":
                    lines.append(f"⏭️ {label}: [NO APLICA - no es delivery]")
                elif value:
                    lines.append(f"✅ {label}: {value}")
                elif field in self.missing_info:
                    lines.append(f"🔵 {label}: [PREGUNTANDO AHORA]")
                else:
                    lines.append(f"⚪ {label}: [PENDIENTE]")
            
            if self.missing_info:
                lines.append(f"\n🔍 **FALTANTE:** {', '.join([f.value for f in self.missing_info])}")
        
        return "\n".join(lines)