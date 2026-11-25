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
_auth = {"Authorization": "token " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}  # repo privado desde el 23/11/2026
_tar = tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=_auth)).read())); _tar.extractall("/tmp", filter="data")
ROOT = Path("/tmp") / _tar.getnames()[0].split("/")[0]; os.chdir(ROOT); sys.path.insert(0, str(ROOT))  # nombre real de la carpeta (GitHub quita la 'v' inicial de ramas como v2-*)
from core.envinfo import report as _entorno  # noqa: E402
ENTORNO = _entorno({"job": os.environ.get("JOB_ID", "local"), "branch": BRANCH})
from huggingface_hub import HfApi, snapshot_download   # noqa: E402
api = HfApi()
PREP = os.environ.get("PREPARAR_EVAL")          # v2 · eval_n3: genera N requerimientos SIM-E0x con el maestro antes de correr
reqs = sorted(p.name for p in (ROOT / "data/requerimientos").iterdir() if (p / "input").exists()) if os.environ.get("ALL") == "1" \
    else [] if PREP else os.environ["REQS"].split(",")

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
def _rev(repo: str) -> str:
    try:
        return f"{repo}@{api.model_info(repo).sha}"
    except Exception:  # noqa: BLE001
        return f"{repo}@?"


_pares = [x.split("=") for x in os.environ.get("ADAPTERS", "").split()]
mods = [f"{a}={snapshot_download(repo)}" for a, repo in _pares]
TEACHER = os.environ.get("TEACHER_MODEL", "Qwen/Qwen3-32B-AWQ")   # D-F4-1 C; TEACHER_MODEL=none lo desactiva
# G5: con puertas manuales el maestro siempre se carga, porque genera el dictamen IA de cada puerta
# G2: revisiones exactas de modelos y adaptadores; el orquestador las graba en cada <artefacto>.input.r<n>.json
REVS = {"base": _rev(BASE), "modelos": {BASE: _rev(BASE), **({TEACHER: _rev(TEACHER)} if TEACHER.lower() != "none" else {})},
        "loras": {a: _rev(repo) for a, repo in _pares}}
from core.registry import Registry as _Reg   # noqa: E402
for _m in _Reg(ROOT).modelos_hf():          # v2 (D-P5): modelos de HF Inference Providers que usa el router por nivel
    REVS["modelos"][_m] = _rev(_m.split(":")[0]) + f" vía {_m.split(':')[1] if ':' in _m else 'auto'}"
os.environ["MODEL_REVS"] = json.dumps(REVS)
ENTORNO["modelos"] = REVS
print("MODELOS", json.dumps(REVS, ensure_ascii=False), flush=True)
MODE_T = os.environ.get("TEACHER_MODE", "auto")                    # auto: solo si algún requerimiento ya llegó al diseño de API
def _devolucion_pendiente(r: str) -> bool:
    """D-E1: hay una devolución humana de la versión pendiente, así que la corrección la hará el maestro."""
    out = ROOT / "data/requerimientos" / r / "output"
    for a in (out / "aprobaciones").glob("*.json") if (out / "aprobaciones").exists() else []:
        d = json.loads(a.read_text(encoding="utf-8")); p = out / "pendientes" / a.name
        if d.get("decision") == "returned" and p.exists() and json.loads(p.read_text(encoding="utf-8")).get("hash") == d.get("hash"):
            return True
    return False


USE_T = TEACHER.lower() != "none" and (MODE_T == "always" or bool(PREP) or os.environ.get("GATES_MODE") == "manual" or any((ROOT / "data/requerimientos" / r / "output" / "api_design.json").exists()
                                                                 or _devolucion_pendiente(r) for r in reqs))
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
if PREP:
    _p = subprocess.run([sys.executable, "scripts/eval_n3/preparar_brs.py", "--n", PREP, "--modelo", TEACHER], capture_output=True, text=True)
    reqs = [x for x in _p.stdout.split() if x.startswith("SIM-E")]
    print("eval_n3: requerimientos preparados", len(reqs), _p.stderr[-800:], flush=True)
os.environ["PIPELINE_PROVIDER"] = "vllm_local"

from core.orchestrator import Orchestrator   # noqa: E402
from core.telemetry import Telemetry         # noqa: E402
job = os.environ.get("JOB_ID", "local"); tel_dir = Path("/tmp/tel"); tel_dir.mkdir(exist_ok=True)
resumen = {}


import threading                              # noqa: E402
_LOCK = threading.Lock()                      # commits al dataset en serie (los hilos de requerimientos terminan en paralelo)


def _publicar(r: str) -> None:
    out = ROOT / "data/requerimientos" / r / "output"
    if PREP and (out.parent / "input").exists():   # eval_n3: los requerimientos se generan en el job; se guarda su entrada
        with _LOCK:
            api.upload_folder(folder_path=str(out.parent / "input"), path_in_repo=f"piloto/{PILOT}/estado/{r}/input", repo_id=RUNS,
                              repo_type="dataset", commit_message=f"{PILOT} {r} input")
    if out.exists():
        with _LOCK:
            api.upload_folder(folder_path=str(out), path_in_repo=f"piloto/{PILOT}/estado/{r}/output", repo_id=RUNS, repo_type="dataset",
                              commit_message=f"{PILOT} {r} {resumen.get(r)}")


def one(r):
    try:
        ctx = Orchestrator(ROOT, Telemetry(tel_dir / f"{r}.jsonl", run_id=job), today=os.environ.get("TODAY")).run(r)
        resumen[r] = ctx.get("_estado")
    except Exception as e:  # noqa: BLE001
        resumen[r] = f"error: {str(e)[:200]}"
    print(r, "→", resumen[r], flush=True)
    try:        # G3: el estado de cada requerimiento se publica apenas se detiene (gate pendiente, error o fin), sin esperar a los demás
        _publicar(r)
    except Exception as e:  # noqa: BLE001
        print("no se pudo publicar", r, str(e)[:160], flush=True)


with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    list(ex.map(one, reqs))

# 3) publicar estado y telemetría
ent = Path("/tmp/entorno.json"); ent.write_text(json.dumps(ENTORNO, ensure_ascii=False, indent=1), encoding="utf-8")
api.upload_file(path_or_fileobj=str(ent), path_in_repo=f"piloto/{PILOT}/entornos/{job}.json", repo_id=RUNS, repo_type="dataset")
allt = Path("/tmp/tel_all.jsonl"); allt.write_text("".join(p.read_text() for p in tel_dir.glob("*.jsonl")), encoding="utf-8")
api.upload_file(path_or_fileobj=str(allt), path_in_repo=f"piloto/{PILOT}/telemetria/{job}.jsonl", repo_id=RUNS, repo_type="dataset")
print("RESUMEN", json.dumps(resumen, ensure_ascii=False, indent=1))
srv.terminate()
