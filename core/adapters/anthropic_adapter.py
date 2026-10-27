"""Adaptador Anthropic. SOLO para pruebas internas de la Fase 1; ningún resultado producido con él
se reporta en la tesis. Traduce el JSON Schema a una herramienta forzada para obtener salida estructurada."""
import os, time
from .base import ModelResponse


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, cfg: dict):
        import anthropic  # pip install anthropic
        key = os.environ.get(cfg.get("api_key_env", "ANTHROPIC_API_KEY"))
        if not key:
            raise RuntimeError("falta ANTHROPIC_API_KEY (adaptador de desarrollo)")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = cfg["model"]
        self.max_tokens = cfg.get("max_tokens", 4096)
        self.temperature = cfg.get("temperature", 0.2)

    def capabilities(self) -> dict:
        return {"json_mode": True, "context_tokens": 200_000, "language": "es", "tools": ["rag.search"]}

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and not m.get("name"))
        convo = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        kwargs = dict(model=self.model, max_tokens=self.max_tokens, temperature=self.temperature, system=system, messages=convo)
        if schema:
            kwargs["tools"] = [{"name": "emit", "description": "Devuelve el artefacto estructurado.", "input_schema": _inline(schema)}]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit"}
        t0 = time.time()
        r = self.client.messages.create(**kwargs)
        import json
        text = next((json.dumps(b.input, ensure_ascii=False) for b in r.content if b.type == "tool_use"), "")
        if not text:
            text = "".join(b.text for b in r.content if b.type == "text")
        return ModelResponse(text=text, model_id=r.model, provider=self.name,
                             tokens_in=r.usage.input_tokens, tokens_out=r.usage.output_tokens,
                             latency_ms=int((time.time() - t0) * 1000))


def _inline(schema: dict) -> dict:
    """Las API de herramientas no resuelven $ref a archivos; el registro ya entrega el schema con refs resueltas."""
    s = dict(schema)
    s.pop("$schema", None); s.pop("$id", None)
    return s
