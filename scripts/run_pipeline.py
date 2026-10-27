#!/usr/bin/env python3
"""Ejecuta el vertical Discovery para uno o varios requerimientos.

  PIPELINE_PROVIDER=mock      python scripts/run_pipeline.py --req SIM-P05-R001
  PIPELINE_PROVIDER=hf_local  python scripts/run_pipeline.py --all
  PIPELINE_PROVIDER=anthropic python scripts/run_pipeline.py --req SIM-P05-R001   # solo pruebas internas
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.orchestrator import Orchestrator          # noqa: E402
from core.telemetry import Telemetry                 # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--req", action="append", help="id de requerimiento (repetible)")
ap.add_argument("--all", action="store_true", help="todos los requerimientos en data/requerimientos")
ap.add_argument("--seed", type=int, default=2026)
ap.add_argument("--telemetry", default="telemetry/eventos.jsonl")
a = ap.parse_args()

reqs = a.req or []
if a.all:
    reqs = sorted(p.name for p in (ROOT / "data/requerimientos").iterdir() if (p / "input").exists())
if not reqs:
    ap.error("indica --req <id> o --all")

tel = Telemetry(ROOT / a.telemetry)
orch = Orchestrator(ROOT, tel, seed=a.seed)
summary = []
for r in reqs:
    try:
        ctx = orch.run(r)
        summary.append({"req_id": r, "ok": True, "artefacts": [k for k in ("user_story_set", "domain_model", "ux_spec") if k in ctx]})
    except Exception as e:  # noqa: BLE001
        summary.append({"req_id": r, "ok": False, "error": str(e)[:200]})
        tel.emit(event="pipeline_failed", req_id=r, error=str(e)[:300])
print(json.dumps({"run_id": tel.run_id, "resultados": summary}, ensure_ascii=False, indent=1))
sys.exit(0 if all(s["ok"] for s in summary) else 1)
