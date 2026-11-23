"""Protocolo F5 v2: calendario del piloto, marcas de lead time, clasificación de despliegues, indicadores H1–H6 y contraste."""
import json, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from core import calendario, deploy           # noqa: E402
from core.orchestrator import Orchestrator    # noqa: E402
from core.telemetry import Telemetry          # noqa: E402
import indicadores                            # noqa: E402

CFG = calendario.config("piloto1")


def test_calendario_piloto1():
    assert CFG["inicio"] == date(2026, 11, 30) and CFG["fin"] == date(2026, 12, 11)
    assert not calendario.ventana_valida("2026-12-08", "2026-11-30", CFG)          # martes feriado: movido al 09/12
    assert calendario.ventana_valida("2026-12-09", "2026-11-30", CFG)
    assert not calendario.ventana_valida("2026-12-01", "2026-12-02", CFG)          # no anterior a hoy
    assert calendario.dias_release_desde("2026-12-04", CFG) == ["2026-12-09", "2026-12-10"]
    assert calendario.ventana_valida("2026-11-26", "2026-11-24", None)             # sin piloto: martes o jueves
    assert not calendario.ventana_valida("2026-11-25", "2026-11-24", None)


def test_dias_habiles_saltan_fin_de_semana_y_feriado():
    assert calendario.sumar_dias_habiles(date(2026, 12, 4), 3, CFG["feriados"]) == date(2026, 12, 10)
    assert calendario.dias_entre("2026-12-01T09:00:00-05:00", "2026-12-03T21:00:00-05:00") == 2.5


def test_clasificar_despliegue():
    ok = {"jobs": [{"nombre": "run-tests", "conclusion": "success"}, {"nombre": "deploy", "conclusion": "success"}]}
    pyt = {"jobs": [{"nombre": "run-tests", "conclusion": "failure"}, {"nombre": "deploy", "conclusion": "skipped"}]}
    smk = {"jobs": [{"nombre": "run-tests", "conclusion": "success"}, {"nombre": "deploy", "conclusion": "failure"}]}
    assert deploy.clasificar(ok)[0] == "ok" and deploy.clasificar(pyt)[0] == "fallo_pytest" and deploy.clasificar(smk)[0] == "fallo_smoke"


def test_entrada_pipeline_y_defectos_pre_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROVIDER", "prueba_offline"); monkeypatch.setenv("GATES_MODE", "auto")
    import shutil
    shutil.rmtree(ROOT / "data/requerimientos/SIM-P05-R001/output", ignore_errors=True)
    orch = Orchestrator(ROOT, Telemetry(tmp_path / "ev.jsonl"), seed=1, today="2026-11-24")
    orch.run("SIM-P05-R001")
    st = json.loads((ROOT / "data/requerimientos/SIM-P05-R001/output/estado.json").read_text(encoding="utf-8"))
    assert st["entrada_pipeline"].endswith("-05:00")
    ev = Telemetry(tmp_path / "ev.jsonl").read()
    assert next(e for e in ev if e["event"] == "pipeline_started")["entrada_pipeline"] == st["entrada_pipeline"]
    assert all(e.get("deteccion") == "pre_gate" for e in ev if e["event"] == "defect_detected")


def _estado(base: Path, req: str, **st):
    d = base / req / "output"; d.mkdir(parents=True)
    (d / "estado.json").write_text(json.dumps({"req_id": req, **st}), encoding="utf-8")
    art = {"x": 1, "provenance": {"req_id": req, "phase": "discovery"}}
    (d / "user_story_set.json").write_text(json.dumps(art), encoding="utf-8")
    (d / "user_story_set.decision.json").write_text("{}", encoding="utf-8")


def test_indicadores_hipotesis_censura_rollback_y_escapados(tmp_path):
    _estado(tmp_path, "SIM-P05-R001", entrada_pipeline="2026-11-30T09:00:00-05:00", go_release="2026-12-02T09:00:00-05:00",
            deploy_ok_staging="2026-12-03T10:00:00-05:00")
    _estado(tmp_path, "SIM-P05-R028", entrada_pipeline="2026-12-01T09:00:00-05:00")      # nuevo y sin go_release → censurado
    ev = [{"event": "pipeline_started", "req_id": "SIM-P05-R001"}, {"event": "pipeline_started", "req_id": "SIM-P05-R028"},
          {"event": "deployment", "req_id": "SIM-P05-R001", "resultado": "ok", "fecha": "2026-12-03T10:00:00-05:00", "observacion_hasta": "2026-12-07"},
          {"event": "deployment_outcome", "req_id": "SIM-P05-R001", "resultado": "rollback", "fecha": "2026-12-04T11:00:00-05:00"},
          {"event": "defect_detected", "req_id": "SIM-P05-R001", "deteccion": "escapado", "fecha": "2026-12-04T12:00:00-05:00"},
          {"event": "defect_detected", "req_id": "SIM-P05-R028", "deteccion": "pre_gate", "fecha": "2026-12-02T12:00:00-05:00"},
          {"event": "handoff", "req_id": "SIM-P05-R001", "to": "product-analyst-agent", "mode": "auto"},
          {"event": "agent_completed", "req_id": "SIM-P05-R001", "agent": "product-analyst-agent"}]
    h = indicadores.hipotesis(ev, tmp_path, CFG)
    f = {x["req_id"]: x for x in h["filas"]}
    assert f["SIM-P05-R001"]["h1a_d"] == 2.0 and f["SIM-P05-R001"]["h1a_d_censurado"] is False
    assert f["SIM-P05-R028"]["h1a_d_censurado"] is True and not f["SIM-P05-R028"]["historico"]
    r = h["resumen"]
    assert (r["H2_fallidos"], r["H2_despliegues"]) == (1, 1)                         # rollback dentro de 3 días hábiles
    assert r["H3_con_escapado"] == 1 and r["H3p_con_defecto"] == 2 and r["H5_%"] == 100.0 and r["H6_registradas_%"] == 100.0


def test_newcombe_valores_publicados():
    import contraste
    d, lo, hi = contraste.newcombe_independiente(56, 70, 48, 80)                    # Newcombe (1998), ejemplo: 0,0524 a 0,3339
    assert (round(lo, 4), round(hi, 4)) == (0.0524, 0.3339)
    d, lo, hi = contraste.newcombe_pareado(36, 12, 2, 0)                            # Newcombe (1998b), método 10: 0,0569 a 0,3404
    assert (round(lo, 4), round(hi, 4)) == (0.0569, 0.3404)


def test_linea_base_reproduce_cifras_del_plan():
    import contraste
    lb = contraste.linea_base(ROOT / "data/linea_base/Linea_BaseV2.xlsx")
    assert (lb["dep_fallidos"], lb["dep_total"]) == (18, 40) and len(lb["g1p"]) == 27 and len(lb["g1s"]) == 123
