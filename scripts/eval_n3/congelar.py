#!/usr/bin/env python3
"""eval_n3 · paso 2: congela las entradas exactas de cada agente N3 a partir de la corrida del pipeline v1 (modo automático).

Para cada requerimiento SIM-E0x se cargan los artefactos aprobados y se reconstruye, con el mismo código del orquestador
(Orchestrator._payload), el payload que recibe cada agente N3. Solo se congela la entrada de un agente si todos los artefactos
que consume quedaron aprobados por governance (decision.json con veredicto aprobado).

  python scripts/eval_n3/congelar.py --estado <carpeta con <req>/output> --salida /tmp/eval_n3/casos
"""
import argparse, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.orchestrator import ARTEFACT_NAME, Orchestrator   # noqa: E402
from core.telemetry import Telemetry                        # noqa: E402

N3 = ["solution-architect-agent", "security-compliance-agent", "data-model-agent", "backend-developer-agent"]
# code-review se arma en sembrar.py (necesita el servicio con defectos)
CONSERVAR = ["api_design", "data_model", "qa_suite", "test_cases", "solution_architecture", "user_story_set", "domain_model", "ux_spec"]


def _aprobado(out: Path, art: str) -> bool:
    d = out / f"{art}.decision.json"
    if not (out / f"{art}.json").exists() or not d.exists():
        return False
    g = json.loads(d.read_text(encoding="utf-8")).get("gate", {})
    return g.get("decision") in ("approved", None)


def congelar(estado: Path, salida: Path) -> dict:
    orch = Orchestrator(ROOT, Telemetry(Path("/tmp/congelar.jsonl"), echo=False), today="2026-11-25")
    nodes = {n["agent"]: n for st in orch.reg.dag["stages"] for n in (st.get("parallel") or [st]) if n.get("agent")}
    stage_art = {n["id"]: ARTEFACT_NAME[n["agent"]] for n in nodes.values()}
    resumen = {}
    for req in sorted(p.name for p in estado.iterdir() if (p / "output").exists()):
        out = estado / req / "output"
        ctx = {"req_id": req}
        for art in set(ARTEFACT_NAME.values()):
            if _aprobado(out, art):
                ctx[art] = json.loads((out / f"{art}.json").read_text(encoding="utf-8"))
        dest = salida / req; (dest / "entradas").mkdir(parents=True, exist_ok=True)
        hechos = []
        for ag in N3:
            n = nodes[ag]
            necesita = [stage_art[i] for i in n.get("inputs", []) if i in stage_art]
            if ag == "backend-developer-agent":
                necesita = ["api_design", "data_model"]
            if not all(a in ctx for a in necesita):
                continue
            payload = orch._payload(n, ctx, stage_art)
            (dest / "entradas" / f"{ag}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            hechos.append(ag)
        for art in CONSERVAR:
            if art in ctx:
                (dest / "pipeline_v1").mkdir(exist_ok=True)
                (dest / "pipeline_v1" / f"{art}.json").write_text(json.dumps(ctx[art], ensure_ascii=False, indent=1), encoding="utf-8")
        br = (ROOT / "data/requerimientos" / req / "input")
        caso = {"req_id": req, "entradas": hechos,
                "sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((dest / "entradas").glob("*.json"))},
                "input_requerimiento": str(br) if br.exists() else None}
        (dest / "caso.json").write_text(json.dumps(caso, ensure_ascii=False, indent=1), encoding="utf-8")
        resumen[req] = hechos
    return resumen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estado", required=True); ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    r = congelar(Path(a.estado), Path(a.salida))
    tot = {ag: sum(ag in v for v in r.values()) for ag in N3}
    print(json.dumps({"casos": len(r), "entradas_por_agente": tot}, ensure_ascii=False))


if __name__ == "__main__":
    main()
