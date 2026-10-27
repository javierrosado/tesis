"""Adaptadores de proveedor. Cada uno implementa ModelAdapter.complete(); ninguno conoce a los agentes."""
from .base import ModelAdapter, ModelResponse


def build_adapter(name: str, cfg: dict, repo_root) -> ModelAdapter:
    kind = cfg["adapter"]
    if kind == "mock":
        from .mock import MockAdapter
        return MockAdapter(repo_root / cfg.get("fixtures", "tests/fixtures"), name)
    if kind == "anthropic":
        from .anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(cfg)
    if kind == "hf_local":
        from .hf_local import HFLocalAdapter
        return HFLocalAdapter(cfg)
    if kind == "hf_endpoint":
        from .hf_endpoint import HFEndpointAdapter
        return HFEndpointAdapter(cfg)
    if kind == "ollama":
        from .ollama_adapter import OllamaAdapter
        return OllamaAdapter(cfg)
    raise ValueError(f"adaptador desconocido: {kind}")
