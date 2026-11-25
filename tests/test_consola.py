"""Consola del piloto (Fase C): pantallas, permisos por rol, R1 (accesos) y R3/R4, con un dataset local y sin red."""
import io
import json
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from space.app import ejecutor as ej
from space.app import vistas
from space.app.almacen import AlmacenLocal
from space.app.main import crear_app

REQ = "SIM-P05-R001"


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def dataset(tmp_path):
    out = tmp_path / "piloto/piloto1/estado" / REQ / "output"
    _w(out / "estado.json", {"req_id": REQ, "estado": "esperando_aprobacion", "entrada_pipeline": "2026-12-14T10:05:00-05:00"})
    for art in ("user_story_set", "domain_model", "ux_spec"):
        _w(out / f"{art}.json", {"x": 1})
        _w(out / f"{art}.decision.json", {"gate": {"decision": "approved", "by": "politica_riesgo_bajo"}})
    _w(out / "solution_architecture.json", {"componentes": []})
    _w(out / "solution_architecture.input.r0.json", {"req_id": REQ, "ronda": 0, "modelo": "Qwen3-8B",
                                                     "adaptador": "jrosado1974/qwen3-8b-solution-architect-lora@abc"})
    _w(out / "pendientes/solution_architecture.json",
       {"artefacto": "solution_architecture", "rol": "tech_lead", "hash": "h1", "solicitado": "2026-12-14T15:00:00+00:00",
        "agente": "solution-architect-agent", "hallazgos_governance": [],
        "dictamen_ia": {"recomendacion": "returned", "motivo": "falta ADR", "por": "governance+Qwen3-32B-AWQ"}})
    _w(out / "rechazos.jsonl", json.dumps({"agent": "solution-architect-agent", "round": 0, "ts": "t", "hallazgos":
                                           [{"severidad": "mayor", "regla": "R", "detalle": "d"}], "output": {}}) + "\n")
    _w(tmp_path / "piloto/piloto1/telemetria/j1.jsonl",
       json.dumps({"event": "agent_completed", "req_id": REQ, "agent": "solution-architect-agent", "ts": "t"}) + "\n")
    return tmp_path


class FakeEjecutor:
    def __init__(self):
        self.llamadas = []

    def reanudar(self, pilot, reqs, por):
        self.llamadas.append((pilot, reqs, por)); return {"job_id": "abc123"}

    def jobs(self):
        return []

    def logs(self, job_id, tail=400):
        return ["hola", 'EVENT {"event": "handoff", "agent": "product-analyst-agent"}', "EVENT {roto"]

    def inspeccionar(self, job_id):
        return {"job_id": job_id, "estado": "RUNNING"}


@pytest.fixture
def cli(dataset, monkeypatch):
    monkeypatch.setenv("CONSOLA_USUARIOS", json.dumps({"jrosado1974": ["operador", "registrador", "aprobador"], "asesor": ["auditor"]}))
    fake = FakeEjecutor()
    app = crear_app(almacen=AlmacenLocal(dataset), ejecutor=fake, usuario_fijo="jrosado1974")
    c = TestClient(app); c.fake = fake; c.raiz = dataset
    return c


def _accesos(raiz):
    f = raiz / "piloto/piloto1/accesos.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def test_tablero_dag_y_paso(cli):
    t = cli.get("/api/tablero").json()
    assert t[0]["req"] == REQ and t[0]["etapas"]["Discovery"] == "aprobado"
    assert t[0]["etapas"]["Arquitectura"] == "esperando_gate" and t[0]["gates_abiertos"] == ["solution_architecture"]
    d = cli.get(f"/api/req/{REQ}/dag").json()
    sa = [n for e in d["etapas"] for n in e["nodos"] if n["artefacto"] == "solution_architecture"][0]
    assert sa["rondas_governance"] == 1 and "lora" in sa["modelo"]
    p = cli.get(f"/api/req/{REQ}/paso/solution_architecture").json()
    assert p["input"][0]["ronda"] == 0 and len(p["rondas_governance"]) == 1 and len(p["eventos"]) == 1
    assert cli.get(f"/api/req/{REQ}/paso/..%2Fx").status_code in (400, 404)
    assert cli.get("/api/req/..evil/dag").status_code in (400, 404)


def test_gates_discrepancia_y_decision(cli):
    g = cli.get("/api/gates").json()
    assert len(g) == 1 and g[0]["discrepancia"] is True            # governance sin hallazgos, IA recomienda devolver
    r = cli.post("/api/gates/decidir", json={"decisiones": [{"req": REQ, "artefacto": "solution_architecture", "decision": "returned"}]})
    assert r.status_code == 400 and "motivo" in r.json()["detail"]
    r = cli.post("/api/gates/decidir", headers={"X-Consola-Dispositivo": "pwa"},
                 json={"decisiones": [{"req": REQ, "artefacto": "solution_architecture", "decision": "returned", "motivo": "falta ADR-003"}]})
    assert r.status_code == 200
    ap = json.loads((cli.raiz / "piloto/piloto1/estado" / REQ / "output/aprobaciones/solution_architecture.json").read_text())
    assert ap["por"] == "Javier Rosado" and ap["hash"] == "h1" and ap["canal"] == "pwa" and ap["coincide_con_ia"] is True
    assert ap["dictamen_ia"]["por"] == "governance+Qwen3-32B-AWQ"
    assert cli.get("/api/gates").json() == []
    acc = _accesos(cli.raiz)
    assert any(a["accion"] == "devolver" and a["dispositivo"] == "pwa" for a in acc)
    assert list((cli.raiz / "piloto/piloto1/ventanas").glob("*.json"))


def test_permisos_por_rol(cli):
    h = {"X-Usuario-Prueba": "asesor"}
    assert cli.get("/api/auditoria", headers=h).status_code == 200
    assert cli.post("/api/gates/decidir", headers=h, json={"decisiones": [{}]}).status_code == 403
    assert cli.post("/api/reanudar", headers=h, json={}).status_code == 403
    assert cli.post("/api/alta", headers=h, data={"modo": "validar", "formulario": "{}"}).status_code == 403
    assert cli.get("/api/tablero", headers={"X-Usuario-Prueba": "intruso"}).status_code == 403
    assert any(a["accion"].startswith("denegado:") and a["usuario"] == "asesor" for a in _accesos(cli.raiz))


FORM = {"req_id": "SIM-P06-R001", "titulo": "Reporte de cobranzas", "proyecto": "SIM", "solicitante": "Gerencia", "tipo": "Funcional",
        "origen": "Negocio", "campana": "C1", "fecha_registro": "2026-12-01", "puntos_historia": "5", "reglas_negocio": "BR-001",
        "datos_personales": "no", "necesidad": "La gerencia necesita ver la cobranza del día por canal para decidir acciones de recupero antes del cierre.",
        "resultado_esperado": "Un reporte diario de cobranzas por canal, disponible a las 08:00, con totales y variación contra el día anterior.",
        "restricciones": "Solo lectura", "historia_original": "Como gerente quiero…", "criterios_aceptacion": "", "notas_refinamiento": "Acordado."}


def test_alta_formulario_valida_confirma_e_inmutable(cli):
    r = cli.post("/api/alta", data={"modo": "validar", "formulario": json.dumps(FORM)})
    assert r.status_code == 200, r.text
    br = r.json()["business_request"]
    assert br["contract_version"] == "1.1" and br["criterios_aceptacion"] and len(r.json()["sha256"]) == 64
    assert not (cli.raiz / "piloto/piloto1/requerimientos/SIM-P06-R001").exists()
    r = cli.post("/api/alta", data={"modo": "confirmar", "formulario": json.dumps(FORM)})
    assert r.status_code == 200 and r.json()["registrado"]
    inp = cli.raiz / "piloto/piloto1/requerimientos/SIM-P06-R001/input"
    assert sorted(p.name for p in inp.iterdir()) == sorted(["brief.md", "restricciones.json", "historia_original.md",
                                                             "criterios_aceptacion.md", "notas_refinamiento.md"])
    assert vistas.sha_input(inp.parent) == r.json()["sha256"]
    assert cli.post("/api/alta", data={"modo": "confirmar", "formulario": json.dumps(FORM)}).status_code == 409
    assert any(t["req"] == "SIM-P06-R001" for t in cli.get("/api/tablero").json())


def test_alta_zip_ignora_rutas_y_extras(cli):
    from space.app import alta
    arch = alta.desde_formulario({**FORM, "req_id": "SIM-P06-R002"})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in arch.items():
            z.writestr(f"input/{n}", b)
        z.writestr("../../evil.py", "x"); z.writestr("input/otro.txt", "x")
    r = cli.post("/api/alta", data={"modo": "confirmar"}, files={"zip": ("in.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    assert not list(cli.raiz.rglob("evil.py")) and not list(cli.raiz.rglob("otro.txt"))
    r = cli.post("/api/alta", data={"modo": "validar", "formulario": json.dumps({**FORM, "necesidad": ""}) })
    assert r.status_code in (200, 422)
    malo = cli.post("/api/alta", data={"modo": "validar", "formulario": json.dumps({k: v for k, v in FORM.items() if k != "titulo"})})
    assert malo.status_code == 422


def test_reanudar_logs_y_eventos(cli):
    r = cli.post("/api/reanudar", json={"reqs": [REQ]})
    assert r.json()["job_id"] == "abc123" and cli.fake.llamadas == [("piloto1", [REQ], "jrosado1974")]
    l = cli.get("/api/jobs/abc123/logs").json()
    assert l["eventos"] == [{"event": "handoff", "agent": "product-analyst-agent"}] and "hola" in l["lineas"]
    assert cli.get("/api/jobs/abc-123/logs").status_code == 400
    assert any(a["accion"] == "reanudar" for a in _accesos(cli.raiz))


def test_registro_defecto_y_despliegue(cli):
    assert cli.post("/api/defecto", json={"req": REQ, "etapa_deteccion": "staging", "severidad": "x", "descripcion": "d"}).status_code == 422
    r = cli.post("/api/defecto", json={"req": REQ, "etapa_deteccion": "staging", "severidad": "alta", "descripcion": "500 en /pagos"})
    assert r.json()["event"] == "defect_detected"
    cli.post("/api/despliegue", json={"req": REQ, "resultado": "rollback", "motivo": "smoke falló"})
    reg = cli.get("/api/registros").json()
    assert len(reg["defectos_escapados"]) == 1 and reg["post_despliegue"][0]["resultado"] == "rollback"


def test_auditoria_kappa_y_evidencia(cli):
    cli.post("/api/gates/decidir", json={"decisiones": [{"req": REQ, "artefacto": "solution_architecture", "decision": "approved"}]})
    a = cli.get("/api/auditoria").json()
    assert a["global"]["n"] == 1 and a["decision_log"][0]["clase_modelo"] == "LoRA"
    z = zipfile.ZipFile(io.BytesIO(cli.get("/api/evidencia.zip").content))
    nombres = z.namelist()
    assert "decision_log.jsonl" in nombres and "hashes_input.json" in nombres and "accesos.jsonl" in nombres
    assert any(n.startswith("inputs/") for n in nombres) and any(n.startswith("telemetria/") for n in nombres)


def test_kappa_y_cron():
    k = vistas.kappa([("approved", "approved")] * 8 + [("returned", "returned")] * 2)
    assert k["kappa"] == 1.0 and k["acuerdo"] == 1.0
    k = vistas.kappa([("approved", "approved")] * 5 + [("approved", "returned")] * 5 + [("returned", "approved")] * 5 + [("returned", "returned")] * 5)
    assert k["kappa"] == 0.0
    assert vistas.kappa([])["kappa"] is None
    assert ej.cron_utc("10:00") == "0 15 * * *" and ej.cron_utc("18:00") == "0 23 * * *"
    env = ej.env_job("piloto1")
    assert env["ALL"] == "1" and env["GATES_MODE"] == "manual" and env["PILOT"] == "piloto1"
