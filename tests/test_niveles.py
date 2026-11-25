"""v2 · Router por nivel de razonamiento (model_tier / reasoning_effort) y proveedores de HF Inference Providers."""
import io, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry  # noqa: E402

NIVEL = {"api-designer-agent": "N1", "test-case-generator-agent": "N1", "cicd-pipeline-agent": "N1",
         "ux-ui-copilot-agent": "N2", "qa-automation-agent": "N2", "release-manager-agent": "N2", "product-analyst-agent": "N2",
         "domain-modeling-agent": "N2", "data-model-agent": "N3", "backend-developer-agent": "N3", "solution-architect-agent": "N3",
         "code-review-agent": "N3", "security-compliance-agent": "N3"}


def _reg(monkeypatch, activo=True, asignacion=None, base="vllm_local"):
    monkeypatch.setenv("PIPELINE_PROVIDER", base)
    monkeypatch.delenv("NIVELES", raising=False)
    r = Registry(ROOT)
    r.niveles["activo"] = activo
    r.niveles["asignacion"] = asignacion or {}
    return r


def test_cada_agente_declara_su_nivel():
    r = Registry(ROOT)
    for a, n in NIVEL.items():
        assert r.agents[a].spec["model_tier"] == n, a
        assert r.agents[a].spec["reasoning_effort"] in ("bajo", "medio", "alto", "maximo"), a
    assert r.agents["security-compliance-agent"].spec["reasoning_effort"] == "maximo"
    assert r.agents["governance-agent"].spec["model_tier"] is None


def test_router_inactivo_no_cambia_la_v1(monkeypatch):
    v1 = _reg(monkeypatch, activo=False)
    assert v1.provider_for("solution-architect-agent")[0] == "vllm_local:solution-architect-agent"
    assert v1.provider_for("backend-developer-agent")[0] == "vllm_teacher"
    assert v1.correccion_provider("domain-modeling-agent")[0] == "vllm_teacher"


def test_router_por_nivel_y_asignacion(monkeypatch):
    r = _reg(monkeypatch, asignacion={"solution-architect-agent": "hf_glm53", "security-compliance-agent": "hf_dsv4pro"})
    n, cfg = r.provider_for("solution-architect-agent")
    assert n == "hf_glm53@alto" and cfg["reasoning_effort"] == "high" and cfg["model"].startswith("zai-org/GLM-5.3:")
    n, cfg = r.provider_for("security-compliance-agent")
    assert n == "hf_dsv4pro@maximo" and cfg["max_new_tokens"] == 32768
    assert r.provider_for("data-model-agent")[0] == "vllm_teacher"                       # N3 sin asignación: E0 del nivel
    assert r.provider_for("api-designer-agent")[0] == "vllm_local:api-designer-agent"    # N1 conserva su LoRA
    assert r.correccion_provider("solution-architect-agent") is None                      # corrige con su propio modelo
    assert r.modelos_hf() == ["deepseek-ai/DeepSeek-V4-Pro:deepinfra", "zai-org/GLM-5.3:together"]


def test_router_no_actua_en_prueba_offline(monkeypatch):
    r = _reg(monkeypatch, asignacion={"solution-architect-agent": "hf_glm53"}, base="prueba_offline")
    assert r.provider_for("solution-architect-agent")[0] == "prueba_offline"


def test_adaptador_hf_providers_envia_token_y_esfuerzo(monkeypatch):
    from core.adapters.openai_compat import OpenAICompatAdapter
    monkeypatch.setenv("HF_TOKEN", "tok-prueba")
    enviados = []

    def urlopen(req, timeout=None):
        enviados.append((dict(req.header_items()), json.loads(req.data)))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {}}).encode())
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    r = Registry(ROOT)
    cfg = {**r.providers_cfg["providers"]["hf_qwen36"], "_registro": "hf_qwen36"}
    a = OpenAICompatAdapter(cfg)
    a.complete([{"role": "user", "content": "x"}], {"title": "s", "type": "object"})
    h, body = enviados[-1]
    assert h["Authorization"] == "Bearer tok-prueba" and "response_format" not in body          # sin salida estructurada
    assert body["messages"][-1]["content"].endswith("cumpla el esquema indicado.") and a.registro == "hf_qwen36"
    b = OpenAICompatAdapter({**r.providers_cfg["providers"]["hf_glm53"], "reasoning_effort": "high"})
    b.complete([{"role": "user", "content": "x"}], {"title": "s", "type": "object"})
    assert enviados[-1][1]["reasoning_effort"] == "high" and "response_format" in enviados[-1][1]
