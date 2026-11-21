"""Proveedor de prueba offline (antes llamado `mock`).

No llama a ningún modelo de lenguaje: devuelve artefactos de ejemplo predefinidos que están en
tests/fixtures/<agente>/<req_id>.json. Sirve solo para probar el software del pipeline (orquestador,
contratos, governance, reintentos y telemetría) sin red ni GPU, en CI y en ejecuciones de prueba locales.
Ningún resultado de la tesis se produce con este proveedor. Si falta un artefacto, falla explícitamente."""
import time
from pathlib import Path
from .base import ModelResponse


class PruebaOfflineAdapter:
    name = "prueba_offline"

    def __init__(self, fixtures_dir: Path, provider_name: str = "prueba_offline"):
        self.fixtures = Path(fixtures_dir)
        self.provider_name = provider_name
        self.calls = 0

    def capabilities(self) -> dict:
        return {"json_mode": True, "context_tokens": 1_000_000, "language": "es", "tools": ["rag.search"]}

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        self.calls += 1
        # el orquestador etiqueta cada llamada con agente y req_id en el primer mensaje de sistema
        tag = next((m for m in messages if m.get("role") == "system" and m.get("name") == "__route"), None)
        if tag is None:
            raise RuntimeError("PruebaOfflineAdapter necesita el mensaje de ruta (agent/req_id)")
        agent, req_id, attempt, variant = tag["agent"], tag["req_id"], tag.get("attempt", 0), tag.get("variant", "")
        # orden de búsqueda: variante+intento → variante → intento → por defecto
        names = [f"{req_id}.{variant}.attempt{attempt}.json" if variant else None, f"{req_id}.{variant}.json" if variant else None,
                 f"{req_id}.attempt{attempt}.json", f"{req_id}.json"]
        candidates = [self.fixtures / agent / n for n in names if n]
        for c in candidates:
            if c.exists():
                text = c.read_text(encoding="utf-8")
                return ModelResponse(text=text, model_id="artefacto-de-prueba", provider=self.provider_name,
                                     tokens_in=sum(len(str(m.get("content", ""))) // 4 for m in messages),
                                     tokens_out=len(text) // 4, latency_ms=5)
        raise FileNotFoundError(f"sin artefacto de prueba para {agent}/{req_id} (intento {attempt}); crea {candidates[-1]}")
