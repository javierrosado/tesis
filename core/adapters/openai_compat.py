"""Adaptador para un servidor compatible con la API de chat de OpenAI que corre DENTRO del entorno
(p. ej. vLLM sirviendo un modelo open-weight y sus adaptadores LoRA). No usa proveedores externos ni
API keys comerciales: la URL apunta a localhost en el job de HF. Salida estructurada por JSON Schema."""
import json, time, urllib.request
from .base import ModelResponse


class OpenAICompatAdapter:
    name = "openai_compat"

    def __init__(self, cfg: dict):
        self.url = cfg.get("url", "http://localhost:8000/v1").rstrip("/") + "/chat/completions"
        self.model = cfg["model"]
        self.max_tokens = cfg.get("max_new_tokens", 4096)
        self.temperature = cfg.get("temperature", 0.2)
        self.chat_kwargs = cfg.get("chat_template_kwargs", {})
        self.timeout = cfg.get("timeout_s", 900)
        self.context = cfg.get("context_tokens", 32000)

    def capabilities(self) -> dict:
        return {"json_mode": True, "context_tokens": self.context, "language": "es", "tools": ["rag.search"]}

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        chat = [{"role": m["role"], "content": m["content"]} for m in messages if not m.get("name")]
        body = {"model": self.model, "messages": chat, "max_tokens": self.max_tokens, "temperature": self.temperature}
        if self.chat_kwargs:
            body["chat_template_kwargs"] = self.chat_kwargs
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.get("title", "salida"), "schema": schema}}
        t0 = time.time()
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=self.timeout))
        u = r.get("usage", {})
        return ModelResponse(text=r["choices"][0]["message"]["content"], model_id=self.model, provider=self.name,
                             tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                             latency_ms=int((time.time() - t0) * 1000))
