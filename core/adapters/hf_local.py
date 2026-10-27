"""Adaptador Hugging Face local: carga un modelo open-weight con transformers (int4 opcional) y,
si json_grammar=true, restringe la decodificación al JSON Schema con `outlines`.
Es el adaptador del piloto reportado en la tesis (Fase 2) y del agente con LoRA (Fase 3)."""
import json, time
from .base import ModelResponse


class HFLocalAdapter:
    name = "hf_local"

    def __init__(self, cfg: dict):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.model_id = cfg["model"]
        self.max_new_tokens = cfg.get("max_new_tokens", 2048)
        self.temperature = cfg.get("temperature", 0.2)
        self.json_grammar = cfg.get("json_grammar", True)
        kw = {"device_map": "auto"}
        if cfg.get("quantization") == "int4":
            from transformers import BitsAndBytesConfig
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
                                                           bnb_4bit_quant_type="nf4")
        self.tok = AutoTokenizer.from_pretrained(self.model_id)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_id, **kw)
        self.adapter_weights = cfg.get("adapter_weights")
        if self.adapter_weights:                      # Fase 3: adaptador LoRA del agente entrenado
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, self.adapter_weights)
        self._outlines = None

    def capabilities(self) -> dict:
        return {"json_mode": self.json_grammar, "context_tokens": 32_000, "language": "es", "tools": ["rag.search"]}

    def _generate_free(self, prompt: str) -> str:
        import torch
        ids = self.tok(prompt, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=self.max_new_tokens, do_sample=self.temperature > 0,
                                      temperature=max(self.temperature, 1e-5))
        return self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)

    def _generate_json(self, prompt: str, schema: dict) -> str:
        import outlines  # pip install outlines
        if self._outlines is None:
            self._outlines = outlines.models.Transformers(self.model, self.tok)
        gen = outlines.generate.json(self._outlines, json.dumps(schema))
        return json.dumps(gen(prompt, max_tokens=self.max_new_tokens), ensure_ascii=False)

    def complete(self, messages, schema=None, tools=None) -> ModelResponse:
        chat = [{"role": m["role"], "content": m["content"]} for m in messages if not m.get("name")]
        prompt = self.tok.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
        t0 = time.time()
        text = self._generate_json(prompt, schema) if (schema and self.json_grammar) else self._generate_free(prompt)
        model_id = self.model_id + (f"+{self.adapter_weights}" if self.adapter_weights else "")
        return ModelResponse(text=text, model_id=model_id, provider=self.name,
                             tokens_in=len(self.tok(prompt)["input_ids"]), tokens_out=len(self.tok(text)["input_ids"]),
                             latency_ms=int((time.time() - t0) * 1000))
