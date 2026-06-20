from pydantic import BaseModel, Field, computed_field
from typing import List, Optional, Union, Dict
from enum import Enum
from datetime import datetime
import uuid

class OrderStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class ServiceCategory(str, Enum):
    """Categoría de servicio - para identificación rápida"""
    DELIVERY = "delivery"
    PICKUP = "pickup"

class DeliveryDetails(BaseModel):
    """Detalles específicos para servicio a domicilio"""
    address: str = Field(..., description="Dirección completa de entrega")
    fee: float = Field(0.0, description="Costo de envío")
    estimated_time: Optional[int] = Field(None, description="Tiempo estimado en minutos")
    instructions: Optional[str] = Field(None, description="Instrucciones adicionales para el domiciliario")
    
    def calculate_total_with_fee(self, subtotal: float) -> float:
        """Calcula total incluyendo fee de delivery"""
        return subtotal + self.fee
    
class PickupDetails(BaseModel):
    """Detalles específicos para recoger en local"""
    scheduled_time: Optional[datetime] = Field(None, description="Hora programada para recoger")
    instructions: Optional[str] = Field(None, description="Instrucciones para la recogida")
    
    def calculate_total_with_fee(self, subtotal: float) -> float:
        """Sin fee adicional para pickup"""
        return subtotal
    
class ServiceDetails(BaseModel):
    """
    Modelo unificado que contiene los detalles específicos según el tipo de servicio.
    Usa Union para representar los diferentes tipos posibles.
    """
    category: ServiceCategory
    details: Union[DeliveryDetails, PickupDetails]
    
    @property
    def type_name(self) -> str:
        """Nombre legible del tipo de servicio"""
        mapping = {
            ServiceCategory.DELIVERY: "A domicilio",
            ServiceCategory.PICKUP: "Para recoger"
            # ServiceCategory.DINE_IN: "En el restaurante"
        }
        return mapping.get(self.category, "Desconocido")
    
    def calculate_total(self, subtotal: float) -> float:
        """Delega el cálculo al tipo específico de servicio"""
        return self.details.calculate_total_with_fee(subtotal)
    
    @classmethod
    def create_delivery(cls, address: str, fee: float = 0.0, **kwargs) -> 'ServiceDetails':
        """Factory method para crear servicio a domicilio"""
        return cls(
            category=ServiceCategory.DELIVERY,
            details=DeliveryDetails(address=address, fee=fee, **kwargs)
        )
    
    @classmethod
    def create_pickup(cls, scheduled_time: Optional[datetime] = None, **kwargs) -> 'ServiceDetails':
        """Factory method para crear servicio para llevar"""
        return cls(
            category=ServiceCategory.PICKUP,
            details=PickupDetails(scheduled_time=scheduled_time, **kwargs)
        )

class OrderItem(BaseModel):
    id: str = Field(default_factory=lambda: f"item_{uuid.uuid4().hex[:6]}")
    quantity: int = Field(default=1, ge=1)
    protein: Optional[str] = None
    principle: Optional[str] = None  # El "principio" (frijoles, lentejas, etc.)
    # sides: List[str] = []  # Acompañamientos (arroz, yuca, ensalada, jugo)
    size: Optional[str] = None  # "corriente", "mini"
    unit_price: float = 0.0
    requirements: List[str] = []

    @computed_field
    def subtotal(self) -> float:
        return self.unit_price * self.quantity
    
    def to_summary(self) -> str:
        parts = [f"item_id:{self.id} --> {self.quantity}x {self.protein or '?'}"]
        
        if self.principle:
            parts.append(f"principio: {self.principle}")
        
        # if self.sides:
        #     parts.append(f"acompañamientos: {', '.join(self.sides)}")
        
        if self.size and self.size != "corriente":
            parts.append(f"({self.size})")
        
        if self.requirements:
            reqs = ", ".join(self.requirements)
            parts.append(f"[{reqs}]")
        
        return " | ".join(parts)
    
    def to_dict(self) -> dict:
        """
        Convierte el OrderItem a diccionario plano para JSON/LLM.
        Excluye campos computados como subtotal (se calcula en demanda).
        """
        return {
            "item_id": self.id,
            "quantity": self.quantity,
            "protein": self.protein,
            "size": self.size,
            "unit_price": self.unit_price,
            "requirements": self.requirements.copy(),  # Copia para evitar mutaciones
            "subtotal": self.subtotal  # Incluimos el computed_field
        }

class FieldStatus(BaseModel):
    """Estado completo de un campo del pedido.

    Reemplaza los antiguos field_states + field_notes en un solo objeto.
    """
    state: str = "pending"
    notes: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class Order(BaseModel):
    id: str = Field(default_factory=lambda: f"ORD-{uuid.uuid4().hex[:6].upper()}")
    customer_id: Optional[str] = None
    status: OrderStatus = OrderStatus.DRAFT
    items: List[OrderItem] = Field(default_factory=list)
    
    # Servicio - ahora es un objeto completo con todos los detalles
    service: Optional[ServiceDetails] = None
    
    # Acompañamiento
    con_todo: Optional[str] = Field(
        default=None,
        description="None=no preguntado, 'sí'=confirmado con todo el acompañamiento"
    )
    
    # Pago
    payment_method: Optional[str] = None
    payment_status: str = "pending"
    
    # Metadata
    observations: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @computed_field
    @property
    def subtotal(self) -> float:
        """Suma de todos los items sin incluir fees"""
        return sum(item.subtotal for item in self.items)
    
    @computed_field
    @property
    def total_amount(self) -> float:
        """
        Total incluyendo fees según el tipo de servicio.
        Delega el cálculo al objeto service.
        """
        if self.service:
            return self.service.calculate_total(self.subtotal)
        return self.subtotal
    
    @computed_field
    @property
    def service_type(self) -> Optional[str]:
        """Retorna el tipo de servicio como string (para compatibilidad)"""
        return self.service.type_name if self.service else None
    
    @computed_field
    @property
    def address(self) -> Optional[str]:
        """Retorna la dirección si es delivery (para compatibilidad)"""
        if self.service and self.service.category == ServiceCategory.DELIVERY:
            return self.service.details.address
        return None
    
    @computed_field
    @property
    def delivery_fee(self) -> float:
        """Retorna el fee si es delivery (para compatibilidad)"""
        if self.service and self.service.category == ServiceCategory.DELIVERY:
            return self.service.details.fee
        return 0.0

    def to_summary(self) -> str:
        """Genera versión compacta para el Extractor."""
        if not self.items:
            return "Pedido vacío."
        
        items_summary = " | ".join([f"{i.to_summary()}" for i in self.items])
        service_info = f" [{self.service.type_name}]" if self.service else ""
        
        return f"{items_summary}{service_info}"

    def to_dict(self) -> dict:
        """Convierte a diccionario plano para JSON/LLM."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "status": self.status,
            "items": [item.model_dump() for item in self.items],
            "service": self.service.model_dump() if self.service else None,
            "payment_method": self.payment_method,
            "con_todo": self.con_todo,
            "subtotal": self.subtotal,
            "total": self.total_amount,
            "created_at": self.created_at.isoformat(),
            "observations": self.observations
        }
    
    def set_delivery(self, address: str, fee: float = 0.0, **kwargs) -> None:
        """Establece servicio a domicilio"""
        self.service = ServiceDetails.create_delivery(address=address, fee=fee, **kwargs)
    
    def set_pickup(self, scheduled_time: Optional[datetime] = None, **kwargs) -> None:
        """Establece servicio para llevar"""
        self.service = ServiceDetails.create_pickup(scheduled_time=scheduled_time, **kwargs)
    
    # def set_dine_in(self, guests: int = 1, table_number: Optional[int] = None, **kwargs) -> None:
    #     """Establece servicio en el restaurante"""
    #     self.service = ServiceDetails.create_dine_in(guests=guests, table_number=table_number, **kwargs)
        
    def add_item(self, item: OrderItem) -> None:
        """
        Añade un item a la orden.
        Reglas de negocio:
        - No duplicar items idénticos
        - Validar límites de cantidad
        """
        # Validar negocio
        # if len(self.items) >= 20:
        #     raise ValueError("Máximo 20 items por orden")
        
        # Añadir item
        self.items.append(item)
        self.updated_at = datetime.now()
        print(f"   ✅ Item añadido a orden {self.id}: {item.to_summary()}")
    
    def update_item(self, item_id: str, **changes) -> None:
        """
        Actualiza un item existente.
        Los changes pueden incluir: quantity, protein, principle, size,
        add_requirements, remove_requirements
        """
        item = self._find_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} no encontrado")
        
        # Aplicar cambios simples
        simple_fields = ['quantity', 'protein', 'principle', 'size', 'unit_price']
        for field in simple_fields:
            if field in changes:
                setattr(item, field, changes[field])
        
        # Manejar requirements
        if 'add_requirements' in changes:
            for req in changes['add_requirements']:
                if req not in item.requirements:
                    item.requirements.append(req)
        
        if 'remove_requirements' in changes:
            for req in changes['remove_requirements']:
                if req in item.requirements:
                    item.requirements.remove(req)
        
        # Si se envía 'requirements' directamente, reemplazar todo
        if 'requirements' in changes:
            item.requirements = changes['requirements'].copy()
        
        self.updated_at = datetime.now()
        print(f"   ✅ Item actualizado en orden {self.id}: {item_id}")
    
    def remove_item(self, item_id: str) -> OrderItem:
        """
        Elimina un item de la orden y lo retorna.
        """
        item = self._find_item(item_id)
        if not item:
            raise ValueError(f"Item {item_id} no encontrado")
        
        self.items = [i for i in self.items if i.id != item_id]
        self.updated_at = datetime.now()
        print(f"   ✅ Item eliminado de orden {self.id}: {item_id}")
        return item
    
    def update_order_metadata(self, **changes) -> None:
        """
        Actualiza metadatos del pedido (no items).
        
        Args:
            customer_name: Nombre del cliente
            service_type: "delivery" o "pickup"
            address: Dirección de entrega (si delivery)
            scheduled_time: Hora de recogida (si pickup)
            payment_method: Método de pago
            observations: Observaciones adicionales
        """
        if 'customer_name' in changes:
            self.customer_id = changes.pop('customer_name')
        
        if 'service_type' in changes:
            st = changes.pop('service_type').lower()
            if st == 'delivery':
                addr = changes.pop('address', '')
                self.set_delivery(address=addr)
            elif st in ('pickup', 'takeaway'):
                sched = changes.pop('scheduled_time', None)
                self.set_pickup(scheduled_time=sched)
        
        if 'address' in changes and self.service:
            if self.service.category == ServiceCategory.DELIVERY:
                self.service.details.address = changes.pop('address')
        
        if 'scheduled_time' in changes and self.service:
            if self.service.category == ServiceCategory.PICKUP:
                self.service.details.scheduled_time = changes.pop('scheduled_time')
        
        if 'payment_method' in changes:
            self.payment_method = changes.pop('payment_method')
        
        if 'observations' in changes:
            obs = changes.pop('observations')
            if isinstance(obs, list):
                self.observations.extend(obs)
            else:
                self.observations.append(obs)
        
        self.updated_at = datetime.now()
        print(f"   ✅ Metadatos de orden {self.id} actualizados: {list(changes.keys())}")
    
    def _find_item(self, item_id: str) -> Optional[OrderItem]:
        """Busca un item por ID (método auxiliar)"""
        return next((item for item in self.items if item.id == item_id), None)
    
    def validate_order(self) -> List[str]:
        """
        Valida toda la orden y retorna lista de errores.
        """
        errors = []
        
        # Validar que haya al menos un item
        if not self.items:
            errors.append("La orden debe tener al menos un item")
        
        # Validar que los items tengan proteína
        for i, item in enumerate(self.items):
            if not item.protein:
                errors.append(f"Item {i+1} no tiene proteína especificada")
        
        return errors
    
    def is_valid(self) -> bool:
        """Retorna True si la orden es válida"""
        return len(self.validate_order()) == 0
