# /// script
# requires-python = ">=3.11"
# dependencies = ["huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML", "fastapi==0.136.3", "httpx", "pytest==9.2.0", "ruff==0.17.6", "bandit==1.9.4", "scipy==1.18.1", "anthropic"]
# ///
"""N3 · Benchmark de los 5 agentes N3 sobre eval_n3 (plan v1 · N3; selección por niveles §3).

Modelos (MODELOS, coma): proveedores de config/providers.yaml. Por defecto los de frontera por HF Inference Providers
(hf_glm53, hf_dsv4pro, hf_dsv4flash) y la referencia de techo Claude (claude_ref, API de pago por uso, model_id fijado) si
hay ANTHROPIC_API_KEY. Todo por API: el job corre en CPU.

Métricas por agente (eval_n3/README §1):
- solution-architect, data-model, security-compliance: contrato válido y aprobación de governance en la ronda 0;
- backend-developer: pass@1 = todas las pruebas de aceptación del caso pasan con las semillas de referencia;
- code-review: recall de defectos sembrados (hallazgo crítico o mayor dentro del handler del defecto) y falsos positivos
  sobre el servicio limpio.
Pares de modelos sobre los mismos casos: McNemar exacto bilateral. Costo por llamada (usage.cost) y latencia.
Salida: runs/bench_n3/<job>/ en RUNS_REPO. Variables: BRANCH, RUNS_REPO, MODELOS, AGENTES, MAX_CASOS."""
import io, itertools, json, os, statistics, sys, tarfile, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "main")
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
_auth = {"Authorization": "token " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}
_tar = tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=_auth)).read())); _tar.extractall("/tmp", filter="data")
ROOT = Path("/tmp") / _tar.getnames()[0].split("/")[0]; os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from core.envinfo import report as _entorno                 # noqa: E402
from huggingface_hub import HfApi, snapshot_download        # noqa: E402
from scipy import stats                                      # noqa: E402
from core.orchestrator import Orchestrator                  # noqa: E402
from core.telemetry import Telemetry                        # noqa: E402
from core.model_port import ModelPort                       # noqa: E402
from core.adapters import build_adapter                     # noqa: E402
from core import governance, verify                         # noqa: E402
from core.tools import sandbox                              # noqa: E402

JOB = os.environ.get("JOB_ID", "local"); RUNS = os.environ["RUNS_REPO"]; api = HfApi()
ENTORNO = _entorno({"job": JOB, "branch": BRANCH})
MODELOS = os.environ.get("MODELOS", "hf_glm53,hf_dsv4pro,hf_dsv4flash" + (",claude_ref" if os.environ.get("ANTHROPIC_API_KEY") else "")).split(",")
AGENTES = os.environ.get("AGENTES", "solution-architect-agent,data-model-agent,security-compliance-agent,backend-developer-agent,code-review-agent").split(",")
src = Path(snapshot_download(RUNS, repo_type="dataset", allow_patterns=["runs/eval_n3/casos/**"])) / "runs/eval_n3/casos"
casos = sorted(p.name for p in src.iterdir() if (p / "caso.json").exists())[: int(os.environ.get("MAX_CASOS", "999"))]
tel = Telemetry(Path(f"/tmp/bench_{JOB}.jsonl"), run_id=JOB, echo=False)
orch = Orchestrator(ROOT, tel, today="2026-11-25")
reg = orch.reg
ENTORNO["modelos"] = {}
for m in MODELOS:
    cfg = reg.providers_cfg["providers"][m]
    repo = cfg["model"].split(":")[0]
    try:
        ENTORNO["modelos"][m] = f"{repo}@{api.model_info(repo).sha}" + (f" vía {cfg['model'].split(':')[1]}" if ":" in cfg["model"] else "")
    except Exception:  # noqa: BLE001
        ENTORNO["modelos"][m] = cfg["model"]          # p. ej. Claude: model_id fijado, sin repo en HF
print("MODELOS", json.dumps(ENTORNO["modelos"], ensure_ascii=False), "· casos", len(casos), flush=True)


def J(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def adaptador(m: str, agente: str):
    cfg = dict(reg.providers_cfg["providers"][m])
    esf = reg.agents[agente].spec.get("reasoning_effort")
    if esf and cfg.get("acepta_reasoning_effort"):
        cfg["reasoning_effort"] = (reg.niveles.get("esfuerzo") or {}).get(esf, esf)
        if esf == "maximo" and cfg.get("max_new_tokens_maximo"):
            cfg["max_new_tokens"] = cfg["max_new_tokens_maximo"]
    return build_adapter(f"{m}@{esf}", cfg, ROOT)


def llamar(m, agente, caso, payload, br, variante=""):
    ag = reg.agents[agente]
    knowledge, _ = orch.rag.context_block(orch._queries_for(ag, {"business_request": br}))
    msgs = orch._messages(ag, payload, knowledge)
    out, st = ModelPort(adaptador(m, agente), tel).run(ag, caso, msgs, variant=variante)
    return out, st


def evaluar(job):
    m, agente, caso = job
    d = src / caso
    br = J(d / "business_request.json") or {}
    r = {"modelo": m, "agente": agente, "caso": caso, "autor_ref": (J(d / "autoria.json") or {}).get("autor")}
    try:
        if agente == "code-review-agent":
            return evaluar_revision(m, caso, d, br, r)
        payload = J(d / "entradas" / f"{agente}.json")
        if payload is None:
            return None
        out, st = llamar(m, agente, caso, payload, br)
        r.update(contrato=True, tokens_out=st["tokens_out"], latencia_ms=st["latency_ms"], costo_usd=st.get("costo_usd", 0), intentos=st["attempts"])
        # humo 6b072dce: con solo api_design y data_model, governance no veía la arquitectura (F5.comps_valid de security
        # fallaba siempre) ni el dominio (entity_coverage de data-model pasaba sin comparar). Se carga todo lo aprobado aguas arriba.
        ctx = {"req_id": caso, "business_request": br, **{p.stem: J(p) for p in sorted((d / "pipeline_v1").glob("*.json"))}}
        if agente == "backend-developer-agent":
            ref, pruebas = J(d / "servicio_limpio.json"), J(d / "pruebas_aceptacion.json")
            if not ref or not pruebas:
                return None
            back = {**out, "semillas": ref["semillas"]}           # datos de referencia del caso: las pruebas los referencian por id
            files = sandbox.render_app(payload["api_design"], payload["data_model"], back)
            rt = sandbox.run_tests(files, pruebas)
            r.update(def_repetida=sum(bool(h.get("lineas")) and h["lineas"][0].lstrip().startswith("def ") for h in out.get("handlers", [])),
                     fallos=[f"{f['prueba']}: {f['detalle'][:160]}" for f in rt["fallos"][:5]])
            r.update(pruebas=rt["collected"], pasan=rt["passed"], pass_at_1=rt["collected"] > 0 and rt["passed"] == rt["collected"],
                     tasa=round(rt["passed"] / rt["collected"], 3) if rt["collected"] else 0.0)
        else:
            v, _, f5 = governance.review(reg.agents[agente], out, ctx, 0)
            r.update(aprobado_r0=v["veredicto"] == "aprobado", hallazgos=[h["regla"] for h in v["hallazgos"]])
    except Exception as e:  # noqa: BLE001
        r.update(contrato=False, error=str(e)[:300], aprobado_r0=False, pass_at_1=False)
    return r


def _detecta(files, endpoint, hallazgos) -> bool:
    a, b = sandbox.handler_spans(files).get(endpoint, (0, -1))
    return any(h.get("severidad") in ("critico", "mayor") and h.get("archivo") == "app/main.py" and a - 2 <= int(h.get("linea", 0)) <= b
               for h in hallazgos)


def evaluar_revision(m, caso, d, br, r):
    api_d, dm = J(d / "pipeline_v1" / "api_design.json"), J(d / "pipeline_v1" / "data_model.json")
    # humo 6b072dce: la suite del pipeline v1 se escribió para OTRO backend (sus semillas e ids); contra el servicio limpio
    # fallaba y los revisores reportaban 7–11 falsos positivos por caso. Se usan las pruebas de aceptación del caso, que
    # pasan contra el servicio limpio. Con ellas los mutantes de lógica aparecen en el reporte de pruebas (como en el
    # pipeline); los defectos de seguridad no: el recall se reporta por tipo.
    qa, limpio = J(d / "pruebas_aceptacion.json") or {"suites": []}, J(d / "servicio_limpio.json")
    if not (api_d and dm and limpio) or not (d / "defectos").exists():
        return None
    detalle, costo = [], 0.0
    variantes = [("limpio", None, limpio)] + [(x["id"], x, x["backend_code"]) for x in (J(p) for p in sorted((d / "defectos").glob("D*.json")))]
    for vid, defecto, back in variantes:
        ctx = {"req_id": caso, "api_design": api_d, "data_model": dm, "backend_code": back, "qa_suite": qa}
        payload = orch._special_payload("code-review-agent", ctx)
        try:
            out, st = llamar(m, "code-review-agent", caso, payload, br, variante=vid)
            costo += st.get("costo_usd", 0)
            files = verify.app_files(ctx)
            hall = out.get("hallazgos", [])
            if defecto is None:
                detalle.append({"variante": vid, "falsos_positivos": sum(h.get("severidad") in ("critico", "mayor") for h in hall)})
            else:
                detalle.append({"variante": vid, "tipo": defecto["tipo"], "detectado": _detecta(files, defecto["endpoint"], hall)})
        except Exception as e:  # noqa: BLE001
            detalle.append({"variante": vid, "error": str(e)[:200], "detectado": False})
    defs = [x for x in detalle if x["variante"] != "limpio"]
    r.update(contrato=True, defectos=len(defs), detectados=sum(x.get("detectado", False) for x in defs),
             falsos_positivos=next((x.get("falsos_positivos") for x in detalle if x["variante"] == "limpio"), None),
             detalle=detalle, costo_usd=costo)
    return r


trabajos = [(m, a, c) for m in MODELOS for a in AGENTES for c in casos]
filas, lock = [], threading.Lock()
with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "12"))) as ex:
    for x in ex.map(evaluar, trabajos):
        if x:
            with lock:
                filas.append(x)

METRICA = {"backend-developer-agent": "pass_at_1", "code-review-agent": None}
tabla = {}
for a in AGENTES:
    tabla[a] = {}
    for m in MODELOS:
        fs = [f for f in filas if f["agente"] == a and f["modelo"] == m]
        if not fs:
            continue
        t = {"n": len(fs), "contrato_%": round(100 * sum(f.get("contrato", False) for f in fs) / len(fs), 1),
             "costo_usd": round(sum(f.get("costo_usd") or 0 for f in fs), 3)}
        if a == "code-review-agent":
            dd = sum(f.get("defectos", 0) for f in fs); det = sum(f.get("detectados", 0) for f in fs)
            por_tipo = {}
            for tp in ("logica", "seguridad"):
                xs = [x for f in fs for x in f.get("detalle", []) if x.get("tipo") == tp]
                por_tipo[tp] = round(100 * sum(x.get("detectado", False) for x in xs) / len(xs), 1) if xs else None
            t.update(defectos=dd, detectados=det, recall_pct=round(100 * det / dd, 1) if dd else None, recall_por_tipo_pct=por_tipo,
                     falsos_positivos_media=round(statistics.mean([f["falsos_positivos"] for f in fs if f.get("falsos_positivos") is not None] or [0]), 2))
        else:
            k = METRICA.get(a) or "aprobado_r0"
            t[f"{k}_%"] = round(100 * sum(bool(f.get(k)) for f in fs) / len(fs), 1)
        if a in ("backend-developer-agent", "code-review-agent"):    # eval_n3/README §3.1: sesgo de autoría (19 Claude / 9 frontera)
            est = {}
            for au in sorted({f.get("autor_ref") or "?" for f in fs}):
                g = [f for f in fs if (f.get("autor_ref") or "?") == au]
                if a == "code-review-agent":
                    dd = sum(f.get("defectos", 0) for f in g)
                    est[au] = {"n": len(g), "recall_pct": round(100 * sum(f.get("detectados", 0) for f in g) / dd, 1) if dd else None}
                else:
                    est[au] = {"n": len(g), "pass_at_1_%": round(100 * sum(bool(f.get("pass_at_1")) for f in g) / len(g), 1)}
            t["por_autor_ref"] = est
        lat = [f["latencia_ms"] for f in fs if f.get("latencia_ms")]
        t["latencia_mediana_s"] = round(statistics.median(lat) / 1000, 1) if lat else None
        tabla[a][m] = t
    # McNemar por pares sobre el mismo resultado binario por caso (code-review: por defecto)
    pares = {}
    for m1, m2 in itertools.combinations(MODELOS, 2):
        if a == "code-review-agent":
            v1 = {(f["caso"], x["variante"]): x.get("detectado", False) for f in filas if f["agente"] == a and f["modelo"] == m1 for x in f.get("detalle", []) if x["variante"] != "limpio"}
            v2 = {(f["caso"], x["variante"]): x.get("detectado", False) for f in filas if f["agente"] == a and f["modelo"] == m2 for x in f.get("detalle", []) if x["variante"] != "limpio"}
        else:
            k = METRICA.get(a) or "aprobado_r0"
            v1 = {f["caso"]: bool(f.get(k)) for f in filas if f["agente"] == a and f["modelo"] == m1}
            v2 = {f["caso"]: bool(f.get(k)) for f in filas if f["agente"] == a and f["modelo"] == m2}
        com = set(v1) & set(v2)
        b = sum(v1[c] and not v2[c] for c in com); c_ = sum(v2[c] and not v1[c] for c in com)
        p = min(1.0, 2 * stats.binom.cdf(min(b, c_), b + c_, 0.5)) if b + c_ else 1.0
        pares[f"{m1} vs {m2}"] = {"n": len(com), f"solo_{m1}": b, f"solo_{m2}": c_, "p": round(float(p), 4)}
    tabla[a]["mcnemar"] = pares

d = Path("/tmp/bench"); d.mkdir(exist_ok=True)
(d / "entorno.json").write_text(json.dumps(ENTORNO, ensure_ascii=False, indent=1), encoding="utf-8")
(d / "detalle.jsonl").write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas), encoding="utf-8")
(d / "tabla.json").write_text(json.dumps(tabla, ensure_ascii=False, indent=1), encoding="utf-8")
tel.path.exists() and (d / "telemetria.jsonl").write_text(tel.path.read_text(encoding="utf-8"), encoding="utf-8")
api.upload_folder(folder_path=str(d), path_in_repo=f"runs/bench_n3/{JOB}", repo_id=RUNS, repo_type="dataset", commit_message=f"bench_n3 {JOB}")
print("TABLA", json.dumps(tabla, ensure_ascii=False, indent=1), flush=True)
