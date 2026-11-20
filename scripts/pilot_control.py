#!/usr/bin/env python3
"""Control del piloto desde el chat del proyecto: listar gates pendientes y registrar decisiones humanas
(aprobar/devolver) con timestamp real en el Hub, para que la siguiente corrida las lea.

  python scripts/pilot_control.py pendientes --pilot humo16
  python scripts/pilot_control.py decidir --pilot humo16 --req SIM-P05-R001 --artefacto user_story_set --decision approved [--motivo "..."]
  python scripts/pilot_control.py estado --pilot humo16
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

RUNS = os.environ.get("RUNS_REPO") or f"{os.environ['HF_USERNAME']}/tesis-runs"


def _state(pilot):
    return Path(snapshot_download(RUNS, repo_type="dataset", allow_patterns=[f"piloto/{pilot}/estado/**"], force_download=True)) / "piloto" / pilot / "estado"


def pendientes(a):
    base = _state(a.pilot); res = []
    for req in sorted(p.name for p in base.iterdir()) if base.exists() else []:
        out = base / req / "output"
        for p in sorted((out / "pendientes").glob("*.json")) if (out / "pendientes").exists() else []:
            pend = json.loads(p.read_text(encoding="utf-8"))
            ap = out / "aprobaciones" / p.name
            if ap.exists() and json.loads(ap.read_text(encoding="utf-8")).get("hash") == pend["hash"]:
                continue
            art = json.loads((out / f"{p.stem}.json").read_text(encoding="utf-8"))
            res.append({"req": req, "artefacto": p.stem, "rol": pend["rol"], "hash": pend["hash"], "solicitado": pend["solicitado"],
                        "hallazgos_governance": pend.get("hallazgos_governance", []), "contenido": art})
    print(json.dumps(res, ensure_ascii=False, indent=1))


def decidir(a):
    base = _state(a.pilot); out = base / a.req / "output"
    pend = json.loads((out / "pendientes" / f"{a.artefacto}.json").read_text(encoding="utf-8"))
    rec = {"decision": a.decision, "motivo": a.motivo or "", "por": a.por, "rol": pend["rol"], "hash": pend["hash"],
           "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    HfApi().upload_file(path_or_fileobj=json.dumps(rec, ensure_ascii=False, indent=1).encode(), repo_id=RUNS, repo_type="dataset",
                        path_in_repo=f"piloto/{a.pilot}/estado/{a.req}/output/aprobaciones/{a.artefacto}.json",
                        commit_message=f"{a.pilot} {a.req} {a.artefacto} {a.decision}")
    print(json.dumps(rec, ensure_ascii=False))


def estado(a):
    base = _state(a.pilot)
    for req in sorted(p.name for p in base.iterdir()) if base.exists() else []:
        f = base / req / "output" / "estado.json"
        print(req, json.loads(f.read_text(encoding="utf-8")) if f.exists() else "-")


ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
for n in ("pendientes", "estado"):
    x = sp.add_parser(n); x.add_argument("--pilot", required=True)
x = sp.add_parser("decidir"); x.add_argument("--pilot", required=True); x.add_argument("--req", required=True); x.add_argument("--artefacto", required=True)
x.add_argument("--decision", choices=["approved", "returned"], required=True); x.add_argument("--motivo"); x.add_argument("--por", default="Javier Rosado")
a = ap.parse_args(); {"pendientes": pendientes, "decidir": decidir, "estado": estado}[a.cmd](a)
