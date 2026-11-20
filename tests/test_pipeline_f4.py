"""F4: ejecución real (DDL, servicio, pruebas, análisis estático), gates manuales reanudables y aprobación por riesgo."""
import json, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry            # noqa: E402
from core.telemetry import Telemetry           # noqa: E402
from core.orchestrator import Orchestrator     # noqa: E402
from core import governance, verify            # noqa: E402
from core.tools import sandbox                 # noqa: E402

REG = Registry(ROOT)
F = lambda a: json.loads((ROOT / f"tests/fixtures/{a}/SIM-P05-R001.json").read_text(encoding="utf-8"))
CTX = {"req_id": "SIM-P05-R001", "hoy": "2026-11-24", "domain_model": F("domain-modeling-agent"), "solution_architecture": F("solution-architect-agent"),
       "api_design": F("api-designer-agent"), "data_model": F("data-model-agent"), "backend_code": F("backend-developer-agent"),
       "test_cases": F("test-case-generator-agent"), "qa_suite": F("qa-automation-agent"), "code_review": F("code-review-agent"),
       "security_compliance": F("security-compliance-agent")}


def test_ddl_se_ejecuta_y_fk_invalida_falla():
    assert sandbox.ddl_check(CTX["data_model"])["ok"]
    bad = json.loads(json.dumps(CTX["data_model"])); bad["tablas"][1]["fks"][0]["tabla_ref"] = "no_existe"
    v, ok, _ = governance.review(REG.agents["data-model-agent"], bad, CTX, 0)
    assert not ok and any("no existe" in h["detalle"] for h in v["hallazgos"])


def test_servicio_importa_y_responde():
    sm = sandbox.smoke(verify.app_files(CTX), CTX["api_design"])
    assert sm["import_ok"] and all(r["status"] < 500 for r in sm["resultados"])


def test_handler_roto_rechazado():
    bad = json.loads(json.dumps(CTX["backend_code"])); bad["handlers"][0]["lineas"] = ["return DB[\"tabla_inexistente\"][0]"]
    v, ok, f5 = governance.review(REG.agents["backend-developer-agent"], bad, CTX, 0)
    assert not ok and f5["smoke_ok"]["value"] < 0.8


def test_pruebas_reales_pasan_y_detectan_defecto():
    rt = sandbox.run_tests(verify.app_files(CTX), CTX["qa_suite"])
    assert rt["suite_runs"] and rt["failed"] == 0 and rt["collected"] == 3
    roto = json.loads(json.dumps(CTX["backend_code"])); roto["handlers"][0]["lineas"][2] = roto["handlers"][0]["lineas"][2].replace('p["estado"]', '"registrado"')
    rt2 = sandbox.run_tests(verify.app_files(CTX, roto), CTX["qa_suite"])
    assert rt2["failed"] == 1


def test_release_no_go_inconsistente_rechazado():
    rel = F("release-manager-agent"); rel["release"]["ventana"] = "2026-11-25"   # miércoles
    v, ok, _ = governance.review(REG.agents["release-manager-agent"], rel, CTX, 0)
    assert not ok and any("martes o jueves" in h["detalle"] for h in v["hallazgos"])


def test_flujo_manual_reanudable(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROVIDER", "mock")
    out = ROOT / "data/requerimientos/SIM-P05-R001/output"; shutil.rmtree(out, ignore_errors=True)
    aprobados = []
    for _ in range(10):
        orch = Orchestrator(ROOT, Telemetry(tmp_path / "ev.jsonl"), seed=1, today="2026-11-24")
        ctx = orch.run("SIM-P05-R001")
        if ctx["_estado"] != "esperando_aprobacion":
            break
        for p in (out / "pendientes").glob("*.json"):
            req = json.loads(p.read_text(encoding="utf-8")); art = p.stem
            if art in aprobados:
                continue
            (out / "aprobaciones").mkdir(exist_ok=True)
            (out / "aprobaciones" / f"{art}.json").write_text(json.dumps({"decision": "approved", "por": "prueba", "ts": "2026-11-24T15:00:00+00:00", "hash": req["hash"]}), encoding="utf-8")
            aprobados.append(art)
    assert ctx["_estado"] == "validado_sin_despliegue"
    assert sorted(aprobados) == sorted(["user_story_set", "solution_architecture", "security_compliance", "code_review", "release_plan"])
    ev = Telemetry(tmp_path / "ev.jsonl").read()
    assert sum(1 for e in ev if e["event"] == "pipeline_paused") == 5
    assert any(e["event"] == "human_gate" and e.get("by") == "politica_riesgo_bajo" for e in ev)


def test_deploy_agrega_checkout_determinista():
    from core import verify
    job = {"steps": [{"name": "deploy", "run": "./deploy.sh staging"}]}
    assert verify.needs_checkout(job)
    job2 = {"steps": [{"uses": "actions/checkout@v4"}, {"run": "./deploy.sh staging"}]}
    assert not verify.needs_checkout(job2)
    assert not verify.needs_checkout({"steps": [{"run": "echo listo"}]})
