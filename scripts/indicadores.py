"""Indicadores del piloto para la tesis, calculados solo desde la telemetría (eventos JSONL) y el estado publicado.

Agrupa cada agente por la clase de modelo que lo atendió, para que la tesis pueda contrastar
los agentes especializados (QLoRA, F3) con los no entrenados:
  - lora    : Qwen3-8B + adaptador QLoRA del agente (model_id = nombre del agente)
  - base    : Qwen3-8B sin adaptar
  - maestro : Qwen3-32B-AWQ (D-F4-1 opción C: backend, QA, code-review)

Uso:  python scripts/indicadores.py telemetria/*.jsonl [--md salida.md] [--csv salida.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from collections import defaultdict
from pathlib import Path


def clase(model_id: str | None, agent: str) -> str:
    if not model_id:
        return "determinista"
    if model_id == agent:
        return "lora"
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("telemetria", nargs="+"); ap.add_argument("--md"); ap.add_argument("--csv")
    a = ap.parse_args()
    res = calcular(list(cargar(a.telemetria)))
    md = a_markdown(res); print(md)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(res["agentes"][0])); w.writeheader(); w.writerows(res["agentes"])
