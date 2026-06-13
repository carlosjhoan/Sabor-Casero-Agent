"""
Main entry point for the assistant
"""
# import asyncio
import sys
import argparse
from pathlib import Path
import os

# Add the parent directory to sys.path
sys.path.append(str(Path(__file__).parent.parent))

def _run_gradio_impl():
    """Run Gradio interface (implementation)"""
    print("🌐 Launching Gradio interface...")
    from src.ui.gradio_app import GradioAssistantApp
    from src.core.assistant import SaborCaseroAssistant
    from src.core.extractor.retriever_factory import RetrieverFactory
    import gradio as gr
    # from src.utils.config import load_config
    from src.config.environment import settings
    from src.core.order.infrastructure.json_oder_repository import JsonOrderRepository
    from src.core.order.infrastructure.json_session_repository import JsonSessionRepository
    from src.core.order.application.processor import OrderProcessor
    from src.core.order.application.orchestrator import OrderOrchestrator
    from src.core.conversation_log.application.conversation_logger import ConversationLogger
    from src.core.conversation_log.infrastructure.conversation_json_repository import JsonConversationLogRepository
    

    # config = load_config()

    way = settings.retriever_type
    extractor = RetrieverFactory.get_retriever(way=way)

    session_repository = JsonSessionRepository(file_path=settings.sessions_path)
    order_repository = JsonOrderRepository(storage_dir=settings.orders_path)
    order_orhestrator = OrderOrchestrator(order_repository=order_repository, session_repository=session_repository)
    order_processor = OrderProcessor(order_repository=order_repository, session_repository=session_repository)
    
    log_repository = JsonConversationLogRepository(base_path=settings.conversation_logs_path)
    logger_conversation = ConversationLogger(repository=log_repository)

    assistant = SaborCaseroAssistant(
        extractor=extractor,
        order_orchestrator=order_orhestrator,
        logger_conversation=logger_conversation
    )

    app = GradioAssistantApp(assistant=assistant)
    demo = app.create_interface()

    # # port = config.get("gradio_port", 7860)
    print("🌐 Launching on http://localhost:7860")
    
    demo.queue().launch(
        theme=gr.themes.Soft(),
        server_name="0.0.0.0",
        server_port=7860,
        share=True,
        show_error=True,
        debug=True
    )


def _run_gradio_with_reload():
    """Run Gradio with auto-reload on file changes"""
    try:
        from watchfiles import run_process, DefaultFilter
        import sys
        print("🔄 Auto-reload enabled. Watching for .py file changes...")
        print("   Press Ctrl+C to stop.\n")
        
        watch_filter = DefaultFilter(
            ignore_dirs={
                '.venv', '__pycache__', '.git', '.idea', 'venv',
                '.hg', '.svn', '.pytest_cache', '.mypy_cache',
                '.tox', '.hypothesis', 'node_modules', 'data', 'logs'
            }
        )
        
        run_process('.', target=_run_gradio_impl, watch_filter=watch_filter)
    except ImportError:
        print("⚠️ watchfiles not installed.")
        print("   Install with: pip install watchfiles")
        print("   Falling back to normal mode...\n")
        _run_gradio_impl()


def run_gradio(reload=False):
    """Run Gradio interface (optionally with auto-reload)"""
    if reload:
        _run_gradio_with_reload()
    else:
        _run_gradio_impl()

    

# def run_api():
#     """Run FastAPI server"""
#     import uvicorn
#     from src.api.app import app
#     uvicorn.run(app, host="0.0.0.0", port=8000)

def run_cli():
    """Run command-line interface with a persistent event loop.

    Uses a single event loop for the entire session so that fire-and-forget
    background tasks (summarize, evaluation) are NOT cancelled between messages.
    """
    import asyncio
    from src.core.assistant import SaborCaseroAssistant
    from src.core.extractor.retriever_factory import RetrieverFactory
    from src.core.order.infrastructure.json_oder_repository import JsonOrderRepository
    from src.core.order.infrastructure.json_session_repository import JsonSessionRepository
    from src.core.order.application.orchestrator import OrderOrchestrator
    from src.config.environment import settings

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Use RetrieverFactory so CLI respects RETRIEVER_WAY in .env
    way = settings.retriever_type
    extractor = RetrieverFactory.get_retriever(way=way)
    order_repository = JsonOrderRepository(storage_dir=settings.orders_path)
    session_repository = JsonSessionRepository(file_path=settings.sessions_path)
    order_orchestrator = OrderOrchestrator(
        order_repository=order_repository,
        session_repository=session_repository,
    )
    assistant = SaborCaseroAssistant(
        extractor=extractor,
        order_orchestrator=order_orchestrator,
    )

    print("🥘 Sabor Casero Assistant - Modo CLI")
    print("Escribe 'salir' para terminar\n")

    user_id = "cli_user"
    session_id = f"cli_{user_id}_{int(__import__('time').time())}"

    try:
        while True:
            message = input("\nTú: ").strip()

            if message.lower() in ('salir', 'exit', 'quit'):
                break

            if not message:
                continue

            result = loop.run_until_complete(
                assistant.process_message(user_id, message, session_id=session_id)
            )

    except KeyboardInterrupt:
        print("\n\n¡Hasta luego! 👋")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        # Give background tasks (summarize, evaluation) time to finish
        if loop.is_running():
            loop.run_until_complete(asyncio.sleep(1.0))
        loop.run_until_complete(asyncio.sleep(0.5))
        loop.close()
        asyncio.set_event_loop(None)

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Sabor Casero Assistant")
    parser.add_argument(
        "--mode",
        choices=["gradio", "api", "cli"],
        default="gradio",
        help="Interface mode"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file (YAML). Default: looks for configs/development.yaml"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Auto-reload on file changes (development mode)"
    )
    
    args = parser.parse_args()

    from src.utils.config import load_config


    if not args.config:
        default_locations = [
            "configs/development.yaml",
            "config.yaml",
            "config.yml"
        ]
        
        for location in default_locations:
            if os.path.exists(location):
                args.config = location
                print(f"📁 Using config file: {location}")
                break
    
    config = load_config(args.config)

    # Check API key
    if not config.get("deepseek_api_key"):
        print("❌ ERROR: DeepSeek API key not found!")
        print("Set DEEPSEEK_API_KEY environment variable or add to config file")
        print("Example: export DEEPSEEK_API_KEY='sk-...'")
        sys.exit(1)
    
    # Run in selected mode
    if args.mode == "gradio":
        run_gradio(reload=args.reload)
    elif args.mode == "cli":
        run_cli()
    # elif args.mode == "test":
    #     run_test(config)

if __name__ == "__main__":
    main()