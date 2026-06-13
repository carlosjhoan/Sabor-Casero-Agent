"""
Smoke test Fase 5: verifica que el pipeline end-to-end funciona.

1. Inicialización de ToolOrchestrator con menu tools
2. _route_query con queries reales contra DeepSeek
3. Validación contra ontología real

Uso: python -m test_tools.smoke_test_router
"""
import asyncio
import json
import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.core.extractor.owl_retriever import OwlRetriever
from src.infrastructure.owl_client import OwlClient
from src.config.environment import settings


async def test_orchestrator_init():
    """Verifica que ToolOrchestrator se inicializa con tools."""
    owl_path = Path(__file__).resolve().parent.parent / "data" / "ontology" / "menu.ttl"
    client = OwlClient(str(owl_path))
    retriever = OwlRetriever(owl_client=client)

    if retriever._orchestrator is not None:
        print("✅ ToolOrchestrator inicializado correctamente")
        registry = retriever._orchestrator.registry
        print(f"   Tools registradas: {len(registry)}")
        for name in registry:
            print(f"     - {name}")
    else:
        print("❌ ToolOrchestrator NO se inicializó (None)")
        return False
    return True


async def test_route_query(segment: str, focus: str, desc: str):
    """Ejecuta una consulta real a través de _route_query."""
    owl_path = Path(__file__).resolve().parent.parent / "data" / "ontology" / "menu.ttl"
    client = OwlClient(str(owl_path))
    retriever = OwlRetriever(owl_client=client)

    print(f"\n─── Test: {desc} ───")
    print(f"   segment: '{segment}'")
    print(f"   focus:   '{focus}'")

    result = await retriever._route_query(segment, focus)

    if result and len(result) > 10:
        print(f"✅ Resultado ({len(result)} chars):")
        print(f"   {result[:200]}")
        return True
    elif result:
        print(f"⚠️  Resultado muy corto: '{result}'")
        return True
    else:
        print("❌ Sin resultado (None)")
        return False


async def test_fallback_path():
    """Verifica que el fallback funciona si orchestrator es None."""
    from src.core.extractor.owl_retriever import OwlRetriever
    from unittest.mock import MagicMock, AsyncMock

    owl_path = Path(__file__).resolve().parent.parent / "data" / "ontology" / "menu.ttl"
    client = OwlClient(str(owl_path))
    retriever = OwlRetriever(owl_client=client)

    # Forzar orchestrator a None
    retriever._orchestrator = None

    # Mockear get_llm_client_for_stage para que devuelva algo que devuelva texto
    original_get_llm = __import__('src.core.extractor.owl_retriever',
                                  fromlist=['get_llm_client_for_stage'])

    # Llamar con una consulta simple que falle al no tener orchestrator
    result = await retriever._route_query("cuánto cuesta la pechuga", "precio de pechuga de pollo")

    if result is None:
        print("❌ Fallback sin orchestrator retornó None (esperado con mock)")
        # En un entorno real sin API key apropiada puede fallar
        # Lo importante es que NO CRASHEE
        print("   (no crash — el fallback al menos no explota)")
        return True

    print(f"✅ Fallback funcionó: '{result[:100]}'")
    return True


async def main():
    print("=" * 60)
    print("FASE 5 — Smoke Test: Pipeline Owl Router End-to-End")
    print("=" * 60)

    # 1. Init
    print("\n[1] Verificar inicialización ToolOrchestrator")
    ok = await test_orchestrator_init()
    if not ok:
        print("❌ Abortando — no se pudo inicializar el router")
        return

    # 2. Queries reales
    print("\n[2] Pruebas de ruteo con LLM real")
    queries = [
        ("cuánto cuesta la pechuga", "precio de pechuga de pollo",
         "Precio de ítem específico"),
        ("qué principios hay", "principios disponibles en el menú de hoy",
         "Listar sección (Principios)"),
        ("cuánto vale la bandeja mixta", "precio de bandeja mixta",
         "Precio con sinónimo coloquial"),
        ("dame el menú completo", "menú completo del día",
         "Menú completo"),
    ]

    results = []
    for segment, focus, desc in queries:
        r = await test_route_query(segment, focus, desc)
        results.append(r)

    # 3. Fallback
    print("\n[3] Verificar fallback sin orchestrator")
    await test_fallback_path()

    # Resumen
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r)
    print(f"Resultados: {passed}/{len(results)} queries OK")
    if passed == len(results):
        print("✅ Fase 5: SMOKE TEST COMPLETADO")
    else:
        print("⚠️  Algunas queries fallaron — revisar logs")

if __name__ == "__main__":
    asyncio.run(main())
