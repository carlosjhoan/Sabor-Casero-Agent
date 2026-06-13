"""
Gradio interface for the assistant
"""
import gradio as gr
from typing import List, Optional
import sys
import os
import asyncio
from src.utils.utils import print_section
from src.core.assistant import SaborCaseroAssistant
from src.core.order.domain.session_repository_interface import SessionData

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GradioAssistantApp:
    """
    Gradio interface wrapper
    """
    def __init__(self, assistant: SaborCaseroAssistant=None):
        # Initialize assistant
        self.assistant = assistant
        
        
        # Conversation history cache
        self.sessions = {}
    
    async def chat_interface(self, message: str, history: List, session_id: str = None):
        """
        Gradio chat interface con:
        - Formato de mensajes compatible con Gradio 6.x
        - Mensaje inmediato del usuario
        - Indicador de "escribiendo" mientras procesa
        """
        user_id = "default_user"
        
        # 1. Crear sesión si no existe
        if not session_id:
            session: SessionData = self.assistant.orchestrator.action_planner.session_repository.create_session(customer_id=user_id)
            session_id = session.session_id
            print_section(head="Nueva sesión creada", msg=session_id)

        # 2. Convertir history al formato de Gradio 6 si es necesario
        chat_history = []
        if history:
            for item in history:
                if isinstance(item, dict) and "role" in item:
                    # Ya es formato Gradio 6
                    chat_history.append(item)
                elif isinstance(item, tuple) and len(item) == 2:
                    # Formato tupla antiguo (user_msg, assistant_msg)
                    user_msg, assistant_msg = item
                    if user_msg:
                        chat_history.append({"role": "user", "content": user_msg})
                    if assistant_msg:
                        chat_history.append({"role": "assistant", "content": assistant_msg})
                elif isinstance(item, list) and len(item) == 2:
                    # Formato lista [user_msg, assistant_msg]
                    user_msg, assistant_msg = item
                    if user_msg:
                        chat_history.append({"role": "user", "content": user_msg})
                    if assistant_msg:
                        chat_history.append({"role": "assistant", "content": assistant_msg})
        
        # 3. Agregar mensaje del usuario (formato Gradio 6)
        chat_history.append({"role": "user", "content": message})
        
        yield chat_history, "", session_id
        
        # 4. Mostrar indicador de "escribiendo"
        chat_history.append({"role": "assistant", "content": "💬 Escribiendo..."})
        yield chat_history, "", session_id
        
        # 5. Procesar con el assistant
        assistant_response = await self.assistant.process_message(user_id, message, session_id=session_id)
        
        # 6. Reemplazar indicador con respuesta real
        chat_history[-1] = {"role": "assistant", "content": assistant_response["response"]}
        
        print("\n", 30*" - = - ")
        print("Assistant response:", assistant_response["response"])
        print(" ", 30*" - = - ", "\n")

        print ("\n", 50*"=")
        print (f"Session: {session_id}")
        print ("="*50)

        yield chat_history, "", session_id
    
    
    def create_interface(self):
        """
        Create Gradio interface con:
        - Sin scroll en ventana principal
        - Scroll automático en chat
        - Botones FQ debajo del input
        - Animación de typing
        """
        with gr.Blocks(
            title="Sabor Casero - Luz Stella",
            elem_id="main-container",  # Para aplicar estilos
        ) as demo:
            
            # Header fijo (sin scroll)
            gr.Markdown("# 🥘 Sabor Casero - Luz Stella")
            gr.Markdown("Tu asistente virtual para pedidos e información del restaurante")
            
            # Estado de la sesión (oculto)
            session_state = gr.State(None)
            
            # Chat interface con autoscroll (Gradio 6.x)
            chatbot = gr.Chatbot(
                height=500,
                autoscroll=True,  # Scroll automático al final
                layout="bubble",  # Estilo de burbuja
                avatar_images=(
                    "https://api.dicebear.com/7.x/avataaars/svg?seed=user",
                    "https://api.dicebear.com/7.x/avataaars/svg?seed=chef"
                ),
                buttons=["copy", "copy_all"],  # Botones de copiar
            )
            
            # Input area
            with gr.Row():
                msg = gr.Textbox(
                    label="",
                    placeholder="Escribe tu pregunta o pedido aquí...",
                    scale=4,
                    container=False
                )
                submit_btn = gr.Button("📤 Enviar", variant="primary", scale=1)
            
            # Botones de Preguntas Frecuentes (debajo del input)
            gr.Markdown("### 💬 Preguntas frequentes")
            with gr.Row():
                btn_hola = gr.Button("👋 Hola", variant="secondary")
                btn_buenos = gr.Button("🌅 Buenos días")
                btn_especiales = gr.Button("⭐ Especiales del día")
            
            with gr.Row():
                btn_pago = gr.Button("💳 Métodos de pago")
                btn_deliver = gr.Button("🚚 Delivery")
                btn_horario = gr.Button("🕐 Horario")
            
            # Clear button
            with gr.Row():
                clear_btn = gr.Button("🗑️ Limpiar conversación", variant="secondary")
            
            # Event handlers para botones FQ
            def set_message(text):
                return text
            
            btn_hola.click(lambda: "Hola", None, msg)
            btn_buenos.click(lambda: "Buenos días", None, msg)
            btn_especiales.click(lambda: "Cuáles son los especiales del día?", None, msg)
            btn_pago.click(lambda: "Qué métodos de pago tienen?", None, msg)
            btn_deliver.click(lambda: "Hacen delivery a mi zona?", None, msg)
            btn_horario.click(lambda: "A qué hora abren?", None, msg)
            
            # Click en botón FQ → enviar automáticamente
            for btn in [btn_hola, btn_buenos, btn_especiales, btn_pago, btn_deliver, btn_horario]:
                btn.click(
                    set_message,
                    [msg],
                    msg
                ).then(
                    self.chat_interface,
                    [msg, chatbot, session_state],
                    [chatbot, msg, session_state]
                )
            
            # Event handlers
            def clear_chat():
                return [], ""
            
            # Handle submissions con indicador de typing
            submit_event = msg.submit(
                self.chat_interface,
                [msg, chatbot, session_state],
                [chatbot, msg, session_state]
            ).then(lambda: "", None, msg)
            
            submit_btn.click(
                self.chat_interface,
                [msg, chatbot, session_state],
                [chatbot, msg, session_state]
            ).then(lambda: "", None, msg)
            
            clear_btn.click(clear_chat, None, [chatbot, msg])
        
        return demo
    
    def _handle_message(self, message: str, history: list, session_id: Optional[str]):
        """
        Procesa mensaje con manejo automático de sesión
        """
        import time
        import uuid
        
        # 1. CREAR SESIÓN SI NO EXISTE (primer mensaje)
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            print(f"🆕 Nueva sesión creada: {session_id}")
            self.sessions[session_id] = {"created_at": time.time()}
        
        # 2. Registrar actividad
        self.sessions[session_id]["last_activity"] = time.time()
        
        # 3. PROCESAR CON EL ASISTENTE (pasando session_id)
        try:
            # ¡El assistant recibe el session_id!
            response = self.assistant.process_message(
                session_id=session_id,  # ← AHORA TIENE SESSION_ID
                message=message
            )
            
            # 4. Actualizar historial
            history = history or []
            history.append((message, response))
            
            return history, "", session_id  # ← Retorna session_id para próximo mensaje
            
        except Exception as e:
            error_msg = f"Lo siento, ocurrió un error: {str(e)}"
            history.append((message, error_msg))
            return history, "", session_id


def main():
    """Launch the Gradio app"""
    app = GradioAssistantApp()
    demo = app.create_interface()
    
    # Launch with production settings
    demo.launch(theme=gr.themes.Soft())
    # demo.queue(concurrency_count=3, max_size=20).launch(
    #     server_name="0.0.0.0",
    #     server_port=7860,
    #     share=False,
    #     show_error=True
    # )

if __name__ == "__main__":
    main()