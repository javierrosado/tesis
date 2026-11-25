#!/usr/bin/env python3
"""Publica la consola del piloto (space/) en un HF Docker Space privado.

  python scripts/publicar_space.py --space jrosado1974/consola-piloto [--secrets]

Sube solo lo que la consola necesita (space/, core/, config/, contracts/, agents/, scripts/, el job del pipeline, el checklist
y el MANIFEST). Nunca sube data/ ni secretos en archivos: HF_TOKEN y GITHUB_TOKEN van como secrets del Space (--secrets los
toma del entorno, cargado con scripts/load_env.sh). Recomendado: un HF_TOKEN de permisos finos (Jobs + tesis-piloto).
"""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
INCLUIR = ["space", "core", "config", "contracts", "agents", "scripts", "jobs/run_pipeline_job.py",
           "docs/checklists_gates.md", "runs/MANIFEST.md"]
IGNORAR = shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", "*.patch")

ap = argparse.ArgumentParser()
ap.add_argument("--space", default="jrosado1974/consola-piloto")
ap.add_argument("--secrets", action="store_true", help="registra HF_TOKEN y GITHUB_TOKEN del entorno como secrets del Space")
ap.add_argument("--tag", help="tag congelado que usará el job (CONSOLA_TAG)")
a = ap.parse_args()

api = HfApi()
variables = {"PILOT": "piloto1", "RUNS_REPO": "jrosado1974/tesis-piloto", "CONSOLA_FLAVOR": "a100-large",
             "CONSOLA_USUARIOS": json.dumps({"jrosado1974": ["operador", "registrador", "aprobador"]})}
if a.tag:
    variables["CONSOLA_TAG"] = a.tag
api.create_repo(a.space, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
for k, v in variables.items():
    api.add_space_variable(a.space, k, v)
if a.secrets:
    for k in ("HF_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(k):
            api.add_space_secret(a.space, k, os.environ[k])

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    for rel in INCLUIR:
        src = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, d / rel, ignore=IGNORAR)
        elif src.exists():
            (d / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, d / rel)
    shutil.copy2(ROOT / "space/Dockerfile", d / "Dockerfile")       # el Space exige Dockerfile y README en la raíz
    shutil.copy2(ROOT / "space/README.md", d / "README.md")
    info = api.upload_folder(folder_path=str(d), repo_id=a.space, repo_type="space", commit_message="consola: publicación",
                             delete_patterns=["*"])
print(json.dumps({"space": a.space, "url": f"https://huggingface.co/spaces/{a.space}", "commit": getattr(info, "oid", None)}))
