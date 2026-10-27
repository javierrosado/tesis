"""Adaptador para un Inference Endpoint dedicado de Hugging Face (TGI, API compatible con OpenAI chat).
Usa `response_format` con el JSON Schema cuando el servidor lo soporta (TGI ≥ 2.x)."""
import json, os, time, urllib.request
from .base import ModelResponse


class HFEndpointAdapter:
    name = "hf_endpoint"

    def __init__(self, cfg: dict):
        self.url = os.environ.get(cfg.get("url_env", "HF_ENDPOINT_URL"))
        self.token = os.environ.get(cfg.get("token_env", "HF_TOKEN"))
        if not self.url:
            raise RuntimeError("falta HF_ENDPOINT_URL")
        self.model = cfg.get("model", "tgi")
        self.max_tokens = cfg.get("max_new_tokens", 2048)
        self.temperature = cfg.get("temperature", 0.2)

    def capabilities(self) -> dict:
        return {"json_mode": True, "context_tokens": 32_000, "language": "es", "tools": ["rag.search"]}

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        body = {"model": self.model, "messages": [{"role": m["role"], "content": m["content"]} for m in messages if not m.get("name")],
                "max_tokens": self.max_tokens, "temperature": self.temperature}
        if schema:
            body["response_format"] = {"type": "json_schema", "value": schema}
        req = urllib.request.Request(self.url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=600) as r:
            data = json.load(r)
        usage = data.get("usage", {})
        return ModelResponse(text=data["choices"][0]["message"]["content"], model_id=data.get("model", self.model), provider=self.name,
                             tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
                             latency_ms=int((time.time() - t0) * 1000))
