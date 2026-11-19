"""Criterios F5 de los 4 agentes entrenables nuevos: casos negativos que governance debe rechazar."""
import copy, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry   # noqa: E402
from core import governance, verify  # noqa: E402

REG = Registry(ROOT)
F = lambda a: json.loads((ROOT / f"tests/fixtures/{a}/SIM-P05-R001.json").read_text(encoding="utf-8"))
CTX = {"req_id": "SIM-P05-R001", "user_story_set": F("product-analyst-agent"), "domain_model": F("domain-modeling-agent"),
       "solution_architecture": F("solution-architect-agent"), "api_design": F("api-designer-agent"), "test_cases": F("test-case-generator-agent")}


def _rev(agent, out):
    return governance.review(REG.agents[agent], out, CTX, 0)


def test_fixtures_aprobadas():
    for a in ("solution-architect-agent", "api-designer-agent", "test-case-generator-agent", "cicd-pipeline-agent"):
        v, ok, f5 = _rev(a, F(a))
        assert ok and v["veredicto"] == "aprobado", (a, v["hallazgos"])


def test_arquitectura_entidad_sin_componente():
    o = F("solution-architect-agent"); o["componentes"][1]["entidades"] = []
    v, ok, _ = _rev("solution-architect-agent", o)
    assert not ok and any("ZonaEntrega" in h["detalle"] for h in v["hallazgos"])


def test_parametro_de_ruta_no_declarado_rechazado():
    o = F("api-designer-agent"); o["endpoints"][0]["parametros"] = []
    v, ok, _ = _rev("api-designer-agent", o)
    assert not ok and any(h["regla"] == "F5.openapi_valid" and "pedidoId" in h["detalle"] for h in v["hallazgos"])


def test_openapi_renderizado_valido():
    from openapi_spec_validator import validate
    from core.render import openapi_from_design
    validate(openapi_from_design(F("api-designer-agent")))


def test_workflow_needs_inexistente_rechazado():
    o = F("cicd-pipeline-agent"); o["pipelines"][0]["jobs"][1]["needs"] = ["build"]
    v, ok, _ = _rev("cicd-pipeline-agent", o)
    assert not ok and any("build" in h["detalle"] for h in v["hallazgos"])


def test_nombres_normalizados():
    assert verify.norm("Zona Entrega") == verify.norm("ZonaEntrega") and verify.norm("Campaña") == verify.norm("campana")


def test_refinement_rounds_no_bloquea():
    v, ok, f5 = governance.review(REG.agents["api-designer-agent"], F("api-designer-agent"), CTX, 2)
    assert ok and v["veredicto"] == "aprobado" and not f5["refinement_rounds"]["ok"]


def test_criterio_sin_caso_rechazado():
    o = F("test-case-generator-agent"); o["casos"] = [c for c in o["casos"] if c["historia"] != "US-02"]
    v, ok, _ = _rev("test-case-generator-agent", o)
    assert not ok and any("US-02#1" in h["detalle"] for h in v["hallazgos"])


def test_pytest_no_compila():
    assert not verify.pytest_code_ok("def test_x(:\n  pass")
    assert verify.pytest_code_ok("def test_x():\n    assert True\n")


def test_prod_sin_puerta_manual_rechazado():
    o = F("cicd-pipeline-agent")
    for p in o["pipelines"]:
        for g in p["gates"]:
            g["tipo"] = "automatica"
    v, ok, _ = _rev("cicd-pipeline-agent", o)
    assert not ok and any(h["regla"] == "F5.prod_manual_gate" for h in v["hallazgos"])


def test_pytest_con_fences_y_clase():
    assert verify.pytest_code_ok("```python\nclass TestX:\n    def test_a(self):\n        assert 1\n```")


def test_lenguaje_ubicuo_por_contencion():
    m = verify.metrics_domain_modeling({"entidades": [{"nombre": "Pedido"}], "lenguaje_ubicuo": [{"termino": "Pedido de campaña"}], "eventos": [], "transiciones": []}, {})
    assert m["ubiquitous_coverage"] == 1.0


def test_codigo_como_lineas():
    assert verify.pytest_code_ok(["def test_a():", "    x = 1", "    assert x == 1"])
    assert not verify.pytest_code_ok(["def test_a(): x = 1 assert x == 1"])


def test_orquestador_sella_procedencia():
    from core.orchestrator import Orchestrator
    out = {"req_id": "X", "provenance": {"contract_version": "1.0", "req_id": "X", "agent": "product-analyst", "phase": "discovery", "inputs": [], "knowledge_refs": ["BR-010"]}}
    Orchestrator._stamp_provenance(REG.agents["domain-modeling-agent"], out, "SIM-P05-R001")
    assert out["provenance"]["agent"] == "domain-modeling" and out["req_id"] == "SIM-P05-R001"


def test_integracion_consigo_mismo_rechazada():
    o = F("solution-architect-agent"); o["integraciones"][0]["destino"] = o["integraciones"][0]["origen"]
    v, ok, _ = _rev("solution-architect-agent", o)
    assert not ok and any("distintos" in h["detalle"] for h in v["hallazgos"])


def test_204_con_esquema_rechazado():
    o = F("api-designer-agent"); o["endpoints"][0]["respuestas"] = [{"status": 204, "descripcion": "sin contenido", "esquema": "EstadoPedido"}]
    v, ok, _ = _rev("api-designer-agent", o)
    assert not ok and any("204" in h["detalle"] for h in v["hallazgos"])


def test_pytest_sin_checkout_en_su_job_rechazado():
    o = F("cicd-pipeline-agent"); j = o["pipelines"][0]["jobs"][0]; j["steps"] = [s for s in j["steps"] if not s.get("uses")]
    v, ok, _ = _rev("cicd-pipeline-agent", o)
    assert not ok and any("checkout" in h["detalle"] for h in v["hallazgos"])


def test_accion_inexistente_rechazada():
    o = F("cicd-pipeline-agent"); o["pipelines"][0]["jobs"][0]["steps"].append({"nombre": "Escaneo", "uses": "actions/vulnerability-scanner@v1"})
    v, ok, _ = _rev("cicd-pipeline-agent", o)
    assert not ok and any("vulnerability-scanner" in h["detalle"] for h in v["hallazgos"])
