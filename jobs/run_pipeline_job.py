# /// script
# requires-python = ">=3.11"
# dependencies = ["vllm==0.34.0", "xgrammar==0.2.8", "huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML", "fastapi", "httpx", "uvicorn", "ruff", "bandit", "pytest"]
# ///
"""Corrida (o reanudación) del pipeline de 16 agentes sobre uno o varios requerimientos, en HF Jobs.

- Sirve Qwen3-8B con vLLM y sus 5 adaptadores LoRA (un módulo por agente entrenable).
- Restaura el estado del piloto desde el Hub (artefactos, decisiones, aprobaciones humanas), ejecuta hasta el
  siguiente gate pendiente o hasta el despliegue, y vuelve a publicar el estado y la telemetría.
Variables: BRANCH, PILOT (nombre del piloto), REQS (coma) o ALL=1, RUNS_REPO, ADAPTERS ('agente=repo ...'),
           TODAY (AAAA-MM-DD, opcional; por defecto la fecha de Lima), DEPLOY_REPO (opcional), WORKERS.
Protocolo F5 v2: si PILOT está en config/piloto.yaml (p. ej. piloto1), el orquestador usa su calendario (días de release
y feriados). Para el piloto real, RUNS_REPO apunta al dataset privado <usuario>/tesis-piloto."""
import io, json, os, subprocess, sys, tarfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "main"); PILOT = os.environ["PILOT"]; RUNS = os.environ["RUNS_REPO"]
BASE = os.environ.get("BASE", "Qwen/Qwen3-8B"); WORKERS = int(os.environ.get("WORKERS", "8"))
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(url).read())).extractall("/tmp", filter="data")
ROOT = Path(f"/tmp/tesis-{BRANCH.replace('/', '-')}"); os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from core.envinfo import report as _entorno  # noqa: E402
ENTORNO = _entorno({"job": os.environ.get("JOB_ID", "local"), "branch": BRANCH})
from huggingface_hub import HfApi, snapshot_download   # noqa: E402
api = HfApi()
reqs = sorted(p.name for p in (ROOT / "data/requerimientos").iterdir() if (p / "input").exists()) if os.environ.get("ALL") == "1" else os.environ["REQS"].split(",")

# 1) estado previo del piloto
try:
    st = Path(snapshot_download(RUNS, repo_type="dataset", allow_patterns=[f"piloto/{PILOT}/estado/**"]))
    for r in reqs:
        src = st / "piloto" / PILOT / "estado" / r
        if src.exists():
            subprocess.run(["cp", "-rL", f"{src}/output", str(ROOT / "data/requerimientos" / r)], check=False)
except Exception as e:  # noqa: BLE001
    print("sin estado previo:", str(e)[:120])

# 2) vLLM con el modelo base y los adaptadores
mods = [f"{a}={snapshot_download(repo)}" for a, repo in (x.split("=") for x in os.environ.get("ADAPTERS", "").split())]
TEACHER = os.environ.get("TEACHER_MODEL", "Qwen/Qwen3-32B-AWQ")   # D-F4-1 C; TEACHER_MODEL=none lo desactiva
MODE_T = os.environ.get("TEACHER_MODE", "auto")                    # auto: solo si algún requerimiento ya llegó al diseño de API
USE_T = TEACHER.lower() != "none" and (MODE_T == "always" or any((ROOT / "data/requerimientos" / r / "output" / "api_design.json").exists() for r in reqs))
if not USE_T:   # los agentes del maestro se difieren a la próxima ventana; nunca se sustituye el modelo
    os.environ["PROVIDERS_DOWN"] = "vllm_teacher"
print("maestro:", "sí" if USE_T else "no (diferido)", flush=True)
cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", BASE, "--port", "8000", "--max-model-len", "28000",
       "--gpu-memory-utilization", "0.36" if USE_T else "0.90", "--max-num-seqs", "32"]
if mods:
    cmd += ["--enable-lora", "--max-lora-rank", "64", "--max-loras", str(len(mods)), "--lora-modules", *mods]
srv = subprocess.Popen(cmd, stdout=open("/tmp/vllm.log", "w"), stderr=subprocess.STDOUT)
for _ in range(180):
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=5); break
    except Exception:  # noqa: BLE001
        if srv.poll() is not None:
            print(open("/tmp/vllm.log").read()[-4000:]); sys.exit("vLLM no arrancó")
        time.sleep(10)
print("vLLM listo con", len(mods), "adaptadores", flush=True)
if USE_T:   # segundo servidor: maestro para backend / QA / code-review (config/providers.yaml → vllm_teacher)
    tsrv = subprocess.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", TEACHER, "--port", "8001",
                             "--max-model-len", "28000", "--gpu-memory-utilization", "0.54", "--max-num-seqs", "16"],
                            stdout=open("/tmp/vllm_t.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(180):
        try:
            urllib.request.urlopen("http://localhost:8001/health", timeout=5); break
        except Exception:  # noqa: BLE001
            if tsrv.poll() is not None:
                print(open("/tmp/vllm_t.log").read()[-4000:]); sys.exit("vLLM maestro no arrancó")
            time.sleep(10)
    print("vLLM maestro listo:", TEACHER, flush=True)
os.environ["PIPELINE_PROVIDER"] = "vllm_local"

from core.orchestrator import Orchestrator   # noqa: E402
from core.telemetry import Telemetry         # noqa: E402
job = os.environ.get("JOB_ID", "local"); tel_dir = Path("/tmp/tel"); tel_dir.mkdir(exist_ok=True)
resumen = {}


def one(r):
    try:
        ctx = Orchestrator(ROOT, Telemetry(tel_dir / f"{r}.jsonl", run_id=job), today=os.environ.get("TODAY")).run(r)
        resumen[r] = ctx.get("_estado")
    except Exception as e:  # noqa: BLE001
        resumen[r] = f"error: {str(e)[:200]}"
    print(r, "→", resumen[r], flush=True)


with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    list(ex.map(one, reqs))

# 3) publicar estado y telemetría
for r in reqs:
    out = ROOT / "data/requerimientos" / r / "output"
    if out.exists():
        api.upload_folder(folder_path=str(out), path_in_repo=f"piloto/{PILOT}/estado/{r}/output", repo_id=RUNS, repo_type="dataset",
                          commit_message=f"{PILOT} {r} {resumen.get(r)}")
allt = Path("/tmp/tel_all.jsonl"); allt.write_text("".join(p.read_text() for p in tel_dir.glob("*.jsonl")), encoding="utf-8")
api.upload_file(path_or_fileobj=str(allt), path_in_repo=f"piloto/{PILOT}/telemetria/{job}.jsonl", repo_id=RUNS, repo_type="dataset")
print("RESUMEN", json.dumps(resumen, ensure_ascii=False, indent=1))
srv.terminate()
