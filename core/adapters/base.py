from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ModelResponse:
    text: str
    model_id: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)


@runtime_checkable
class ModelAdapter(Protocol):
    """Contrato mínimo de un proveedor. `schema` es el JSON Schema de salida: el adaptador lo usa si
    el proveedor soporta salida estructurada; si no, lo ignora y el puerto valida y reintenta."""

    name: str

    def complete(self, messages: list[dict], schema: dict | None = None, tools: list | None = None) -> ModelResponse: ...

    def capabilities(self) -> dict: ...
