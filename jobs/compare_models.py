# /// script
# requires-python = ">=3.11"
# dependencies = ["vllm", "jsonschema", "PyYAML", "huggingface_hub", "openapi-spec-validator", "scipy"]
# ///
"""Comparación de modelos base (sin ajuste) para justificar la elección del modelo base de los agentes entrenables.

Cada modelo responde los mismos casos de prueba de los 5 agentes entrenables (partición test de tesis-sft-v2),
con el mismo prompt, temperatura 0, una sola generación y salida restringida por JSON Schema. Se miden los mismos
indicadores de F3: contrato válido, aprobación de governance en la ronda 0, métricas F5, tokens y latencia.
Los modelos se sirven de uno en uno con vLLM en la misma GPU, para que la latencia sea comparable.
Variables: MODELS (separados por espacio; el primero es la referencia), SFT_REPO, RUNS_REPO, BRANCH, AGENTS."""
import io, json, os, statistics, subprocess, sys, tarfile, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "main")
MODELS = os.environ.get("MODELS", "Qwen/Qwen3-8B meta-llama/Llama-3.1-8B-Instruct mistralai/Mistral-7B-Instruct-v0.3").split()
AGENTS = os.environ.get("AGENTS", "product-analyst-agent solution-architect-agent api-designer-agent test-case-generator-agent cicd-pipeline-agent").split()
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(url).read())).extractall("/tmp", filter="data")
ROOT = Path(f"/tmp/tesis-{BRANCH.replace('/', '-')}"); os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from core.envinfo import report as _entorno  # noqa: E402
ENTORNO = _entorno({"job": os.environ.get("JOB_ID", "local"), "branch": BRANCH})
from huggingface_hub import snapshot_download, HfApi   # noqa: E402
import jsonschema                                       # noqa: E402
from scipy.stats import binomtest                       # noqa: E402
from core.registry import Registry                     # noqa: E402
from core.adapters.openai_compat import OpenAICompatAdapter   # noqa: E402
from core.orchestrator import Orchestrator             # noqa: E402
from core import governance                            # noqa: E402
from refilter_dataset import rebuild                   # noqa: E402

reg = Registry(ROOT)
src = Path(snapshot_download(os.environ["SFT_REPO"], repo_type="dataset", allow_patterns=["*/test.jsonl"]))
cases = [(ag, json.loads(l)) for ag in AGENTS for l in (src / ag / "test.jsonl").read_text(encoding="utf-8").splitlines()]
print("casos:", len(cases), flush=True)


def serve(model):
    srv = subprocess.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", model, "--served-model-name", model,
                            "--port", "8000", "--max-model-len", "16384", "--gpu-memory-utilization", "0.90"],
                           stdout=open("/tmp/vllm.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(240):
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=5); return srv
        except Exception:  # noqa: BLE001
            if srv.poll() is not None:
                print(open("/tmp/vllm.log").read()[-3000:], flush=True); return None
            time.sleep(10)
    srv.terminate(); return None


def messages_for(model, msgs):
    msgs = [dict(m) for m in msgs]
    if "mistral" in model.lower() and msgs and msgs[0]["role"] == "system":   # la plantilla de Mistral no admite rol system
        sysm = msgs.pop(0)["content"]
        msgs[0]["content"] = sysm + "\n\n" + msgs[0]["content"]
    return msgs


rows, lock = [], threading.Lock()


def evaluar(model, job):
    agent, e = job
    ag = reg.agents[agent]
    ad = OpenAICompatAdapter({"model": model, "max_new_tokens": 6144, "temperature": 0.0,
                              "chat_template_kwargs": {"enable_thinking": False} if "qwen3" in model.lower() else None})
    _, ctx = rebuild(agent, e["messages"]); ctx["req_id"] = e["req_id"]
    r = {"modelo": model, "agente": agent, "req_id": e["req_id"], "contrato": False, "aprobado_r0": False, "f5": {}}
    try:
        resp = ad.complete(messages_for(model, e["messages"][:-1]), ag.output_schema)
        r.update(tokens_out=resp.tokens_out, latencia_ms=resp.latency_ms)
        out = json.loads(resp.text); jsonschema.validate(out, ag.output_schema); r["contrato"] = True
        Orchestrator._stamp_provenance(ag, out, e["req_id"])
        v, ok, f5 = governance.review(ag, out, ctx, 0)
        r.update(aprobado_r0=v["veredicto"] == "aprobado", f5={k: x["value"] for k, x in f5.items() if k != "refinement_rounds"},
                 hallazgos=[h["regla"] for h in v["hallazgos"]])
    except Exception as x:  # noqa: BLE001
        r["error"] = str(x)[:300]
    with lock:
        rows.append(r)


estado = {}
for m in MODELS:
    t0 = time.time(); srv = serve(m)
    if srv is None:
        estado[m] = "no_arranco"; print(m, "→ vLLM no arrancó", flush=True); continue
    print(m, "listo en", round(time.time() - t0), "s", flush=True)
    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(lambda j: evaluar(m, j), cases))
    srv.terminate(); srv.wait(timeout=120); time.sleep(15)
    estado[m] = "ok"; print(m, "evaluado", flush=True)


def num(v):
    return float(v) if isinstance(v, (int, float, bool)) else None


def resumen(rs):
    f5k = sorted({k for r in rs for k in r["f5"]})
    ok = [r for r in rs if "tokens_out" in r]
    return {"n": len(rs), "contrato_%": round(100 * sum(r["contrato"] for r in rs) / len(rs), 1) if rs else None,
            "aprobado_r0_%": round(100 * sum(r["aprobado_r0"] for r in rs) / len(rs), 1) if rs else None,
            "errores": sum("error" in r for r in rs),
            **{f"F5.{k}": round(statistics.mean([num(r["f5"][k]) for r in rs if k in r["f5"] and num(r["f5"][k]) is not None] or [0]), 3) for k in f5k},
            "tokens_out_media": round(statistics.mean([r["tokens_out"] for r in ok]), 0) if ok else None,
            "latencia_s_media": round(statistics.mean([r["latencia_ms"] for r in ok]) / 1000, 1) if ok else None}


tabla = {m: {"global": resumen([r for r in rows if r["modelo"] == m]),
             **{ag: resumen([r for r in rows if r["modelo"] == m and r["agente"] == ag]) for ag in AGENTS}} for m in MODELS if estado.get(m) == "ok"}
ref = MODELS[0]; mcn = {}
key = lambda r: (r["agente"], r["req_id"])   # noqa: E731
a = {key(r): r["aprobado_r0"] for r in rows if r["modelo"] == ref}
for m in MODELS[1:]:
    b = {key(r): r["aprobado_r0"] for r in rows if r["modelo"] == m}
    comunes = set(a) & set(b)
    n10 = sum(a[k] and not b[k] for k in comunes); n01 = sum(b[k] and not a[k] for k in comunes)
    p = binomtest(n10, n10 + n01, 0.5, alternative="greater").pvalue if n10 + n01 else 1.0
    mcn[m] = {"solo_ref_aprueba": n10, "solo_otro_aprueba": n01, "p_mcnemar_unilateral": round(p, 6), "pares": len(comunes)}
d = Path("/tmp/cmp"); d.mkdir(exist_ok=True)
(d / "entorno.json").write_text(json.dumps(ENTORNO, ensure_ascii=False, indent=1), encoding="utf-8")
(d / "detalle.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
(d / "tabla.json").write_text(json.dumps({"estado": estado, "tabla": tabla, "mcnemar_vs_ref": mcn, "referencia": ref}, ensure_ascii=False, indent=1), encoding="utf-8")
HfApi().upload_folder(folder_path=str(d), path_in_repo=f"runs/compare_models/{os.environ.get('JOB_ID', 'local')}", repo_id=os.environ["RUNS_REPO"], repo_type="dataset")
print("TABLA", json.dumps({"estado": estado, "global": {m: t["global"] for m, t in tabla.items()}, "mcnemar": mcn}, ensure_ascii=False, indent=1), flush=True)
