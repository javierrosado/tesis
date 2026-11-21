# /// script
# requires-python = ">=3.11"
# dependencies = ["vllm==0.34.0", "xgrammar==0.2.8", "huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML"]
# ///
"""Regenera con el maestro las salidas de UN agente reutilizando las entradas ya destiladas (mismo payload y
conocimiento recuperado), con el prompt y el schema vigentes y el bucle de governance del orquestador
(hasta 3 rondas con feedback). Se usa cuando una regla nueva de governance invalida las salidas previas.
Variables: AGENT, SRC_REPO (dataset con las entradas), DST_REPO (dataset destino; se reemplazan solo los archivos de AGENT), WORKERS."""
import io, json, os, re, subprocess, sys, tarfile, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "f3-qlora"); TEACHER = os.environ.get("TEACHER", "Qwen/Qwen3-32B-AWQ")
AGENT = os.environ["AGENT"]; SRC = os.environ["SRC_REPO"]; DST = os.environ["DST_REPO"]; WORKERS = int(os.environ.get("WORKERS", "16"))
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(url).read())).extractall("/tmp", filter="data")
ROOT = Path(f"/tmp/tesis-{BRANCH.replace('/', '-')}"); os.chdir(ROOT); sys.path.insert(0, str(ROOT))
srv = subprocess.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", TEACHER, "--port", "8000",
                        "--max-model-len", "20000", "--gpu-memory-utilization", "0.92", "--max-num-seqs", "48"],
                       stdout=open("/tmp/vllm.log", "w"), stderr=subprocess.STDOUT)
for _ in range(180):
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=5); break
    except Exception:  # noqa: BLE001
        if srv.poll() is not None:
            print(open("/tmp/vllm.log").read()[-4000:]); sys.exit("vLLM no arrancó")
        time.sleep(10)
print("vLLM listo", flush=True)

from huggingface_hub import snapshot_download, HfApi   # noqa: E402
from core.registry import Registry                     # noqa: E402
from core.model_port import ModelPort, ContractError   # noqa: E402
from core.telemetry import Telemetry                   # noqa: E402
from core.adapters.openai_compat import OpenAICompatAdapter   # noqa: E402
from core.orchestrator import Orchestrator             # noqa: E402
from core import governance                            # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
from refilter_dataset import rebuild, align_prompt     # noqa: E402

reg = Registry(ROOT); ag = reg.agents[AGENT]
adapter = OpenAICompatAdapter({"model": TEACHER, "max_new_tokens": 6144, "temperature": 0.3, "chat_template_kwargs": {"enable_thinking": False}})
src = Path(snapshot_download(SRC, repo_type="dataset", allow_patterns=[f"{AGENT}/*.jsonl"]))
items = [(sp, json.loads(l)) for sp in ("test", "val", "train") for l in (src / AGENT / f"{sp}.jsonl").read_text(encoding="utf-8").splitlines()]
out, lock, stats = {"train": [], "val": [], "test": []}, threading.Lock(), {"ok": 0, "fail": 0, "rondas": [0, 0, 0]}
# reanudación: conserva lo ya regenerado en DST y no lo repite
try:
    prev = Path(snapshot_download(DST, repo_type="dataset", allow_patterns=[f"{AGENT}/*.jsonl"]))
    for sp in out:
        f = prev / AGENT / f"{sp}.jsonl"
        if f.exists():
            out[sp] = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if '"regen-v2"' in l]
except Exception:  # noqa: BLE001
    pass
done_ids = {r["req_id"] for rows in out.values() for r in rows}
items = [it for it in items if it[1]["req_id"] not in done_ids]
print("reanudación:", len(done_ids), "ya regenerados;", len(items), "pendientes", flush=True)
tel = Telemetry(Path("/tmp/regen.jsonl"))


def one(sp_e):
    sp, e = sp_e
    try:
        payload, ctx = rebuild(AGENT, e["messages"]); ctx["req_id"] = e["req_id"]
        base = align_prompt(ag, e["messages"]); msgs = list(base)
        for rnd in range(3):
            res, _ = ModelPort(adapter, tel, max_retries=1).run(ag, e["req_id"], msgs, variant=f"r{rnd}")
            Orchestrator._stamp_provenance(ag, res, e["req_id"])
            v, ok, f5 = governance.review(ag, res, ctx, rnd)
            if v["veredicto"] == "aprobado":
                row = {"req_id": e["req_id"], "rounds": rnd, "f5": {k: r["value"] for k, r in f5.items()}, "origen": "regen-v2",
                       "messages": base + [{"role": "assistant", "content": json.dumps(res, ensure_ascii=False)}]}
                with lock:
                    out[sp].append(row); stats["ok"] += 1; stats["rondas"][rnd] += 1
                return
            msgs = base + [{"role": "user", "content": "Hallazgos de gobernanza sobre tu versión anterior; corrígelos todos:\n" + json.dumps(v["hallazgos"], ensure_ascii=False, indent=1)}]
    except (ContractError, Exception) as x:  # noqa: BLE001
        print("error", e["req_id"], str(x)[:150], flush=True)
    with lock:
        stats["fail"] += 1


def publish(final):
    d = Path("/tmp/regen_out") / AGENT; d.mkdir(parents=True, exist_ok=True)
    with lock:
        snap = {k: list(v) for k, v in out.items()}; st = json.loads(json.dumps(stats))
    for sp, rows in snap.items():
        (d / f"{sp}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (d / "regen_resumen.json").write_text(json.dumps({"agent": AGENT, "teacher": TEACHER, "src": SRC, "stats": st, "final": final,
                                                      "counts": {k: len(v) for k, v in snap.items()}}, indent=1), encoding="utf-8")
    HfApi().upload_folder(folder_path=str(d), path_in_repo=AGENT, repo_id=DST, repo_type="dataset", commit_message=f"regen {AGENT} ({'final' if final else 'parcial'})")
    print("publicado", st, {k: len(v) for k, v in snap.items()}, flush=True)


from concurrent.futures import as_completed   # noqa: E402
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = [ex.submit(one, it) for it in items]
    for i, _ in enumerate(as_completed(futs), 1):
        if i % 30 == 0:
            publish(False)
publish(True)
print("listo", stats, {k: len(v) for k, v in out.items()}, flush=True)
srv.terminate()
