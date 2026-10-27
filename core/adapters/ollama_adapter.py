"""Adaptador Ollama (modelos open-weight en una máquina local). Usa `format` = JSON Schema (Ollama ≥ 0.5)."""
import json, time, urllib.request
from .base import ModelResponse


class OllamaAdapter:
    name = "ollama"

    def __init__(self, cfg: dict):
        self.url = cfg.get("url", "http://localhost:11434")
        self.model = cfg["model"]
        self.temperature = cfg.get("temperature", 0.2)

    def capabilities(self) -> dict:
        return {"json_mode": True, "context_tokens": 32_000, "language": "es", "tools": ["rag.search"]}

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        body = {"model": self.model, "stream": False, "options": {"temperature": self.temperature},
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages if not m.get("name")]}
        if schema:
            body["format"] = schema
        req = urllib.request.Request(self.url + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=600) as r:
            data = json.load(r)
        return ModelResponse(text=data["message"]["content"], model_id=self.model, provider=self.name,
                             tokens_in=data.get("prompt_eval_count", 0), tokens_out=data.get("eval_count", 0),
                             latency_ms=int((time.time() - t0) * 1000))
