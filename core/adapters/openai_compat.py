"""Adaptador para un servidor compatible con la API de chat de OpenAI que corre DENTRO del entorno
(p. ej. vLLM sirviendo un modelo open-weight y sus adaptadores LoRA). No usa proveedores externos ni
API keys comerciales: la URL apunta a localhost en el job de HF. Salida estructurada por JSON Schema."""
import copy, json, sys, time, urllib.error, urllib.request
from .base import ModelResponse

def _grammar_safe(schema, drop_patterns: bool = False):
    """Adapta el schema al motor de gramática de vLLM sin perder estructura:
    - quita minLength/maxLength donde hay pattern (el motor no compone regex con longitud: "Unable to determine if regex is empty");
    - con drop_patterns=True (reintento ante 400) quita además pattern y format.
    El contrato completo lo sigue validando el puerto (jsonschema) después de la generación."""
    def walk(n):
        if isinstance(n, dict):
            out = {}
            for k, v in n.items():
                if k in ("minLength", "maxLength") and "pattern" in n:
                    continue
                if drop_patterns and k in ("pattern", "format"):
                    continue
                out[k] = walk(v)
            return out
        if isinstance(n, list):
            return [walk(v) for v in n]
        return n
    return walk(copy.deepcopy(schema))


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

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=self.timeout))

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        chat = [{"role": m["role"], "content": m["content"]} for m in messages if not m.get("name")]
        body = {"model": self.model, "messages": chat, "max_tokens": self.max_tokens, "temperature": self.temperature}
        if self.chat_kwargs:
            body["chat_template_kwargs"] = self.chat_kwargs
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.get("title", "salida"), "schema": _grammar_safe(schema)}}
        t0 = time.time()
        try:
            r = self._post(body)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:500]
            print(f"[openai_compat] HTTP {e.code}: {detail}", file=sys.stderr, flush=True)
            if e.code == 400 and "context length" in detail.lower() and self.max_tokens > 4096:
                body["max_tokens"] = 4096       # D-E5: entrada larga; se cede salida antes que fallar (queda en el log)
                r = self._post(body)
                u = r.get("usage", {})
                return ModelResponse(text=r["choices"][0]["message"]["content"], model_id=self.model, provider=self.name,
                                     tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                                     latency_ms=int((time.time() - t0) * 1000))
            if e.code != 400 or not schema:
                raise
            body["response_format"]["json_schema"]["schema"] = _grammar_safe(schema, drop_patterns=True)   # reintento sin regex
            r = self._post(body)
        u = r.get("usage", {})
        return ModelResponse(text=r["choices"][0]["message"]["content"], model_id=self.model, provider=self.name,
                             tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                             latency_ms=int((time.time() - t0) * 1000))
