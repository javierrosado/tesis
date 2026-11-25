# /// script
# requires-python = ">=3.11"
# dependencies = ["vllm==0.34.0", "xgrammar==0.2.8", "huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML", "scipy==1.18.1"]
# ///
"""G4 · ¿Baja el adaptador LoRA de product-analyst con BusinessRequest v1.1? (consola §3, opción A del autor, 24/11/2026)

1. Toma los 24 casos de prueba de product-analyst (tesis-sft-v2, construidos con v1.0).
2. El maestro Qwen3-32B-AWQ redacta historia_original (todos) y criterios (30 %); las notas son plantilla determinista
   (scripts/g4_contexto.py). Nada más del BusinessRequest cambia.
3. Una generación por caso (temperatura 0, sin reintentos), como en F3: base y LoRA, con v1.0 y con v1.1.
   Métricas: contrato válido y aprobación de governance en la ronda 0.
4. McNemar exacto (bilateral) LoRA v1.0 vs LoRA v1.1 sobre los mismos casos.
Salida: runs/g4_eval/<job>/ en RUNS_REPO (contextos sintéticos, detalle, tabla, entorno).
Variables: SFT_REPO, RUNS_REPO, BRANCH, ADAPTER (repo del LoRA de product-analyst), TEACHER."""
import io, json, os, statistics, subprocess, sys, tarfile, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "main"); BASE = os.environ.get("BASE", "Qwen/Qwen3-8B")
TEACHER = os.environ.get("TEACHER", "Qwen/Qwen3-32B-AWQ")
ADAPTER = os.environ.get("ADAPTER", "jrosado1974/qwen3-8b-product-analyst-lora"); AG = "product-analyst-agent"
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
_auth = {"Authorization": "token " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}
tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=_auth)).read())).extractall("/tmp", filter="data")
ROOT = Path(f"/tmp/tesis-{BRANCH.replace('/', '-')}"); os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from core.envinfo import report as _entorno  # noqa: E402
ENTORNO = _entorno({"job": os.environ.get("JOB_ID", "local"), "branch": BRANCH})
from huggingface_hub import snapshot_download, HfApi   # noqa: E402
api = HfApi()
lora = snapshot_download(ADAPTER)
ENTORNO["modelos"] = {"base": f"{BASE}@{api.model_info(BASE).sha}", "lora": f"{ADAPTER}@{api.model_info(ADAPTER).sha}",
                      "maestro": f"{TEACHER}@{api.model_info(TEACHER).sha}"}


def servir(args, puerto, log):
    p = subprocess.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", *args, "--port", str(puerto)],
                         stdout=open(log, "w"), stderr=subprocess.STDOUT)
    for _ in range(180):
        try:
            urllib.request.urlopen(f"http://localhost:{puerto}/health", timeout=5); return p
        except Exception:  # noqa: BLE001
            if p.poll() is not None:
                print(open(log).read()[-4000:]); sys.exit(f"vLLM no arrancó ({puerto})")
            time.sleep(10)
    sys.exit("vLLM no respondió")


s8 = servir(["--model", BASE, "--max-model-len", "16384", "--gpu-memory-utilization", "0.36", "--enable-lora", "--max-lora-rank", "64",
             "--lora-modules", f"{AG}={lora}"], 8000, "/tmp/vllm8.log")
s32 = servir(["--model", TEACHER, "--max-model-len", "16384", "--gpu-memory-utilization", "0.54", "--max-num-seqs", "16"], 8001, "/tmp/vllm32.log")
print("vLLM listos", json.dumps(ENTORNO["modelos"]), flush=True)

import jsonschema                                            # noqa: E402
from scipy import stats                                      # noqa: E402
from core.registry import Registry                          # noqa: E402
from core.adapters.openai_compat import OpenAICompatAdapter  # noqa: E402
from core.orchestrator import Orchestrator                  # noqa: E402
from core import governance                                 # noqa: E402
import g4_contexto as g4                                    # noqa: E402

reg = Registry(ROOT); ag = reg.agents[AG]
src = Path(snapshot_download(os.environ.get("SFT_REPO", "jrosado1974/tesis-sft-v2"), repo_type="dataset", allow_patterns=[f"{AG}/test.jsonl"]))
casos = [json.loads(l) for l in (src / AG / "test.jsonl").read_text(encoding="utf-8").splitlines()]
maestro = OpenAICompatAdapter({"model": TEACHER, "url": "http://localhost:8001/v1", "max_new_tokens": 1024, "temperature": 0.0,
                               "chat_template_kwargs": {"enable_thinking": False}})
docs = g4.documentados([c["req_id"] for c in casos])


def contexto(c):
    br = g4.leer_br(c["messages"])
    hist = json.loads(maestro.complete(g4.prompt_historia(br), g4.TEXTO_SCHEMA).text)["texto"]
    crit = json.loads(maestro.complete(g4.prompt_criterios(br), g4.TEXTO_SCHEMA).text)["texto"] if c["req_id"] in docs else None
    b11 = g4.br_v11(br, hist, crit)
    jsonschema.validate(b11, ag.input_schema)
    return {"req_id": c["req_id"], "v10": br, "v11": b11}


with ThreadPoolExecutor(max_workers=8) as ex:
    ctxs = list(ex.map(contexto, casos))
print("contextos v1.1 generados:", len(ctxs), "· con criterios:", len(docs), flush=True)

rows, lock = [], threading.Lock()


def evaluar(job):
    variante, version, c, x = job
    br = x[version]
    msgs = g4.con_br(c["messages"], br)
    ad = OpenAICompatAdapter({"model": BASE if variante == "base" else AG, "max_new_tokens": 6144, "temperature": 0.0,
                              "chat_template_kwargs": {"enable_thinking": False}})
    r = {"variante": variante, "version": version, "req_id": c["req_id"], "contrato": False, "aprobado_r0": False}
    try:
        resp = ad.complete(msgs, ag.output_schema)
        r.update(tokens_out=resp.tokens_out, latencia_ms=resp.latency_ms)
        out = json.loads(resp.text); jsonschema.validate(out, ag.output_schema); r["contrato"] = True
        Orchestrator._stamp_provenance(ag, out, c["req_id"])
        v, _, f5 = governance.review(ag, out, {"req_id": c["req_id"], "business_request": br}, 0)
        r.update(aprobado_r0=v["veredicto"] == "aprobado", f5={k: y["value"] for k, y in f5.items() if k != "refinement_rounds"},
                 hallazgos=[h["regla"] for h in v["hallazgos"]])
    except Exception as e:  # noqa: BLE001
        r["error"] = str(e)[:200]
    with lock:
        rows.append(r)


trabajos = [(var, ver, c, x) for c, x in zip(casos, ctxs) for var in ("base", "lora") for ver in ("v10", "v11")]
with ThreadPoolExecutor(max_workers=16) as ex:
    list(ex.map(evaluar, trabajos))

tabla = {}
for var in ("base", "lora"):
    for ver in ("v10", "v11"):
        rs = [r for r in rows if r["variante"] == var and r["version"] == ver]
        tabla[f"{var}|{ver}"] = {"n": len(rs), "contrato_%": round(100 * sum(r["contrato"] for r in rs) / len(rs), 1),
                                 "aprobado_r0_%": round(100 * sum(r["aprobado_r0"] for r in rs) / len(rs), 1),
                                 "tokens_out_media": round(statistics.mean([r.get("tokens_out", 0) for r in rs]), 0)}
par = {}
for var in ("base", "lora"):
    a = {r["req_id"]: r["aprobado_r0"] for r in rows if r["variante"] == var and r["version"] == "v10"}
    b = {r["req_id"]: r["aprobado_r0"] for r in rows if r["variante"] == var and r["version"] == "v11"}
    solo10 = sum(a[k] and not b[k] for k in a); solo11 = sum(b[k] and not a[k] for k in a)
    p = min(1.0, 2 * stats.binom.cdf(min(solo10, solo11), solo10 + solo11, 0.5)) if solo10 + solo11 else 1.0
    par[var] = {"solo_v10_aprueba": solo10, "solo_v11_aprueba": solo11, "mcnemar_exacto_bilateral_p": round(float(p), 4)}
tabla["mcnemar_v10_vs_v11"] = par
baja = tabla["lora|v11"]["aprobado_r0_%"] < tabla["lora|v10"]["aprobado_r0_%"]
tabla["conclusion"] = ("el adaptador BAJA con v1.1: proponer re-destilar o re-entrenar (requiere OK del autor)" if baja
                       else "el adaptador no baja con v1.1: se mantiene")

d = Path("/tmp/g4"); d.mkdir(exist_ok=True)
(d / "entorno.json").write_text(json.dumps(ENTORNO, ensure_ascii=False, indent=1), encoding="utf-8")
(d / "contextos_v11_sinteticos.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in ctxs), encoding="utf-8")
(d / "detalle.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
(d / "tabla.json").write_text(json.dumps(tabla, ensure_ascii=False, indent=1), encoding="utf-8")
api.upload_folder(folder_path=str(d), path_in_repo=f"runs/g4_eval/{os.environ.get('JOB_ID', 'local')}", repo_id=os.environ["RUNS_REPO"], repo_type="dataset")
print("TABLA", json.dumps(tabla, ensure_ascii=False, indent=1), flush=True)
s8.terminate(); s32.terminate()
