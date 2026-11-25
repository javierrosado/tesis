# /// script
# requires-python = ">=3.11"
# dependencies = ["vllm==0.34.0", "xgrammar==0.2.8", "huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML"]
# ///
"""Ejecuta el pipeline sobre uno o varios requerimientos con un modelo open-weight servido por vLLM
dentro del job (sin API keys). Es el ejecutor de las pruebas de humo y del piloto.
Variables: BRANCH, MODEL, PROVIDER (vllm_local), REQS (coma) o ALL=1, RUNS_REPO, RUN_NAME, LORA_MODULES (opcional)."""
import io, os, subprocess, sys, tarfile, time, urllib.request
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "main"); MODEL = os.environ.get("MODEL", "Qwen/Qwen3-8B")
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
_auth = {"Authorization": "token " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}  # repo privado desde el 23/11/2026
_tar = tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=_auth)).read())); _tar.extractall("/tmp", filter="data")
ROOT = Path("/tmp") / _tar.getnames()[0].split("/")[0]; os.chdir(ROOT)  # nombre real de la carpeta (GitHub quita la 'v' inicial de ramas como v2-*)
cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", MODEL, "--port", "8000",
       "--max-model-len", "24000", "--gpu-memory-utilization", "0.90"]
if os.environ.get("LORA_MODULES"):
    cmd += ["--enable-lora", "--max-lora-rank", "64", "--lora-modules", *os.environ["LORA_MODULES"].split()]
srv = subprocess.Popen(cmd, stdout=open("/tmp/vllm.log", "w"), stderr=subprocess.STDOUT)
for _ in range(180):
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=5); break
    except Exception:  # noqa: BLE001
        if srv.poll() is not None:
            print(open("/tmp/vllm.log").read()[-4000:]); sys.exit("vLLM no arrancó")
        time.sleep(10)
print("vLLM listo:", MODEL, flush=True)
tel = f"telemetry/{os.environ.get('RUN_NAME', 'run')}.jsonl"
args = ["--all"] if os.environ.get("ALL") == "1" else sum((["--req", r] for r in os.environ["REQS"].split(",")), [])
env = dict(os.environ, PIPELINE_PROVIDER=os.environ.get("PROVIDER", "vllm_local"))
r = subprocess.run([sys.executable, "scripts/run_pipeline.py", *args, "--telemetry", tel], env=env)
from huggingface_hub import HfApi   # noqa: E402
api = HfApi(); dest = f"runs/{os.environ.get('RUN_NAME', 'run')}/{os.environ.get('JOB_ID', 'local')}"
if os.path.exists(tel):
    api.upload_file(path_or_fileobj=tel, path_in_repo=f"{dest}/telemetria.jsonl", repo_id=os.environ["RUNS_REPO"], repo_type="dataset")
for d in sorted((ROOT / "data/requerimientos").glob("*/output")):
    if any(d.glob("*.json")):
        api.upload_folder(folder_path=str(d), path_in_repo=f"{dest}/{d.parent.name}", repo_id=os.environ["RUNS_REPO"], repo_type="dataset", allow_patterns=["*.json", "*.yaml"])
if r.returncode:
    print("--- vllm.log (cola) ---\n" + open("/tmp/vllm.log").read()[-3000:])
srv.terminate(); print("exit:", r.returncode); sys.exit(r.returncode)
