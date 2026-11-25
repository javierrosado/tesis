# /// script
# requires-python = ">=3.11"
# dependencies = ["huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML", "fastapi==0.136.3", "httpx", "pytest==9.2.0", "ruff==0.17.6", "bandit==1.9.4", "anthropic"]
# ///
"""eval_n3 · paso 3 (mitad de frontera): servicio limpio + pruebas de aceptación de referencia, escritos por los modelos de
frontera vía HF Inference Providers (solo CPU; sin GPU). La otra mitad la escribe Claude (uso 3 del documento de selección).

Reparto (eval_n3/README §3): de los casos con entrada de backend congelada, por hash del req_id: 15 Claude, 8 GLM-5.3 y
7 DeepSeek V4-Pro. Un caso entra solo si todas sus pruebas pasan contra su servicio limpio (hasta 4 intentos con el detalle
de los fallos).

Variables: BRANCH, RUNS_REPO (tesis-runs, con runs/eval_n3/casos/), HF_TOKEN, ANTHROPIC_API_KEY (la mitad de Claude; sin ella esos casos
quedan pendientes)."""
import hashlib, io, json, os, sys, tarfile, textwrap, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BRANCH = os.environ.get("BRANCH", "main")
url = f"https://github.com/javierrosado/tesis/archive/refs/heads/{BRANCH}.tar.gz"
_auth = {"Authorization": "token " + os.environ["GITHUB_TOKEN"]} if os.environ.get("GITHUB_TOKEN") else {}
_tar = tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers=_auth)).read())); _tar.extractall("/tmp", filter="data")
ROOT = Path("/tmp") / _tar.getnames()[0].split("/")[0]; os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from huggingface_hub import HfApi, snapshot_download   # noqa: E402
from core.registry import Registry                      # noqa: E402
from core.adapters import build_adapter                 # noqa: E402
from core.tools import sandbox                          # noqa: E402

RUNS = os.environ["RUNS_REPO"]; api = HfApi()
src = Path(snapshot_download(RUNS, repo_type="dataset", allow_patterns=["runs/eval_n3/casos/**"])) / "runs/eval_n3/casos"
reg = Registry(ROOT)
casos = sorted(p.name for p in src.iterdir() if (p / "entradas" / "backend-developer-agent.json").exists())
SOLO = [c for c in os.environ.get("CASOS", "").split(",") if c]           # rehacer solo estos (p. ej. los descartados)
orden = sorted(casos, key=lambda r: hashlib.sha256(f"autoria:{r}".encode()).hexdigest())
n = len(orden); n_claude = round(n / 2); n_glm = round((n - n_claude) * 8 / 15)
autoria = {r: "claude" if i < n_claude else "hf_glm53" if i < n_claude + n_glm else "hf_dsv4pro" for i, r in enumerate(orden)}

BACK = reg.agents["backend-developer-agent"].output_schema
QA = reg.agents["qa-automation-agent"].output_schema
SCHEMA = {"title": "referencia", "type": "object", "additionalProperties": False, "required": ["handlers", "semillas", "suites"],
          "properties": {"handlers": BACK["properties"]["handlers"], "semillas": BACK["properties"]["semillas"], "suites": QA["properties"]["suites"]}}
SISTEMA = ("Eres un desarrollador senior. Escribes la implementación de referencia de un servicio (cuerpo de cada handler, en "
           "Python, con las firmas dadas) y sus pruebas de aceptación con pytest. Reglas: (1) los handlers usan solo DB (dict "
           "tabla → lista de filas), HTTPException y los parámetros de su firma; los errores se lanzan con "
           "HTTPException(status_code=..., detail='<id del catálogo de errores>'); no importes módulos; en `lineas` va solo el "
           "cuerpo de la función, sin la línea `def` (la firma la pone el sistema); (2) las semillas "
           "usan exactamente las tablas y columnas dadas; (3) cada prueba usa las fixtures `client` (TestClient) y `db`, llama "
           "a un endpoint con client y verifica status y cuerpo; las pruebas referencian datos de las semillas por su id "
           "(no por posición) y cubren los casos felices, los errores del catálogo y las reglas de negocio; (4) entre 6 y 12 "
           "pruebas. (5) Cada handler usa solo los parámetros de su firma en `firmas_handlers` (con esos nombres exactos; "
           "`body` existe solo si la firma lo tiene). (6) Cada función de prueba declara `client` y `db` como parámetros "
           "(def test_x(client, db):); no hay variables globales. Responde solo con el JSON.")


def _cuerpo(lineas: list[str]) -> list[str]:
    """Corrida 6b06ef0c (25/11): los modelos repetían la línea `def _ep_xxx(...)` dentro de `lineas`; render_app la envolvía en
    otra función, el handler real devolvía None y las 28 referencias se descartaron. Se quita esa línea y se des-indenta."""
    if lineas and lineas[0].lstrip().startswith("def "):
        return textwrap.dedent("\n".join(lineas[1:])).splitlines()
    return lineas


def generar(req: str) -> dict:
    prov = autoria[req]
    if prov == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return {"req_id": req, "autor": "claude", "estado": "pendiente_claude"}
        prov = "claude_ref"                     # uso 3: Claude por API de pago por uso, model_id fijado
    entrada = json.loads((src / req / "entradas" / "backend-developer-agent.json").read_text(encoding="utf-8"))
    name, cfg = prov, dict(reg.providers_cfg["providers"][prov])
    if cfg.get("acepta_reasoning_effort"):
        cfg["reasoning_effort"] = "high"
    ad = build_adapter(name, cfg, ROOT)
    msgs = [{"role": "system", "content": SISTEMA}, {"role": "user", "content": "## Entrada\n```json\n" + json.dumps(entrada, ensure_ascii=False, indent=1) + "\n```"}]
    ultimo = ""; gasto = {"costo_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "llamadas": 0}
    for intento in range(6):
        try:
            r = ad.complete(msgs, SCHEMA)
            gasto["llamadas"] += 1; gasto["tokens_in"] += r.tokens_in; gasto["tokens_out"] += r.tokens_out
            gasto["costo_usd"] = round(gasto["costo_usd"] + float((r.meta or {}).get("costo_usd") or 0), 6)
            d = json.loads(r.text)
            back = {"req_id": req, "handlers": [{**h, "lineas": _cuerpo(h["lineas"])} for h in d["handlers"]], "semillas": d["semillas"]}
            qa = {"req_id": req, "suites": d["suites"]}
            files = sandbox.render_app(entrada["api_design"], entrada["data_model"], back)
            rt = sandbox.run_tests(files, qa)
            if rt["collected"] >= 6 and rt["passed"] == rt["collected"]:
                return {"req_id": req, "autor": autoria[req], "proveedor": prov, "modelo": cfg["model"], "estado": "ok", "intentos": intento + 1,
                        "pruebas": rt["collected"], **gasto, "servicio_limpio": back, "pruebas_aceptacion": qa}
            fallos = "\n".join(f"- {f['prueba']}: {f['detalle'][:300]}" for f in rt["fallos"][:8]) or f"recolectadas {rt['collected']} (mínimo 6)"
            ultimo = f"intento {intento + 1}: {rt['passed']}/{rt['collected']}\n{fallos}"
            msgs = msgs[:2] + [{"role": "assistant", "content": r.text[:20000]},
                               {"role": "user", "content": f"Las pruebas no pasan contra tu servicio:\n{fallos}\nCorrige el servicio o las pruebas (sin bajar la exigencia) y responde de nuevo el JSON completo."}]
        except Exception as e:  # noqa: BLE001
            ultimo = f"intento {intento + 1}: {type(e).__name__}: {str(e)[:400]}"
            msgs = msgs[:2] + [{"role": "user", "content": f"Error: {str(e)[:400]}. Responde de nuevo el JSON completo."}]
    return {"req_id": req, "autor": autoria[req], "proveedor": prov, "estado": "descartado", **gasto, "ultimo_fallo": ultimo[:3000]}


_LOCK = threading.Lock()


def publicar(x: dict) -> None:
    """Sube cada caso en cuanto termina (antes solo al final: un timeout del job perdía todo)."""
    d = Path("/tmp/ref") / x["req_id"]; d.mkdir(parents=True, exist_ok=True)
    x = dict(x)
    for k in ("servicio_limpio", "pruebas_aceptacion"):
        if k in x:
            (d / f"{k}.json").write_text(json.dumps(x.pop(k), ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "autoria.json").write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
    with _LOCK:
        api.upload_folder(folder_path=str(d), path_in_repo=f"runs/eval_n3/casos/{x['req_id']}", repo_id=RUNS, repo_type="dataset",
                          commit_message=f"eval_n3: referencia {x['req_id']} ({x['estado']})")
    print("CASO", json.dumps({k: x.get(k) for k in ("req_id", "autor", "estado", "intentos", "llamadas", "costo_usd")}), flush=True)


res = []
with ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "3"))) as ex:   # 3 hilos: el router devolvía 429 con 6
    for f in as_completed([ex.submit(generar, c) for c in casos if not SOLO or c in SOLO]):
        x = f.result(); res.append({k: v for k, v in x.items() if k not in ("servicio_limpio", "pruebas_aceptacion")}); publicar(x)
print("RESUMEN", json.dumps({"casos": len(res), "por_autor": {a: sum(x["autor"] == a for x in res) for a in ("claude", "hf_glm53", "hf_dsv4pro")},
                             "ok": sum(x["estado"] == "ok" for x in res),
                             "costo_usd": {a: round(sum(x.get("costo_usd", 0) for x in res if x["autor"] == a), 4) for a in ("claude", "hf_glm53", "hf_dsv4pro")},
                             "descartados": [x["req_id"] for x in res if x["estado"] == "descartado"]}, ensure_ascii=False))
