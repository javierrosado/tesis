# /// script
# requires-python = ">=3.11"
# dependencies = ["vllm==0.34.0", "xgrammar==0.2.8", "huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML"]
# ///
"""F3 · Evaluación en la partición test: modelo base (Qwen3-8B) vs. su adaptador LoRA por agente.
Una sola generación por ejemplo (sin reintentos ni feedback) para medir la calidad en primera pasada:
contrato válido, aprobación de governance en la ronda 0 y métricas F5. Servido con vLLM multi-LoRA.
Variables: SFT_REPO, ADAPTERS ('agente=repo' separados por espacio), RUNS_REPO, BRANCH."""
import io, json, os, statistics, subprocess, sys, tarfile, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "f3-qlora"); BASE = os.environ.get("BASE", "Qwen/Qwen3-8B")
ADAPTERS = dict(x.split("=") for x in os.environ["ADAPTERS"].split())
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
_auth = {"Authorization": "token " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}  # repo privado desde el 23/11/2026
tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=_auth)).read())).extractall("/tmp", filter="data")
ROOT = Path(f"/tmp/tesis-{BRANCH.replace('/', '-')}"); os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from core.envinfo import report as _entorno  # noqa: E402
ENTORNO = _entorno({"job": os.environ.get("JOB_ID", "local"), "branch": BRANCH})
from huggingface_hub import snapshot_download, HfApi   # noqa: E402
mods = []
for ag, repo in ADAPTERS.items():
    mods.append(f"{ag}={snapshot_download(repo)}")
srv = subprocess.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", BASE, "--port", "8000", "--max-model-len", "16384",
                        "--gpu-memory-utilization", "0.90", "--enable-lora", "--max-lora-rank", "64", "--max-loras", "5", "--lora-modules", *mods],
                       stdout=open("/tmp/vllm.log", "w"), stderr=subprocess.STDOUT)
for _ in range(180):
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=5); break
    except Exception:  # noqa: BLE001
        if srv.poll() is not None:
            print(open("/tmp/vllm.log").read()[-4000:]); sys.exit("vLLM no arrancó")
        time.sleep(10)
print("vLLM listo", flush=True)
import jsonschema                                       # noqa: E402
from core.registry import Registry                     # noqa: E402
from core.adapters.openai_compat import OpenAICompatAdapter   # noqa: E402
from core.orchestrator import Orchestrator             # noqa: E402
from core import governance                            # noqa: E402
from refilter_dataset import rebuild                   # noqa: E402

reg = Registry(ROOT); src = Path(snapshot_download(os.environ["SFT_REPO"], repo_type="dataset", allow_patterns=["*/test.jsonl"]))
rows, lock = [], threading.Lock()


def evaluar(job):
    variante, agent, e = job
    ag = reg.agents[agent]
    model = BASE if variante == "base" else agent
    ad = OpenAICompatAdapter({"model": model, "max_new_tokens": 6144, "temperature": 0.0, "chat_template_kwargs": {"enable_thinking": False}})
    _, ctx = rebuild(agent, e["messages"]); ctx["req_id"] = e["req_id"]
    r = {"variante": variante, "agente": agent, "req_id": e["req_id"], "contrato": False, "aprobado_r0": False, "f5": {}}
    try:
        resp = ad.complete(e["messages"][:-1], ag.output_schema)
        r.update(tokens_out=resp.tokens_out, latencia_ms=resp.latency_ms)
        out = json.loads(resp.text); jsonschema.validate(out, ag.output_schema); r["contrato"] = True
        Orchestrator._stamp_provenance(ag, out, e["req_id"])
        v, ok, f5 = governance.review(ag, out, ctx, 0)
        r.update(aprobado_r0=v["veredicto"] == "aprobado", f5={k: x["value"] for k, x in f5.items() if k != "refinement_rounds"},
                 hallazgos=[h["regla"] for h in v["hallazgos"]])
    except Exception as x:  # noqa: BLE001
        r["error"] = str(x)[:200]
    with lock:
        rows.append(r)


jobs = [(var, ag, json.loads(l)) for ag in ADAPTERS for var in ("base", "lora")
        for l in (src / ag / "test.jsonl").read_text(encoding="utf-8").splitlines()]
with ThreadPoolExecutor(max_workers=16) as ex:
    list(ex.map(evaluar, jobs))


def num(v):
    return float(v) if isinstance(v, (int, float, bool)) else None


tabla = {}
for ag in ADAPTERS:
    for var in ("base", "lora"):
        rs = [r for r in rows if r["agente"] == ag and r["variante"] == var]
        f5k = sorted({k for r in rs for k in r["f5"]})
        tabla[f"{ag}|{var}"] = {"n": len(rs), "contrato_%": round(100 * sum(r["contrato"] for r in rs) / len(rs), 1),
                                "aprobado_r0_%": round(100 * sum(r["aprobado_r0"] for r in rs) / len(rs), 1),
                                **{f"F5.{k}": round(statistics.mean([num(r["f5"][k]) for r in rs if k in r["f5"] and num(r["f5"][k]) is not None] or [0]), 3) for k in f5k},
                                "tokens_out_media": round(statistics.mean([r.get("tokens_out", 0) for r in rs]), 0),
                                "latencia_ms_media": round(statistics.mean([r.get("latencia_ms", 0) for r in rs]), 0)}
d = Path("/tmp/eval"); d.mkdir(exist_ok=True)
(d / "entorno.json").write_text(json.dumps(ENTORNO, ensure_ascii=False, indent=1), encoding="utf-8")
(d / "detalle.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
(d / "tabla.json").write_text(json.dumps(tabla, ensure_ascii=False, indent=1), encoding="utf-8")
HfApi().upload_folder(folder_path=str(d), path_in_repo=f"runs/f3_eval/{os.environ.get('JOB_ID', 'local')}", repo_id=os.environ["RUNS_REPO"], repo_type="dataset")
print("TABLA", json.dumps(tabla, ensure_ascii=False, indent=1), flush=True)
srv.terminate()
