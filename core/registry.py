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
        nv = self.root / "config/niveles.yaml"
        self.niveles = yaml.safe_load(nv.read_text(encoding="utf-8")) if nv.exists() else {"activo": False}
        if os.environ.get("NIVELES") in ("0", "1"):            # el job puede forzarlo (p. ej. benchmark o comparación v1/v2)
            self.niveles["activo"] = os.environ["NIVELES"] == "1"
        self._adapters = {}

    def modelos_hf(self) -> list[str]:
        """v2: modelos de HF Inference Providers que puede usar el router (para registrar repo@sha en el job)."""
        nv = self.niveles or {}
        usados = set((nv.get("niveles") or {}).values()) | set((nv.get("asignacion") or {}).values()) if nv.get("activo") else set()
        return sorted({self.providers_cfg["providers"][p]["model"] for p in usados
                       if "router.huggingface.co" in str(self.providers_cfg["providers"].get(p, {}).get("url", ""))})

    def ruta_nivel(self, agent_name: str, base: str) -> str | None:
        """v2: proveedor que elige el router por nivel (None = sin router: misma ruta que la v1)."""
        nv = self.niveles or {}
        if not nv.get("activo") or base != nv.get("para_proveedor", "vllm_local"):
            return None
        ag = self.agents.get(agent_name)
        tier = ag.spec.get("model_tier") if ag else None
        dest = (nv.get("asignacion") or {}).get(agent_name) or (nv.get("niveles") or {}).get(tier)
        return dest if dest and dest != base else None

    def provider_for(self, agent_name: str) -> tuple[str, dict]:
        ov = (self.providers_cfg.get("overrides") or {}).get(agent_name, {})
        name = ov.get("provider") or os.environ.get("PIPELINE_PROVIDER") or self.providers_cfg["default"]
        ruta = self.ruta_nivel(agent_name, name)
        if ruta:                                                # el router manda sobre los overrides de la v1
            cfg = dict(self.providers_cfg["providers"][ruta])
            ag = self.agents.get(agent_name)
            esfuerzo = ag.spec.get("reasoning_effort") if ag else None
            if esfuerzo and cfg.get("acepta_reasoning_effort"):
                cfg["reasoning_effort"] = (self.niveles.get("esfuerzo") or {}).get(esfuerzo, esfuerzo)
                if esfuerzo == "maximo" and cfg.get("max_new_tokens_maximo"):
                    cfg["max_new_tokens"] = cfg["max_new_tokens_maximo"]
                return f"{ruta}@{esfuerzo}", cfg
            return ruta, cfg
        if ov.get("switch_to") and name == ov.get("for_provider"):   # D-F4-1 C: el agente pasa a otro servidor del mismo job
            return ov["switch_to"], dict(self.providers_cfg["providers"][ov["switch_to"]])
        cfg = dict(self.providers_cfg["providers"][name])
        if ov.get("model") and name == ov.get("for_provider", name):   # p. ej. vllm_local: nombre del módulo LoRA servido por vLLM
            cfg["model"] = ov["model"]
            name = f"{name}:{ov['model']}"
        if ov.get("adapter_weights"):
            cfg["adapter_weights"] = ov["adapter_weights"]
            name = f"{name}+lora"
        return name, cfg

    def correccion_provider(self, agent_name: str) -> tuple[str, dict] | None:
        """D-E1: proveedor que atiende la corrección tras una devolución humana (None = el mismo del agente)."""
        c = self.providers_cfg.get("correccion_humana") or {}
        base = os.environ.get("PIPELINE_PROVIDER") or self.providers_cfg["default"]
        ruta = self.ruta_nivel(agent_name, base)
        if ruta and ruta != c.get("for_provider"):     # v2: un agente con modelo de nivel corrige con su propio modelo
            return None
        if c.get("switch_to") and base == c.get("for_provider"):
            return c["switch_to"], dict(self.providers_cfg["providers"][c["switch_to"]])
        return None

    def dictamen_provider(self) -> tuple[str, dict] | None:
        """G5: proveedor del dictamen IA de las puertas (None = solo governance determinista)."""
        c = self.providers_cfg.get("dictamen") or {}
        base = os.environ.get("PIPELINE_PROVIDER") or self.providers_cfg["default"]
        if c.get("switch_to") and base == c.get("for_provider"):
            return c["switch_to"], dict(self.providers_cfg["providers"][c["switch_to"]])
        return None

    def adapter_by_name(self, name: str, cfg: dict):
        from core.adapters import build_adapter
        if name not in self._adapters:
            self._adapters[name] = build_adapter(name, cfg, self.root)
        return self._adapters[name]

    def adapter_for(self, agent_name: str):
        from core.adapters import build_adapter
        name, cfg = self.provider_for(agent_name)
        if name not in self._adapters:
            self._adapters[name] = build_adapter(name, cfg, self.root)
        return self._adapters[name]
