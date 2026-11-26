"""Indicadores del piloto para la tesis, calculados solo desde la telemetría (eventos JSONL) y el estado publicado.

Agrupa cada agente por la clase de modelo que lo atendió, para que la tesis pueda contrastar
los agentes especializados (QLoRA, F3) con los no entrenados:
  - lora    : Qwen3-8B + adaptador QLoRA del agente (model_id = nombre del agente)
  - base    : Qwen3-8B sin adaptar
  - maestro : Qwen3-32B-AWQ (D-F4-1 opción C: backend, QA, code-review)
  - frontera: modelo de HF Inference Providers asignado por N4 (GLM-5.3, DeepSeek V4-Flash)

Uso:  python scripts/indicadores.py telemetria/*.jsonl [--md salida.md] [--csv salida.csv]
      python scripts/indicadores.py telemetria/*.jsonl registros/*.jsonl --estado piloto/piloto1/estado --piloto piloto1 \
             --csv-req piloto_por_req.csv          # protocolo F5 v2: H1a, H1b, H2, H3, H3', H4, H5, H6 y censura

Protocolo F5 v2 (definiciones del Lote A del Plan V2.7):
  H1a  días desde entrada_pipeline hasta go_release (aprobación del release); H1b hasta deploy_ok_staging.
       Sin marca al cierre del piloto: el caso queda censurado en la fecha de fin y se reporta aparte.
  H2   despliegues fallidos / total: fallo de build, pytest o smoke, o rollback o corrección dentro de 3 días hábiles.
  H3   requerimientos con ≥ 1 defecto escapado (smoke, staging o aceptación, dentro de su ventana) / total.
  H3'  requerimientos con ≥ 1 defecto de cualquier tipo (previo a la puerta o escapado) / total.
  H4   despliegues exitosos / (días de exposición ÷ 30); descriptivo.
  H5   requerimientos con origen, fase y decisión registrados en cada artefacto / total.
  H6   handoffs automáticos / total · agentes con su transición registrada / agentes ejecutados.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import calendario  # noqa: E402

NO_ARTEFACTOS = {"estado", "deployment", "business_request"}


def clase(model_id: str | None, agent: str) -> str:
    if not model_id:
        return "determinista"
    if model_id == agent:
        return "lora"
    if ":" in model_id or model_id.startswith(("zai-org/", "deepseek-ai/", "claude")):   # v2 (N4): HF Inference Providers
        return "frontera"
    return "maestro" if "32B" in model_id else "base"


def cargar(paths):
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def calcular(events: list[dict]) -> dict:
    ag = defaultdict(lambda: {"llamadas": 0, "tin": [], "tout": [], "lat": [], "r0_ok": 0, "evaluados": 0, "rondas": [], "escal": 0, "clase": "?"})
    f5_by = defaultdict(dict)   # (req, agent) -> {round: ok}
    req = defaultdict(lambda: {"inicio": None, "fin": None, "gates": 0, "gates_humanos": 0, "espera_h": 0.0, "defectos": 0, "remediaciones": 0, "estado": None})
    hai = {"con_dictamen": 0, "coinciden": 0, "devueltos_humano": 0, "devueltos_ia": 0}   # concordancia humano–IA (opción A)
    for e in events:
        ev, a, r = e["event"], e.get("agent"), e.get("req_id")
        if ev == "agent_completed":
            x = ag[a]; x["llamadas"] += 1; x["clase"] = clase(e.get("model_id"), a)
            x["tin"].append(e.get("tokens_in", 0)); x["tout"].append(e.get("tokens_out", 0)); x["lat"].append(e.get("latency_ms", 0))
        elif ev == "f5_check":
            f5_by[(r, a)][e["round"]] = e["ok"]
        elif ev == "escalation":
            ag[a]["escal"] += 1
        elif ev == "human_gate":
            q = req[r]; q["gates"] += 1
            if not e.get("delegated") and e.get("by") not in ("politica_riesgo_bajo", None):
                q["gates_humanos"] += 1; q["espera_h"] += float(e.get("delay_h") or 0)
                if e.get("dictamen_ia"):
                    hai["con_dictamen"] += 1; hai["coinciden"] += int(bool(e.get("coincide_con_ia")))
                    hai["devueltos_humano"] += int(e.get("decision") == "returned"); hai["devueltos_ia"] += int(e["dictamen_ia"] == "returned")
        elif ev == "defect_detected":
            req[r]["defectos"] += 1
        elif ev == "remediation":
            req[r]["remediaciones"] += 1
        elif ev == "pipeline_started":
            req[r]["inicio"] = req[r]["inicio"] or e["ts"]
        elif ev in ("pipeline_completed", "deployment"):
            req[r]["fin"] = e["ts"]
            if ev == "deployment":
                req[r]["estado"] = e.get("estado") or e.get("resultado")
    for (r, a), rounds in f5_by.items():
        x = ag[a]; x["evaluados"] += 1
        x["r0_ok"] += int(rounds.get(0, False))
        ok = [k for k, v in rounds.items() if v]
        x["rondas"].append(min(ok) if ok else max(rounds) + 1)
    filas = []
    for a, x in sorted(ag.items()):
        filas.append({"agente": a, "clase": x["clase"], "artefactos": x["evaluados"],
                      "aprob_r0_%": round(100 * x["r0_ok"] / x["evaluados"], 1) if x["evaluados"] else None,
                      "rondas_media": round(st.mean(x["rondas"]), 2) if x["rondas"] else None,
                      "escalamientos": x["escal"], "llamadas": x["llamadas"],
                      "tokens_out_media": round(st.mean(x["tout"])) if x["tout"] else None,
                      "latencia_s_media": round(st.mean(x["lat"]) / 1000, 1) if x["lat"] else None})
    por_clase = defaultdict(list)
    for f in filas:
        por_clase[f["clase"]].append(f)
    resumen = {c: {"agentes": len(fs), "aprob_r0_%": round(st.mean([f["aprob_r0_%"] for f in fs if f["aprob_r0_%"] is not None]), 1),
                   "escalamientos": sum(f["escalamientos"] for f in fs)} for c, fs in por_clase.items()}
    hai["concordancia_%"] = round(100 * hai["coinciden"] / hai["con_dictamen"], 1) if hai["con_dictamen"] else None
    return {"agentes": filas, "por_clase": resumen, "requerimientos": dict(req), "humano_ia": hai}


def a_markdown(res: dict) -> str:
    out = ["## Indicadores por agente", "", "| Agente | Modelo | Artefactos | Aprob. ronda 0 (%) | Rondas medias | Escalamientos | Tokens salida (media) | Latencia (s) |",
           "|---|---|---|---|---|---|---|---|"]
    for f in res["agentes"]:
        out.append(f"| {f['agente']} | {f['clase']} | {f['artefactos']} | {f['aprob_r0_%']} | {f['rondas_media']} | {f['escalamientos']} | {f['tokens_out_media']} | {f['latencia_s_media']} |")
    out += ["", "## Por clase de modelo", "", "| Clase | Agentes | Aprob. ronda 0 media (%) | Escalamientos |", "|---|---|---|---|"]
    for c, v in res["por_clase"].items():
        out.append(f"| {c} | {v['agentes']} | {v['aprob_r0_%']} | {v['escalamientos']} |")
    out += ["", "## Por requerimiento", "", "| Req. | Gates | Gates humanos | Espera humana (h) | Defectos | Remediaciones | Estado |", "|---|---|---|---|---|---|---|"]
    for r, q in sorted(res["requerimientos"].items()):
        out.append(f"| {r} | {q['gates']} | {q['gates_humanos']} | {round(q['espera_h'], 2)} | {q['defectos']} | {q['remediaciones']} | {q['estado'] or '—'} |")
    h = res["humano_ia"]
    out += ["", "## Gates humanos con dictamen de IA (opción A)", "", "| Decisiones con dictamen | Concordancia (%) | Devueltos por el humano | Devolución recomendada por IA |", "|---|---|---|---|",
            f"| {h['con_dictamen']} | {h['concordancia_%']} | {h['devueltos_humano']} | {h['devueltos_ia']} |"]
    return "\n".join(out) + "\n"


def _trazable(out: Path, req: str) -> bool:
    """H5: cada artefacto del requerimiento tiene procedencia (req_id y fase) y su decisión de governance registrada."""
    arts = [p for p in out.glob("*.json") if not p.name.endswith(".decision.json") and ".input.r" not in p.name and p.stem not in NO_ARTEFACTOS]
    if not arts:
        return False
    for a in arts:
        try:
            prov = json.loads(a.read_text(encoding="utf-8")).get("provenance") or {}
        except (json.JSONDecodeError, AttributeError):
            return False
        if prov.get("req_id") != req or not prov.get("phase") or not (out / f"{a.stem}.decision.json").exists():
            return False
    return True


def hipotesis(events: list[dict], estado_dir: Path | None, cfg: dict | None) -> dict:
    fin = datetime.combine(cfg["fin"], time(23, 59, 59), tzinfo=calendario.LIMA).isoformat() if cfg else None
    feriados = cfg.get("feriados", []) if cfg else []
    obs = (cfg or {}).get("observacion") or {}
    estados = {}
    if estado_dir and Path(estado_dir).exists():
        for d in sorted(Path(estado_dir).iterdir()):
            f = d / "output" / "estado.json"
            if f.exists():
                estados[d.name] = {"st": json.loads(f.read_text(encoding="utf-8")), "out": d / "output"}
    reqs = sorted(set(estados) | {e["req_id"] for e in events if e.get("event") == "pipeline_started" and e.get("req_id")})
    deps = defaultdict(list); post = defaultdict(list); defs = defaultdict(list); hand = defaultdict(list); agentes = defaultdict(set)
    for e in events:
        ev, r = e.get("event"), e.get("req_id")
        if ev == "deployment":
            deps[r].append(e)
        elif ev == "deployment_outcome":
            post[r].append(e)
        elif ev == "defect_detected":
            defs[r].append(e)
        elif ev == "handoff":
            hand[r].append(e)
        elif ev == "agent_completed" and e.get("agent"):
            agentes[r].add(e["agent"])
    filas, n_dep, n_fall, n_ok = [], 0, 0, 0
    for r in reqs:
        est = (estados.get(r) or {}).get("st", {})
        ent = est.get("entrada_pipeline")
        fila = {"req_id": r, "historico": r <= "SIM-P05-R027", "entrada_pipeline": ent, "go_release": est.get("go_release"),
                "deploy_ok_staging": est.get("deploy_ok_staging")}
        for k, marca in (("h1a_d", "go_release"), ("h1b_d", "deploy_ok_staging")):
            if ent and est.get(marca):
                fila[k], fila[k + "_censurado"] = calendario.dias_entre(ent, est[marca]), False
            elif ent and fin:
                fila[k], fila[k + "_censurado"] = calendario.dias_entre(ent, fin), True
            else:
                fila[k], fila[k + "_censurado"] = None, None
        resultados = []
        for d in deps[r]:
            res = d.get("resultado") or ("ok" if d.get("alcanzo_deploy") and not d.get("fallido") else "fallo_pytest")
            if res == "ok":
                hasta = d.get("observacion_hasta")
                if any(hasta is None or p["fecha"][:10] <= hasta for p in post[r]):
                    res = next(p["resultado"] for p in post[r])
            resultados.append(res)
        n_dep += len(resultados); n_fall += sum(x != "ok" for x in resultados); n_ok += sum(x == "ok" for x in resultados)
        fila["despliegues"] = len(resultados); fila["despliegues_fallidos"] = sum(x != "ok" for x in resultados)
        fila["resultado_despliegue"] = resultados[-1] if resultados else None
        # defectos escapados dentro de su ventana: 5 días hábiles desde el despliegue o hasta el fin del piloto
        base = next((d["fecha"][:10] for d in deps[r] if d.get("fecha")), None)
        limite = None
        if base:
            limite = calendario.sumar_dias_habiles(date.fromisoformat(base), obs.get("defecto_escapado_dias_habiles", 5), feriados)
            if cfg:
                limite = min(limite, cfg["fin"])
        esc = [d for d in defs[r] if d.get("deteccion") == "escapado" and (limite is None or d["fecha"][:10] <= limite.isoformat())]
        fila["defectos_escapados"] = len(esc); fila["defectos_pre_gate"] = sum(1 for d in defs[r] if d.get("deteccion", "pre_gate") == "pre_gate")
        fila["con_escapado"] = int(bool(esc)); fila["con_defecto"] = int(bool(esc) or fila["defectos_pre_gate"] > 0)
        fila["trazable"] = int(_trazable(estados[r]["out"], r)) if r in estados else None
        h = hand[r]
        fila["handoffs"] = len(h); fila["handoffs_auto"] = sum(1 for x in h if x.get("mode") == "auto")
        destinos = {x.get("to") for x in h}
        fila["agentes"] = len(agentes[r]); fila["agentes_con_transicion"] = len(agentes[r] & destinos)
        filas.append(fila)
    n = len(filas) or 1
    dias_exp = (cfg["fin"] - cfg["inicio"]).days + 1 if cfg else None
    h1a = [f["h1a_d"] for f in filas if f["h1a_d"] is not None and not f["h1a_d_censurado"]]
    h1b = [f["h1b_d"] for f in filas if f["h1b_d"] is not None and not f["h1b_d_censurado"]]
    tot_h = sum(f["handoffs"] for f in filas); tot_ag = sum(f["agentes"] for f in filas)
    resumen = {
        "requerimientos": len(filas),
        "H1a_mediana_d": round(st.median(h1a), 2) if h1a else None, "H1a_censurados": sum(1 for f in filas if f["h1a_d_censurado"]),
        "H1b_mediana_d": round(st.median(h1b), 2) if h1b else None, "H1b_censurados": sum(1 for f in filas if f["h1b_d_censurado"]),
        "H2_fallidos": n_fall, "H2_despliegues": n_dep, "H2_%": round(100 * n_fall / n_dep, 1) if n_dep else None,
        "H3_con_escapado": sum(f["con_escapado"] for f in filas), "H3_%": round(100 * sum(f["con_escapado"] for f in filas) / n, 1),
        "H3p_con_defecto": sum(f["con_defecto"] for f in filas), "H3p_%": round(100 * sum(f["con_defecto"] for f in filas) / n, 1),
        "H4_exitosos": n_ok, "H4_dias_exposicion": dias_exp, "H4_por_mes": round(n_ok / (dias_exp / 30), 2) if dias_exp else None,
        "H5_trazables": sum(f["trazable"] or 0 for f in filas), "H5_%": round(100 * sum(f["trazable"] or 0 for f in filas) / n, 1),
        "H6_auto_%": round(100 * sum(f["handoffs_auto"] for f in filas) / tot_h, 1) if tot_h else None,
        "H6_registradas_%": round(100 * sum(f["agentes_con_transicion"] for f in filas) / tot_ag, 1) if tot_ag else None,
    }
    return {"filas": filas, "resumen": resumen}


def hipotesis_md(h: dict) -> str:
    r = h["resumen"]
    out = ["## Hipótesis del piloto (protocolo v2)", "", "| Indicador | Valor | Detalle |", "|---|---|---|",
           f"| H1a · lead time hasta go_release (mediana, d) | {r['H1a_mediana_d']} | {r['H1a_censurados']} casos censurados al cierre |",
           f"| H1b · lead time hasta deploy_ok_staging (mediana, d) | {r['H1b_mediana_d']} | {r['H1b_censurados']} casos censurados |",
           f"| H2 · despliegues fallidos (%) | {r['H2_%']} | {r['H2_fallidos']} de {r['H2_despliegues']} |",
           f"| H3 · requerimientos con defecto escapado (%) | {r['H3_%']} | {r['H3_con_escapado']} de {r['requerimientos']} |",
           f"| H3′ · requerimientos con algún defecto (%) | {r['H3p_%']} | {r['H3p_con_defecto']} de {r['requerimientos']} |",
           f"| H4 · despliegues exitosos por mes (descriptivo) | {r['H4_por_mes']} | {r['H4_exitosos']} en {r['H4_dias_exposicion']} días |",
           f"| H5 · trazabilidad completa (%) | {r['H5_%']} | {r['H5_trazables']} de {r['requerimientos']} |",
           f"| H6 · handoffs automáticos (%) · transiciones registradas (%) | {r['H6_auto_%']} · {r['H6_registradas_%']} | |"]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("telemetria", nargs="+"); ap.add_argument("--md"); ap.add_argument("--csv")
    ap.add_argument("--estado", help="carpeta piloto/<piloto>/estado descargada del Hub"); ap.add_argument("--piloto", help="nombre en config/piloto.yaml")
    ap.add_argument("--csv-req", help="CSV por requerimiento para scripts/contraste.py")
    a = ap.parse_args()
    eventos = list(cargar(a.telemetria))
    res = calcular(eventos)
    md = a_markdown(res)
    if a.estado or a.piloto:
        hip = hipotesis(eventos, Path(a.estado) if a.estado else None, calendario.config(a.piloto) if a.piloto else None)
        md += "\n" + hipotesis_md(hip)
        if a.csv_req:
            with open(a.csv_req, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(hip["filas"][0])); w.writeheader(); w.writerows(hip["filas"])
    print(md)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(res["agentes"][0])); w.writeheader(); w.writerows(res["agentes"])
