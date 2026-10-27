"""Adaptador de pruebas: devuelve respuestas grabadas en tests/fixtures/<agente>/<req_id>.json.
Permite correr el DAG completo sin red ni GPU (CI, dry-run). Si falta un fixture, falla explícitamente."""
import json, time
from pathlib import Path
from .base import ModelResponse


class MockAdapter:
    name = "mock"

    def __init__(self, fixtures_dir: Path, provider_name: str = "mock"):
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
            raise RuntimeError("MockAdapter necesita el mensaje de ruta (agent/req_id)")
        agent, req_id, attempt, variant = tag["agent"], tag["req_id"], tag.get("attempt", 0), tag.get("variant", "")
        # orden de búsqueda: variante+intento → variante → intento → por defecto
        names = [f"{req_id}.{variant}.attempt{attempt}.json" if variant else None, f"{req_id}.{variant}.json" if variant else None,
                 f"{req_id}.attempt{attempt}.json", f"{req_id}.json"]
        candidates = [self.fixtures / agent / n for n in names if n]
        for c in candidates:
            if c.exists():
                text = c.read_text(encoding="utf-8")
                return ModelResponse(text=text, model_id="mock-fixture", provider=self.provider_name,
                                     tokens_in=sum(len(str(m.get("content", ""))) // 4 for m in messages),
                                     tokens_out=len(text) // 4, latency_ms=int(time.time() * 0) + 5)
        raise FileNotFoundError(f"sin fixture para {agent}/{req_id} (intento {attempt}); crea {candidates[-1]}")
