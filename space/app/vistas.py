"""Lógica de las pantallas D1–D7, sin FastAPI: lee la carpeta del piloto y arma lo que muestra la consola.

Todo se calcula a partir de los archivos que escribe el job; la consola no guarda estado propio salvo el registro de
accesos (R1) y lo que el usuario registra (alta, decisiones, defectos, despliegues).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]

# etapa del tablero → nodos del DAG y artefactos (config/dag.yaml)
ETAPAS = [
    ("Discovery", [("stories", "user_story_set"), ("domain", "domain_model"), ("ux", "ux_spec")]),
    ("Arquitectura", [("architecture", "solution_architecture"), ("security", "security_compliance")]),
    ("Ingeniería", [("api", "api_design"), ("data", "data_model"), ("backend", "backend_code"), ("tests", "test_cases")]),
    ("Calidad", [("qa", "qa_suite"), ("code_review", "code_review")]),
    ("DevOps", [("cicd", "cicd_pipeline"), ("release", "release_plan")]),
]
ORDEN_ESTADO = ["error", "devuelto", "esperando_gate", "escalado", "rechazado_governance", "en_curso", "pendiente", "aprobado"]


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def agentes() -> dict[str, str]:
    """artefacto → agente, desde agents/*/agent.yaml."""
    res = {}
    for f in sorted((REPO / "agents").glob("*/agent.yaml")):
        spec = yaml.safe_load(f.read_text(encoding="utf-8"))
        art = (spec.get("gate") or {}).get("artefact") or spec.get("artefact")
        if art:
            res[art] = spec["name"]
    return res


# ---------------------------------------------------------------- estado de un nodo
def estado_nodo(out: Path, art: str) -> dict:
    """Estado de un artefacto: pendiente, rechazado_governance (ronda n), esperando_gate, aprobado, devuelto, escalado."""
    rech = [r for r in _jsonl(out / "rechazos.jsonl") if _art_de_rechazo(r) == art]
    dec = _j(out / f"{art}.decision.json")
    pend = _j(out / "pendientes" / f"{art}.json")
    apr = _j(out / "aprobaciones" / f"{art}.json")
    ins = sorted(out.glob(f"{art}.input.r*.json"))
    ultimo = _j(ins[-1]) if ins else None
    nodo = {"artefacto": art, "rondas_governance": len(rech), "entradas": len(ins),
            "modelo": (ultimo or {}).get("adaptador") or (ultimo or {}).get("modelo"),
            "proveedor": (ultimo or {}).get("proveedor")}
    if pend and not (apr and apr.get("hash") == pend.get("hash")):
        nodo.update(estado="escalado" if pend.get("escalado") else "esperando_gate", solicitado=pend.get("solicitado"))
    elif apr and pend and apr.get("hash") == pend.get("hash"):
        nodo.update(estado="aprobado" if apr["decision"] == "approved" else "devuelto", decision=apr)
    elif dec:
        g = (dec.get("gate") or {}).get("decision")
        nodo.update(estado={"approved": "aprobado", "returned": "devuelto", "pending": "esperando_gate"}.get(g, "aprobado"),
                    gate=dec.get("gate"))
    elif rech:
        nodo["estado"] = "rechazado_governance"
    elif ins:
        nodo["estado"] = "en_curso"
    else:
        nodo["estado"] = "pendiente"
    return nodo


def _art_de_rechazo(r: dict) -> str | None:
    return _ARTE_POR_AGENTE.get(r.get("agent"))


_ARTE_POR_AGENTE: dict[str, str] = {}


def _init_mapa():
    if not _ARTE_POR_AGENTE:
        _ARTE_POR_AGENTE.update({a: art for art, a in agentes().items()})


# ---------------------------------------------------------------- D1 tablero
def tablero(estado_dir: Path, reqs_dir: Path | None = None) -> list[dict]:
    _init_mapa()
    ids = set(p.name for p in estado_dir.iterdir()) if estado_dir.exists() else set()
    if reqs_dir and reqs_dir.exists():
        ids |= {p.name for p in reqs_dir.iterdir() if (p / "input").exists()}
    filas = []
    for req in sorted(ids):
        out = estado_dir / req / "output"
        st = _j(out / "estado.json") or {"estado": "registrado"}
        etapas = {}
        for etapa, nodos in ETAPAS:
            est = [estado_nodo(out, art)["estado"] for _, art in nodos]
            etapas[etapa] = min(est, key=ORDEN_ESTADO.index) if any(e != "pendiente" for e in est) else "pendiente"
            if all(e == "aprobado" for e in est):
                etapas[etapa] = "aprobado"
        etapas["Despliegue"] = ("aprobado" if st.get("estado") == "desplegado" else
                                "error" if st.get("estado") == "error" else "en_curso" if st.get("go_release") else "pendiente")
        gates = [p.stem for p in (out / "pendientes").glob("*.json")] if (out / "pendientes").exists() else []
        abiertos = [g for g in gates if estado_nodo(out, g)["estado"] in ("esperando_gate", "escalado")]
        filas.append({"req": req, "estado": st.get("estado"), "entrada_pipeline": st.get("entrada_pipeline"),
                      "fin": st.get("fin"), "go_release": st.get("go_release"),
                      "deploy_ok_staging": st.get("deploy_ok_staging"), "etapas": etapas, "gates_abiertos": abiertos})
    return filas


# ---------------------------------------------------------------- D3 DAG y panel por paso
def dag(estado_dir: Path, req: str) -> dict:
    _init_mapa()
    out = estado_dir / req / "output"
    return {"req": req, "estado": _j(out / "estado.json"),
            "etapas": [{"etapa": e, "nodos": [{"id": n, **estado_nodo(out, a), "agente": agentes().get(a)} for n, a in nodos]}
                       for e, nodos in ETAPAS]}


DERIVADOS = {"api_design": ["api_design.openapi.yaml"], "data_model": ["data_model.up.sql", "data_model.down.sql"]}


def paso(estado_dir: Path, req: str, art: str, telemetria: list[dict] | None = None) -> dict:
    _init_mapa()
    if not re.fullmatch(r"[a-z_]+", art):
        raise ValueError("artefacto inválido")
    out = estado_dir / req / "output"
    agente = agentes().get(art)
    deriv = {n: (out / n).read_text(encoding="utf-8") for n in DERIVADOS.get(art, []) if (out / n).exists()}
    if art == "cicd_pipeline":
        deriv |= {p.name: p.read_text(encoding="utf-8") for p in sorted(out.glob("*.workflow.yaml"))}
    if art == "backend_code" and (out / "servicio").exists():
        deriv |= {str(p.relative_to(out)): p.read_text(encoding="utf-8") for p in sorted((out / "servicio").rglob("*.py"))}
    rondas = [r for r in _jsonl(out / "rechazos.jsonl") if r.get("agent") == agente]
    eventos = [e for e in (telemetria or []) if e.get("req_id") == req and (e.get("agent") == agente or e.get("artefact") == art)]
    return {"req": req, "artefacto": art, "agente": agente,
            "input": [_j(p) for p in sorted(out.glob(f"{art}.input.r*.json"))],
            "output": _j(out / f"{art}.json"), "derivados": deriv,
            "rondas_governance": rondas,
            "decision": {"meta": _j(out / f"{art}.decision.json"), "pendiente": _j(out / "pendientes" / f"{art}.json"),
                         "aprobacion": _j(out / "aprobaciones" / f"{art}.json")},
            "devoluciones": _jsonl(out / "devoluciones" / f"{art}.jsonl"),
            "eventos": eventos}


# ---------------------------------------------------------------- D4 gates
def discrepancia(p: dict) -> bool:
    """Aviso de D4: governance aprobó pero el dictamen IA recomienda devolver (o al revés)."""
    dic = p.get("dictamen_ia") or {}
    gov_ok = not any(h.get("severidad") in ("critica", "mayor") for h in p.get("hallazgos_governance", []))
    return bool(dic) and ((dic.get("recomendacion") == "returned") == gov_ok)


# ---------------------------------------------------------------- D7 auditoría (R3)
def kappa(pares: list[tuple[str, str]]) -> dict:
    """Matriz 2×2 humano (filas) × IA (columnas) y kappa de Cohen."""
    m = {(h, i): 0 for h in ("approved", "returned") for i in ("approved", "returned")}
    for h, i in pares:
        if (h, i) in m:
            m[(h, i)] += 1
    n = sum(m.values())
    if not n:
        return {"n": 0, "matriz": {}, "kappa": None, "acuerdo": None}
    po = (m[("approved", "approved")] + m[("returned", "returned")]) / n
    pe = sum(((m[(c, "approved")] + m[(c, "returned")]) / n) * ((m[("approved", c)] + m[("returned", c)]) / n) for c in ("approved", "returned"))
    k = None if math.isclose(pe, 1.0) else round((po - pe) / (1 - pe), 3)
    return {"n": n, "acuerdo": round(po, 3), "kappa": k,
            "matriz": {"humano_aprueba": {"ia_aprueba": m[("approved", "approved")], "ia_devuelve": m[("approved", "returned")]},
                       "humano_devuelve": {"ia_aprueba": m[("returned", "approved")], "ia_devuelve": m[("returned", "returned")]}}}


def clase_modelo(ins: dict | None) -> str:
    if not ins:
        return "?"
    txt = " ".join(str(ins.get(k) or "") for k in ("adaptador", "modelo", "proveedor")).lower()
    if "lora" in txt:
        return "LoRA"
    if "32b" in txt:
        return "32B maestro"
    if "8b" in txt:
        return "8B base"
    return "frontera" if ins.get("proveedor") else "?"


def decision_log(estado_dir: Path) -> list[dict]:
    log = []
    for req in sorted(p.name for p in estado_dir.iterdir()) if estado_dir.exists() else []:
        out = estado_dir / req / "output"
        for p in sorted((out / "aprobaciones").glob("*.json")) if (out / "aprobaciones").exists() else []:
            ins = sorted(out.glob(f"{p.stem}.input.r*.json"))
            log.append({"req": req, "artefacto": p.stem, "agente": agentes().get(p.stem), "clase_modelo": clase_modelo(_j(ins[-1]) if ins else None),
                        **_j(p)})
    return log


def auditoria(estado_dir: Path) -> dict:
    log = decision_log(estado_dir)
    con = [r for r in log if r.get("dictamen_ia")]
    par = lambda rs: [(r["decision"], r["dictamen_ia"].get("recomendacion")) for r in rs]
    por_agente, por_clase = defaultdict(list), defaultdict(list)
    for r in con:
        por_agente[r.get("agente") or "?"].append(r); por_clase[r["clase_modelo"]].append(r)
    return {"global": kappa(par(con)), "sin_dictamen": len(log) - len(con),
            "por_agente": {a: kappa(par(rs)) for a, rs in sorted(por_agente.items())},
            "por_clase": {c: kappa(par(rs)) for c, rs in sorted(por_clase.items())},
            "decision_log": log}


# ---------------------------------------------------------------- R4 paquete de evidencia
def sha_input(req_dir: Path) -> str:
    h = hashlib.sha256()
    for f in sorted((req_dir / "input").glob("*")) if (req_dir / "input").exists() else []:
        h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()


def evidencia_zip(piloto_dir: Path, pilot: str) -> bytes:
    est, reqs = piloto_dir / "estado", piloto_dir / "requerimientos"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("decision_log.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in decision_log(est)))
        for sub in ("telemetria", "entornos", "ventanas", "registros"):
            for f in sorted((piloto_dir / sub).rglob("*")) if (piloto_dir / sub).exists() else []:
                if f.is_file():
                    z.write(f, f"{sub}/{f.relative_to(piloto_dir / sub)}")
        for f in sorted(est.rglob("*.input.r*.json")) if est.exists() else []:
            z.write(f, f"inputs/{f.relative_to(est)}")
        if (piloto_dir / "accesos.jsonl").exists():
            z.write(piloto_dir / "accesos.jsonl", "accesos.jsonl")
        for rel in ("runs/MANIFEST.md", "docs/checklists_gates.md"):
            if (REPO / rel).exists():
                z.write(REPO / rel, Path(rel).name)
        hashes = {r.name: sha_input(r) for r in sorted(reqs.iterdir())} if reqs.exists() else {}
        z.writestr("hashes_input.json", json.dumps(hashes, ensure_ascii=False, indent=1))
        z.writestr("LEEME.txt", f"Paquete de evidencia de {pilot} generado por la consola del piloto (R4).\n")
    return buf.getvalue()
