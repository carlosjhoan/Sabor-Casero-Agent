import json
import os
from pathlib import Path
from uuid import uuid4
from typing import Optional

# Asumiendo que tus modelos están en domain.models
from src.core.order.domain.models import Order, OrderItem 
from src.core.order.domain.order_repository_interface import OrderRepository

class JsonOrderRepository(OrderRepository):
    def __init__(self, storage_dir: str = "data/orders"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, order_id: str) -> Path:
        """Construye la ruta del archivo para una orden específica."""
        return self.storage_dir / f"{order_id}.json"

    def create_order(self, customer_id: str = "anonymous") -> Order:
        """
        Crea una nueva instancia de Order y asegura su persistencia inicial.
        """
        try:
            # 1. Generación de identidad
            order_id = f"ORD-{uuid4().hex[:6].upper()}"
            new_order = Order(id=order_id, customer_id=customer_id, status="draft")
            
            # 2. Persistencia (Reserva del ID en disco)
            # Delegamos la responsabilidad a save_order, que ya debería tener su propio try-except
            self.save_order(new_order)
            
            return new_order

        except Exception as e:
            # Logueamos el error con contexto
            print(f"💥 Error crítico al crear orden para {customer_id}: {str(e)}")
            # En arquitectura limpia, a veces es mejor relanzar una excepción personalizada
            # para que la capa de Aplicación (el Processor) sepa que algo falló.
            raise RuntimeError(f"No se pudo inicializar la persistencia del pedido: {e}")

    def save_order(self, order: Order):
        """Convierte el objeto Order a un diccionario y lo guarda como JSON en el disco."""
        file_path = self._get_path(order.id)
        
        try:
            # 1. Validación previa de la data
            # Si to_dict() falla, el error se captura antes de tocar el disco
            order_data = order.to_dict() 
            
            # 2. Asegurar que el directorio existe (por si alguien lo borró en caliente)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # 3. Escritura segura
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(order_data, f, indent=2, ensure_ascii=False)
                
            print(f"💾 Orden {order.id} guardada exitosamente.")

        except (TypeError, ValueError) as e:
            # Error específico de serialización JSON (data inválida)
            print(f"❌ Error de formato en la orden {order.id}: {e}")
            raise ValueError(f"La orden contiene datos no válidos para JSON: {e}")
            
        except (OSError, IOError) as e:
            # Error específico de disco (permisos, espacio, etc)
            print(f"❌ Error físico de disco al guardar {order.id}: {e}")
            raise RuntimeError(f"No se pudo escribir en el sistema de archivos: {e}")

        except Exception as e:
            # Error inesperado
            print(f"🔥 Error imprevisto al guardar {order.id}: {e}")
            raise

    def get_order_by_id(self, order_id: str) -> Optional[Order]:
        """
        Busca el archivo JSON y reconstruye el objeto Order.
        Diferencia entre 'No existe' y 'Error de sistema'.
        """
        file_path = self._get_path(order_id)
        
        # 1. Caso esperado: La orden simplemente no existe
        if not file_path.exists():
            # Aquí está bien el log informativo y devolver None
            # porque es un flujo de negocio normal (ej. buscar orden previa)
            print(f"🔍 Orden no encontrada: {order_id}")
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            order = Order(**data)
            
            # 2. Reconstrucción del objeto de dominio
            # Si from_dict falla es porque el JSON tiene campos inválidos
            return order

        except json.JSONDecodeError as e:
            print(f"❌ El archivo de la orden {order_id} está corrupto (JSON inválido): {e}")
            # Aquí podrías decidir si mover el archivo corrupto a una carpeta de 'backup'
            raise ValueError(f"No se pudo decodificar el archivo de la orden {order_id}")

        except (KeyError, TypeError) as e:
            print(f"❌ Estructura de datos incompatible en orden {order_id}: {e}")
            raise TypeError(f"El formato del JSON no coincide con el modelo Order: {e}")

        except Exception as e:
            print(f"🔥 Error inesperado al recuperar la orden {order_id}: {e}")
            raise

    def delete_order(self, order_id: str):
        """
        Elimina el archivo físico de la orden.
        Maneja errores de permisos y bloqueos de sistema.
        """
        file_path = self._get_path(order_id)
        
        try:
            if file_path.exists():
                file_path.unlink() # Intenta borrar el archivo
                print(f"🗑️ Orden {order_id} eliminada físicamente.")
            else:
                # No lanzamos excepción porque si el archivo no existe, 
                # el objetivo (que no esté) ya se cumple.
                print(f"⚠️ Intento de eliminar orden {order_id}, pero no existía el archivo.")

        except PermissionError:
            # El archivo está siendo usado por otro proceso o no hay permisos
            print(f"❌ Error de permisos: No se pudo eliminar {order_id}. Puede estar abierto.")
            raise RuntimeError(f"Permiso denegado al intentar borrar la orden {order_id}.")
            
        except OSError as e:
            # Errores de sistema de bajo nivel
            print(f"❌ Error de sistema al eliminar la orden {order_id}: {e}")
            raise RuntimeError(f"Error técnico al eliminar el archivo de la orden: {e}")