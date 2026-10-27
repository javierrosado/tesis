"""Carga agentes (agent.yaml + prompt.md + schemas), proveedores y resuelve $ref de los schemas
para que cualquier adaptador reciba un JSON Schema autocontenido."""
import json, os
from pathlib import Path
import yaml


def _resolve_refs(schema: dict, base: Path) -> dict:
    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node and not node["$ref"].startswith("#"):
                target = (base / node["$ref"]).resolve()
                sub = json.loads(target.read_text(encoding="utf-8"))
                sub = _resolve_refs(sub, target.parent)
                sub.pop("$schema", None); sub.pop("$id", None)
                return sub
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


class Agent:
    def __init__(self, folder: Path):
        self.folder = folder
        self.spec = yaml.safe_load((folder / "agent.yaml").read_text(encoding="utf-8"))
        self.name = self.spec["name"]
        self.prompt = (folder / self.spec["prompt"]).read_text(encoding="utf-8")
        out = folder / self.spec["output_schema"]
        self.output_schema = _resolve_refs(json.loads(out.read_text(encoding="utf-8")), out.parent)
        self.input_schema = None
        if self.spec.get("input_schema"):
            inp = (folder / self.spec["input_schema"]).resolve()
            self.input_schema = _resolve_refs(json.loads(inp.read_text(encoding="utf-8")), inp.parent)
        self.requires = self.spec.get("requires", {})
        self.verification = self.spec.get("verification", [])
        self.gate = self.spec.get("gate")

    def check_capabilities(self, caps: dict):
        missing = []
        if self.requires.get("json_mode") and not caps.get("json_mode"):
            missing.append("json_mode")
        if caps.get("context_tokens", 0) < self.requires.get("context_tokens", 0):
            missing.append(f"context_tokens>={self.requires['context_tokens']}")
        for t in self.requires.get("tools", []):
            if t not in caps.get("tools", []):
                missing.append(f"tool:{t}")
        return missing


class Registry:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.agents = {a.name: a for a in (Agent(p.parent) for p in sorted(self.root.glob("agents/*/agent.yaml")))}
        self.providers_cfg = yaml.safe_load((self.root / "config/providers.yaml").read_text(encoding="utf-8"))
        self.dag = yaml.safe_load((self.root / "config/dag.yaml").read_text(encoding="utf-8"))
        self.gates = yaml.safe_load((self.root / "config/gates.yaml").read_text(encoding="utf-8"))
        self._adapters = {}

    def provider_for(self, agent_name: str) -> tuple[str, dict]:
        ov = (self.providers_cfg.get("overrides") or {}).get(agent_name, {})
        name = ov.get("provider") or os.environ.get("PIPELINE_PROVIDER") or self.providers_cfg["default"]
        cfg = dict(self.providers_cfg["providers"][name])
        if ov.get("adapter_weights"):
            cfg["adapter_weights"] = ov["adapter_weights"]
            name = f"{name}+lora"
        return name, cfg

    def adapter_for(self, agent_name: str):
        from core.adapters import build_adapter
        name, cfg = self.provider_for(agent_name)
        if name not in self._adapters:
            self._adapters[name] = build_adapter(name, cfg, self.root)
        return self._adapters[name]
