# /// script
# requires-python = ">=3.11"
# dependencies = ["vllm==0.34.0", "xgrammar==0.2.8", "huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML"]
# ///
"""F2-A · Destilación: el maestro open-weight (Qwen3-32B-AWQ, servido con vLLM dentro del job) redacta
briefs de entrenamiento a partir de semillas y ejecuta el pipeline completo con governance determinista.
De cada agente entrenable se guarda el par (mensajes de la ronda 0 → salida finalmente aprobada).
Solo entran ejemplos aprobados por governance (contrato + F5 + procedencia): filtrado por rechazo.

Variables: RUNS_REPO, SFT_REPO, BRANCH, N_SEEDS, WORKERS, MAX_MINUTES, TEACHER."""
import hashlib, io, json, os, random, subprocess, sys, tarfile, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "f2a-agentes"); TEACHER = os.environ.get("TEACHER", "Qwen/Qwen3-32B-AWQ")
N = int(os.environ.get("N_SEEDS", "6")); WORKERS = int(os.environ.get("WORKERS", "6"))
DEADLINE = time.time() + 60 * float(os.environ.get("MAX_MINUTES", "40"))
SFT_REPO = os.environ["SFT_REPO"]; RUN_NAME = os.environ.get("RUN_NAME", "f2a_distill")
TRAINABLE = ["product-analyst-agent", "solution-architect-agent", "api-designer-agent", "test-case-generator-agent", "cicd-pipeline-agent"]

url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
_auth = {"Authorization": "token " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}  # repo privado desde el 23/11/2026
_tar = tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=_auth)).read())); _tar.extractall("/tmp", filter="data")
ROOT = Path("/tmp") / _tar.getnames()[0].split("/")[0]; os.chdir(ROOT); sys.path.insert(0, str(ROOT))  # nombre real de la carpeta (GitHub quita la 'v' inicial de ramas como v2-*)
from core.envinfo import report as _entorno  # noqa: E402
ENTORNO = _entorno({"job": os.environ.get("JOB_ID", "local"), "branch": BRANCH})

# 1) servidor vLLM con el maestro
srv = subprocess.Popen([sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", TEACHER, "--port", "8000",
                        "--max-model-len", "20000", "--gpu-memory-utilization", "0.92", "--max-num-seqs", "32"],
                       stdout=open("/tmp/vllm.log", "w"), stderr=subprocess.STDOUT)
for _ in range(180):
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=5); break
    except Exception:  # noqa: BLE001
        if srv.poll() is not None:
            print(open("/tmp/vllm.log").read()[-4000:]); sys.exit("vLLM no arrancó")
        time.sleep(10)
print("vLLM listo", flush=True)
os.environ["PIPELINE_PROVIDER"] = "teacher"

from core.orchestrator import Orchestrator   # noqa: E402
from core.telemetry import Telemetry         # noqa: E402
from core.adapters.openai_compat import OpenAICompatAdapter   # noqa: E402
from huggingface_hub import HfApi            # noqa: E402

subprocess.run([sys.executable, "scripts/gen_seeds.py", "--n", str(N), "--start", os.environ.get("SEED_START", "0"), "--out", "/tmp/seeds.jsonl"], check=True)
seeds = [json.loads(l) for l in open("/tmp/seeds.jsonl", encoding="utf-8")]
teacher = OpenAICompatAdapter({"model": TEACHER, "max_new_tokens": 2048, "temperature": 0.8, "chat_template_kwargs": {"enable_thinking": False}})
BRIEF_SCHEMA = {"title": "BriefDraft", "type": "object", "additionalProperties": False,
                "required": ["titulo", "necesidad", "resultado_esperado", "restricciones", "preguntas_abiertas", "historia_original"],
                "properties": {"titulo": {"type": "string", "minLength": 10, "maxLength": 90}, "necesidad": {"type": "string", "minLength": 150},
                               "resultado_esperado": {"type": "string", "minLength": 40}, "restricciones": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                               "preguntas_abiertas": {"type": "array", "items": {"type": "string"}, "maxItems": 3}, "historia_original": {"type": "string", "minLength": 60}}}


def write_brief(s: dict) -> None:
    reglas = "\n".join(f"- {r['id']}: {r['texto']}" for r in s["reglas"])
    prompt = (f"Redacta un requerimiento realista de software para una empresa de venta directa de cosméticos por catálogo (consultoras, campañas, zonas).\n"
              f"Área: {s['area']}. Tipo: {s['tipo']}. País: {s['pais']}. Canal: {s['canal']}. Solicitante: {s['solicitante']}. Complejidad: {s['puntos']} puntos.\n"
              f"Reglas de negocio que el requerimiento debe involucrar:\n{reglas}\n"
              f"resultado_esperado empieza con 'Como {s['rol']}, quiero ... para ...'. historia_original es el texto libre, informal y a veces ambiguo, con que el negocio lo pidió.\n"
              f"No inventes reglas distintas de las listadas. Responde solo con el JSON.")
    d = json.loads(teacher.complete([{"role": "user", "content": prompt}], BRIEF_SCHEMA).text)
    inp = ROOT / "data/requerimientos" / s["req_id"] / "input"; inp.mkdir(parents=True, exist_ok=True)
    restr = "\n".join(f"- {r}" for r in d["restricciones"])
    (inp / "brief.md").write_text(
        f"# Brief — {d['titulo']}\n\n| Campo | Valor |\n|---|---|\n| Requerimiento | {s['req_id']} |\n| Proyecto | {s['proyecto']} |\n| Tipo | {s['tipo']} |\n"
        f"| Solicitante | {s['solicitante']} |\n| Campaña objetivo | {s['campana']} |\n| Alcance geográfico | {s['pais']} |\n| Canal | {s['canal']} |\n"
        f"| Complejidad estimada | {s['puntos']} puntos |\n\n## Necesidad de negocio\n\n{d['necesidad']}\n\n## Resultado esperado\n\n{d['resultado_esperado']}\n\n"
        f"## Restricciones conocidas\n\n{restr}\n", encoding="utf-8")
    (inp / "historia_original.md").write_text(f"# Historia de usuario — registro original\n\n{d['historia_original']}\n", encoding="utf-8")
    (inp / "restricciones.json").write_text(json.dumps({"req_id": s["req_id"], "tipo": s["tipo"], "origen": "Área de negocio", "campana": s["campana"],
        "puntos_historia": s["puntos"], "datos_personales_involucrados": s["datos_personales"],
        "reglas_negocio_referenciadas": [f"{r['id']} {r['texto'][:40]}" for r in s["reglas"]], "preguntas_abiertas": d["preguntas_abiertas"]}, ensure_ascii=False), encoding="utf-8")


examples, rejections, stats, lock = [], [], {"ok": 0, "fail": 0, "skipped": 0}, threading.Lock()


def run_one(s: dict):
    if time.time() > DEADLINE:
        with lock: stats["skipped"] += 1
        return
    try:
        write_brief(s)
        orch = Orchestrator(ROOT, Telemetry(Path(f"/tmp/tel/{s['req_id']}.jsonl")), seed=2026)
        try:
            orch.run(s["req_id"]); ok = True
        except Exception as e:  # noqa: BLE001 — se conservan los agentes aprobados antes del fallo
            ok = False; print("fallo", s["req_id"], str(e)[:160], flush=True)
        with lock:
            examples.extend(e for e in orch.examples if e["agent"] in TRAINABLE)
            rejections.extend(orch.rejections)
            stats["ok" if ok else "fail"] += 1
    except Exception as e:  # noqa: BLE001
        with lock: stats["fail"] += 1
        print("error brief", s["req_id"], str(e)[:160], flush=True)


def split_of(req_id: str) -> str:
    h = int(hashlib.sha256(req_id.encode()).hexdigest(), 16) % 10
    return "test" if h == 0 else "val" if h == 1 else "train"


def publish(final: bool):
    out = Path("/tmp/sft"); out.mkdir(exist_ok=True)
    with lock: exs = list(examples)
    counts = {}
    for agent in TRAINABLE:
        for sp in ("train", "val", "test"):
            rows = [{"req_id": e["req_id"], "rounds": e["rounds"], "f5": e["f5"],
                     "messages": e["messages"] + [{"role": "assistant", "content": json.dumps(e["output"], ensure_ascii=False)}]}
                    for e in exs if e["agent"] == agent and split_of(e["req_id"]) == sp]
            counts[f"{agent}/{sp}"] = len(rows)
            p = out / agent / f"{sp}.jsonl"; p.parent.mkdir(exist_ok=True)
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    # muestra de revisión humana (~10 % por agente, del split train)
    rng = random.Random(2026); md = ["# Muestra de revisión humana (F2-A)\n"]
    for agent in TRAINABLE:
        tr = [e for e in exs if e["agent"] == agent and split_of(e["req_id"]) == "train"]
        for e in rng.sample(tr, max(1, len(tr) // 10)) if tr else []:
            md.append(f"\n## {agent} · {e['req_id']} · rondas {e['rounds']}\n\n```json\n{json.dumps(e['output'], ensure_ascii=False, indent=1)[:6000]}\n```\n")
    (out / "muestra_revision.md").write_text("".join(md), encoding="utf-8")
    with lock: rj = list(rejections)
    (out / "rechazos.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rj), encoding="utf-8")
    (out / "resumen.json").write_text(json.dumps({"teacher": TEACHER, "branch": BRANCH, "seeds": N, "stats": stats, "counts": counts, "final": final}, indent=1), encoding="utf-8")
    api = HfApi(); api.create_repo(SFT_REPO, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(folder_path=str(out), repo_id=SFT_REPO, repo_type="dataset", commit_message=f"{RUN_NAME} {'final' if final else 'parcial'}")
    print("publicado", counts, stats, flush=True)


Path("/tmp/tel").mkdir(exist_ok=True)
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = [ex.submit(run_one, s) for s in seeds]
    for i, _ in enumerate(as_completed(futs), 1):
        if i % 25 == 0:
            publish(False)
publish(True)
api = HfApi()
tel = "/tmp/tel_all.jsonl"
with open(tel, "w") as f:
    for p in Path("/tmp/tel").glob("*.jsonl"):
        f.write(p.read_text())
api.upload_file(path_or_fileobj=tel, path_in_repo=f"runs/{RUN_NAME}/{os.environ.get('JOB_ID', 'local')}/telemetria.jsonl", repo_id=os.environ["RUNS_REPO"], repo_type="dataset")
srv.terminate()
