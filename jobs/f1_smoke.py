# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "torch", "transformers>=4.51,<4.57", "accelerate", "bitsandbytes",
#   "outlines==0.1.11", "datasets", "jsonschema", "PyYAML", "huggingface_hub",
# ]
# ///
"""F1-smoke: vertical Discovery con Qwen3-8B (hf_local) sobre 1 requerimiento, en HF Jobs.
Descarga el código de la rama indicada, ejecuta el pipeline y sube telemetría y salidas al Hub."""
import io, os, subprocess, sys, tarfile, urllib.request
from huggingface_hub import HfApi

BRANCH = os.environ.get("BRANCH", "f1-discovery")
REQ = os.environ.get("REQ", "SIM-P05-R001")
RUNS_REPO = os.environ["RUNS_REPO"]                       # dataset privado, p. ej. usuario/tesis-runs
RUN_NAME = os.environ.get("RUN_NAME", "f1_smoke")

url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(url).read())).extractall("/tmp", filter="data")
root = f"/tmp/tesis-{BRANCH}"
os.chdir(root)
env = dict(os.environ, PIPELINE_PROVIDER="hf_local")
tel = f"telemetry/{RUN_NAME}.jsonl"
r = subprocess.run([sys.executable, "scripts/run_pipeline.py", "--req", REQ, "--telemetry", tel], env=env)

api = HfApi()
dest = f"runs/{RUN_NAME}/{os.environ.get('JOB_ID', 'local')}"
if os.path.exists(tel):
    api.upload_file(path_or_fileobj=tel, path_in_repo=f"{dest}/telemetria.jsonl", repo_id=RUNS_REPO, repo_type="dataset")
out = f"data/requerimientos/{REQ}/output"
if os.path.isdir(out):
    api.upload_folder(folder_path=out, path_in_repo=f"{dest}/output", repo_id=RUNS_REPO, repo_type="dataset")
print("exit:", r.returncode, "| subido a", RUNS_REPO, dest)
sys.exit(r.returncode)
