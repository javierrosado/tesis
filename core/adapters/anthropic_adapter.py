"""Adaptador Anthropic. Usos: (1) pruebas internas de la Fase 1 (no se reportan); (2) v2: referencia de techo del
benchmark N3 (`claude_ref`, API de pago por uso, model_id fijado) y, solo en el escalón E4 con C1–C4 cumplidas,
code-review y security-compliance (declarado como desviación). Traduce el JSON Schema a una herramienta forzada."""
import os, time
from .base import ModelResponse

# USD por millón de tokens (entrada, salida), lista oficial de Anthropic al 25/11/2026; la API no devuelve el costo
PRECIOS = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, cfg: dict):
        import anthropic  # pip install anthropic
        key = os.environ.get(cfg.get("api_key_env", "ANTHROPIC_API_KEY"))
        if not key:
            raise RuntimeError("falta ANTHROPIC_API_KEY (adaptador de desarrollo)")
        ws = os.environ.get(cfg.get("workspace_env", "ANTHROPIC_WORKSPACE_ID"))   # claves no ligadas a un workspace
        self.client = anthropic.Anthropic(api_key=key, default_headers={"anthropic-workspace-id": ws} if ws else None)
        self.model = cfg["model"]
        self.max_tokens = cfg.get("max_tokens", 4096)
        self.temperature = cfg.get("temperature")      # None = no se envía (25/11: el SDK actual la rechaza con claude-opus-5-5)

    def capabilities(self) -> dict:
        return {"json_mode": True, "context_tokens": 200_000, "language": "es", "tools": ["rag.search"]}

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and not m.get("name"))
        convo = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        kwargs = dict(model=self.model, max_tokens=self.max_tokens, system=system, messages=convo)
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if schema:
            kwargs["tools"] = [{"name": "emit", "description": "Devuelve el artefacto estructurado.", "input_schema": _inline(schema)}]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit"}
        t0 = time.time()
        r = self.client.messages.create(**kwargs)
        import json
        text = next((json.dumps(b.input, ensure_ascii=False) for b in r.content if b.type == "tool_use"), "")
        if not text:
            text = "".join(b.text for b in r.content if b.type == "text")
        pin, pout = PRECIOS.get(self.model, (None, None))
        costo = round((r.usage.input_tokens * pin + r.usage.output_tokens * pout) / 1e6, 6) if pin is not None else None
        return ModelResponse(text=text, model_id=r.model, provider=self.name,
                             tokens_in=r.usage.input_tokens, tokens_out=r.usage.output_tokens,
                             latency_ms=int((time.time() - t0) * 1000), meta={"costo_usd": costo})


def _inline(schema: dict) -> dict:
    """Las API de herramientas no resuelven $ref a archivos; el registro ya entrega el schema con refs resueltas."""
    s = dict(schema)
    s.pop("$schema", None); s.pop("$id", None)
    return s
