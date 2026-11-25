"""Adaptador para un servidor compatible con la API de chat de OpenAI.
- v1: vLLM DENTRO del job de HF (modelo open-weight y sus LoRA), URL en localhost, sin API keys.
- v2 (D-P5): HF Inference Providers (router.huggingface.co/v1) para modelos open-weight de frontera, con el HF_TOKEN de la
  cuenta y el proveedor fijado en el nombre del modelo ("repo:proveedor"). Acepta reasoning_effort y, si el proveedor no
  ofrece salida estructurada, deja la validación del contrato al puerto.
`registro` es el nombre del proveedor en config/providers.yaml (lo graba G2 en cada <artefacto>.input.r<n>.json)."""
import copy, os, json, sys, time, urllib.error, urllib.request
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
        self.registro = cfg.get("_registro", self.name)
        self.model = cfg["model"]
        self.max_tokens = cfg.get("max_new_tokens", 4096)
        self.temperature = cfg.get("temperature", 0.2)
        self.chat_kwargs = cfg.get("chat_template_kwargs", {})
        self.timeout = cfg.get("timeout_s", 900)
        self.context = cfg.get("context_tokens", 32000)
        self.api_key = os.environ.get(cfg["api_key_env"], "") if cfg.get("api_key_env") else ""     # v2: HF Inference Providers
        self.estructurada = cfg.get("salida_estructurada", True)
        self.reasoning_effort = cfg.get("reasoning_effort") if cfg.get("acepta_reasoning_effort") else None

    def capabilities(self) -> dict:
        return {"json_mode": True, "context_tokens": self.context, "language": "es", "tools": ["rag.search"]}

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers)
        return json.load(urllib.request.urlopen(req, timeout=self.timeout))

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        chat = [{"role": m["role"], "content": m["content"]} for m in messages if not m.get("name")]
        body = {"model": self.model, "messages": chat, "max_tokens": self.max_tokens, "temperature": self.temperature}
        if self.chat_kwargs:
            body["chat_template_kwargs"] = self.chat_kwargs
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if schema and not self.estructurada:       # el proveedor no acepta response_format: el contrato lo valida el puerto
            chat[-1] = {**chat[-1], "content": chat[-1]["content"] + "\n\nResponde solo con un objeto JSON que cumpla el esquema indicado."}
            schema = None
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
                                     latency_ms=int((time.time() - t0) * 1000), meta={"costo_usd": u.get("cost")})
            if e.code != 400 or not schema:
                raise
            body["response_format"]["json_schema"]["schema"] = _grammar_safe(schema, drop_patterns=True)   # reintento sin regex
            r = self._post(body)
        u = r.get("usage", {})
        return ModelResponse(text=r["choices"][0]["message"]["content"], model_id=self.model, provider=self.name,
                             tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                             latency_ms=int((time.time() - t0) * 1000), meta={"costo_usd": u.get("cost")})   # HF router informa el costo
