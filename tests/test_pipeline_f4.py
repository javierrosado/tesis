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
    assert not ok and any("días de release permitidos" in h["detalle"] for h in v["hallazgos"])


def test_flujo_manual_reanudable(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROVIDER", "mock")  # alias histórico de prueba_offline: verifica la compatibilidad
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


def test_modelo_diferido_pausa_sin_sustituir(tmp_path, monkeypatch):
    import os, shutil
    from pathlib import Path
    from core.orchestrator import Orchestrator, ModelDeferred
    from core.telemetry import Telemetry
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PIPELINE_PROVIDER", "vllm_local"); monkeypatch.setenv("GATES_MODE", "auto")
    o = Orchestrator(root, Telemetry(tmp_path / "t.jsonl", run_id="t"), today="2026-11-24")
    assert o.reg.provider_for("backend-developer-agent")[0] == "vllm_teacher"
    monkeypatch.setenv("PROVIDERS_DOWN", "vllm_teacher")
    try:
        o._port(o.reg.agents["backend-developer-agent"]); assert False
    except ModelDeferred:
        pass
    o._port(o.reg.agents["product-analyst-agent"])   # los demás agentes no se afectan


def test_devoluciones_humanas_se_acumulan(tmp_path, monkeypatch):
    """ensayo1: al devolver por segunda vez, el agente recibe la versión devuelta y TODAS las devoluciones previas."""
    monkeypatch.setenv("PIPELINE_PROVIDER", "prueba_offline"); monkeypatch.setenv("GATES_MODE", "manual")
    out = ROOT / "data/requerimientos/SIM-P05-R001/output"; shutil.rmtree(out, ignore_errors=True)
    capturas = []
    for i, motivo in enumerate(["agregar casos negativos", "quitar la fecha estimada antes del despacho", None]):
        orch = Orchestrator(ROOT, Telemetry(tmp_path / "ev.jsonl"), seed=1, today="2026-11-24")
        orig = orch._messages
        orch._messages = lambda *a, **k: capturas.append((a, k)) or orig(*a, **k)
        orch.run("SIM-P05-R001")
        if motivo is None:
            break
        pend = json.loads((out / "pendientes" / "user_story_set.json").read_text(encoding="utf-8"))
        (out / "aprobaciones").mkdir(exist_ok=True)
        (out / "aprobaciones" / "user_story_set.json").write_text(json.dumps({"decision": "returned", "motivo": motivo, "por": "prueba",
                                                                               "ts": f"2026-11-24T1{i}:00:00+00:00", "hash": pend["hash"]}), encoding="utf-8")
    hist = (out / "devoluciones" / "user_story_set.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(hist) == 2
    con_fb = [c for c in capturas if len(c[0]) >= 4 and c[0][3]]
    textos = [json.dumps([m["content"] for m in orig(*c[0], **c[1])], ensure_ascii=False) for c in con_fb]
    assert "agregar casos negativos" in textos[-1] and "quitar la fecha estimada" in textos[-1]       # vigentes también en rondas de governance
    assert any("versión que el revisor humano te devolvió" in x and "quitar la fecha estimada" in x for x in textos)


def test_correccion_humana_la_hace_el_maestro(monkeypatch):
    """D-E1: con vLLM, la corrección tras una devolución humana usa el maestro; sin él disponible, se difiere (no se sustituye)."""
    from core.orchestrator import ModelDeferred
    monkeypatch.setenv("PIPELINE_PROVIDER", "vllm_local")
    assert REG.correccion_provider("product-analyst-agent")[0] == "vllm_teacher"
    monkeypatch.setenv("PROVIDERS_DOWN", "vllm_teacher")
    orch = Orchestrator(ROOT, Telemetry(ROOT / "telemetry" / "tmp_correccion.jsonl"), seed=1, today="2026-11-24")
    import pytest
    with pytest.raises(ModelDeferred):
        orch._port(REG.agents["product-analyst-agent"], correccion=True)
    orch._port(REG.agents["product-analyst-agent"], correccion=False)      # la primera versión sigue con su LoRA
    monkeypatch.setenv("PIPELINE_PROVIDER", "prueba_offline")
    assert REG.correccion_provider("product-analyst-agent") is None


def test_pruebas_sin_servicio_detectadas():
    """ensayo1 r10: una prueba que no llama a un endpoint pasa siempre y no verifica el servicio."""
    qa = {"suites": [{"id": "SA-001", "lineas": ["import pytest", "", "def test_ok(client, db):", "    r = client.get('/v1/x')", "    assert r.status_code == 200", "",
                                                 "def test_tautologica(db):", "    nota = {'a': 1}", "    assert nota['a'] == 1"]}]}
    assert verify.pruebas_sin_servicio(qa) == ["SA-001::test_tautologica"]
    assert set(verify.funciones_de_prueba(qa)) == {"SA-001::test_ok", "SA-001::test_tautologica"}


def test_devolucion_de_codigo_vigente_en_todos_los_ciclos(monkeypatch):
    """ensayo1 r11: el motivo del Tech Lead llega al backend en el ciclo 0 y también en los ciclos automáticos de remediación;
    con pruebas fallidas, qa_suite no se aprueba por riesgo bajo (queda para el QA Lead)."""
    import pytest
    from core.orchestrator import PendingApproval
    monkeypatch.setenv("GATES_MODE", "manual")
    orch = Orchestrator(ROOT, Telemetry(ROOT / "telemetry" / "tmp_bucle.jsonl"), seed=1, today="2026-11-24")
    h = {"decision": "returned", "role": "tech_lead", "motivo": "usar exactamente estos pedidos de ejemplo", "ts": "2026-11-24T01:00:00+00:00"}
    guardado = {"code_review": ({"veredicto": "cambios_requeridos", "hallazgos": []}, {"gate": {"decision": "pending", "role": "tech_lead", "hash": "x", "solicitado": h["ts"]},
                                                                                    "verdict": {"hallazgos": []}}),
                "qa_suite": ({"suites": []}, {"gate": {"decision": "deferred"}, "verdict": {"hallazgos": []}})}
    monkeypatch.setattr(orch, "_load", lambda req, art: guardado.get(art))
    monkeypatch.setattr(orch, "_save", lambda ctx, art, out, meta: guardado.__setitem__(art, (out, meta)))
    monkeypatch.setattr(orch, "_human_decision", lambda *a: h)
    monkeypatch.setattr(orch, "_registrar_devolucion", lambda *a: [h])
    monkeypatch.setattr(orch, "_special_payload", lambda *a: {})
    monkeypatch.setattr(orch, "_backend_payload", lambda *a: {})
    llamadas = []

    def run_agent(name, payload, ctx, feedback0=None, force=False, defer_gate=False):
        llamadas.append((name, feedback0))
        if name == "code-review-agent":
            ctx["code_review"] = {"veredicto": "cambios_requeridos", "hallazgos": []}
            return ctx["code_review"]
        ctx.setdefault("qa_suite", {"suites": []})
        return {}
    monkeypatch.setattr(orch, "run_agent", run_agent)
    monkeypatch.setattr(verify, "quality_facts", lambda ctx: {"pruebas_fallidas": 3, "pruebas_total": 5, "criticos": 0, "pruebas_sin_servicio": 0})
    monkeypatch.setattr(sandbox, "run_tests", lambda *a: {"fallos": [{"prueba": "t1", "detalle": "assert 1 == 2"}]})
    monkeypatch.setattr(verify, "app_files", lambda *a, **k: {})
    with pytest.raises(PendingApproval):
        orch.quality_loop({"req_id": "SIM-P05-R001"}, {}, max_cycles=2)
    back = [fb for n, fb in llamadas if n == "backend-developer-agent"]
    assert len(back) == 3                                                  # ciclo 0 (devolución) + 2 ciclos automáticos
    assert all(any("usar exactamente estos pedidos" in f["detalle"] for f in fb) for fb in back)
    assert guardado["qa_suite"][1]["gate"]["decision"] == "pending"          # 3 pruebas fallidas: no se aprueba por riesgo bajo
