"""Puerto de modelo: única puerta de los agentes hacia cualquier proveedor.
Responsabilidades: verificar capacidades, llamar al adaptador, validar el contrato (JSON Schema),
reintentar con retroalimentación y registrar telemetría. No contiene lógica de negocio de ningún agente."""
import json, time
import jsonschema
from .adapters.base import ModelAdapter
from .telemetry import Telemetry


class ContractError(RuntimeError):
    pass


class ModelPort:
    def __init__(self, adapter: ModelAdapter, telemetry: Telemetry, max_retries: int = 2):
        self.adapter, self.telemetry, self.max_retries = adapter, telemetry, max_retries

    def run(self, agent, req_id: str, messages: list[dict], tools=None, variant: str = "") -> tuple[dict, dict]:
        missing = agent.check_capabilities(self.adapter.capabilities())
        if missing:
            raise ContractError(f"{agent.name}: el proveedor {self.adapter.name} no satisface {missing}")
        schema = agent.output_schema
        last_err, totals = None, {"tokens_in": 0, "tokens_out": 0, "latency_ms": 0, "attempts": 0}
        for attempt in range(self.max_retries + 1):
            route = {"role": "system", "name": "__route", "content": "", "agent": agent.name, "req_id": req_id, "attempt": attempt, "variant": variant}
            try:
                r = self.adapter.complete([route] + messages, schema, tools)
            except json.JSONDecodeError as e:          # p. ej. salida truncada por max_new_tokens
                last_err = f"salida truncada o JSON inválido: {e}"[:300]
                self.telemetry.emit(event="contract_rejected", agent=agent.name, req_id=req_id, attempt=attempt,
                                    provider=self.adapter.name, model_id=None, error=last_err)
                continue
            totals["tokens_in"] += r.tokens_in; totals["tokens_out"] += r.tokens_out
            totals["latency_ms"] += r.latency_ms; totals["attempts"] = attempt + 1
            try:
                out = json.loads(_strip_fences(r.text))
                jsonschema.validate(out, schema)
                self.telemetry.emit(event="agent_completed", agent=agent.name, req_id=req_id, attempt=attempt,
                                    provider=r.provider, model_id=r.model_id, **{k: totals[k] for k in ("tokens_in", "tokens_out", "latency_ms")})
                return out, {**totals, "provider": r.provider, "model_id": r.model_id}
            except (json.JSONDecodeError, jsonschema.ValidationError) as e:
                last_err = _short(e)
                extra = {}
                if isinstance(e, json.JSONDecodeError):      # D-E6: fragmento de la salida alrededor del error, para diagnosticar
                    extra = {"contexto": e.doc[max(0, e.pos - 300): e.pos + 100], "largo_salida": len(e.doc)}
                self.telemetry.emit(event="contract_rejected", agent=agent.name, req_id=req_id, attempt=attempt,
                                    provider=r.provider, model_id=r.model_id, error=last_err, **extra)
                messages = messages + [{"role": "assistant", "content": r.text[:4000]},
                                       {"role": "user", "content": f"La salida no cumple el contrato: {last_err}. "
                                                                   f"Corrige y devuelve solo el JSON completo y válido."}]
        raise ContractError(f"{agent.name}/{req_id}: contrato no satisfecho tras {self.max_retries + 1} intentos ({last_err})")


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _short(e) -> str:
    if isinstance(e, jsonschema.ValidationError):
        path = "/".join(str(p) for p in e.absolute_path) or "<raíz>"
        return f"{path}: {e.message}"[:300]
    return str(e)[:300]
