# /// script
# requires-python = ">=3.11"
# dependencies = ["huggingface_hub==2.4.0", "jsonschema==4.26.0", "openapi-spec-validator==0.9.0", "PyYAML", "fastapi==0.136.3", "httpx", "pytest==9.2.0", "ruff==0.17.6", "bandit==1.9.4"]
# ///
"""eval_n3 · paso 3 (mitad de frontera): servicio limpio + pruebas de aceptación de referencia, escritos por los modelos de
frontera vía HF Inference Providers (solo CPU; sin GPU). La otra mitad la escribe Claude (uso 3 del documento de selección).

Reparto (eval_n3/README §3): de los casos con entrada de backend congelada, por hash del req_id: 15 Claude, 8 GLM-5.3 y
7 DeepSeek V4-Pro. Un caso entra solo si todas sus pruebas pasan contra su servicio limpio (hasta 4 intentos con el detalle
de los fallos).

Variables: BRANCH, RUNS_REPO (tesis-runs, con runs/eval_n3/casos/), HF_TOKEN."""
import hashlib, io, json, os, sys, tarfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
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
           "HTTPException(status_code=..., detail='<id del catálogo de errores>'); no importes módulos; (2) las semillas "
           "usan exactamente las tablas y columnas dadas; (3) cada prueba usa las fixtures `client` (TestClient) y `db`, llama "
           "a un endpoint con client y verifica status y cuerpo; las pruebas referencian datos de las semillas por su id "
           "(no por posición) y cubren los casos felices, los errores del catálogo y las reglas de negocio; (4) entre 6 y 12 "
           "pruebas. Responde solo con el JSON.")


def generar(req: str) -> dict:
    prov = autoria[req]
    if prov == "claude":
        return {"req_id": req, "autor": "claude", "estado": "pendiente_claude"}
    entrada = json.loads((src / req / "entradas" / "backend-developer-agent.json").read_text(encoding="utf-8"))
    name, cfg = prov, dict(reg.providers_cfg["providers"][prov]); cfg["reasoning_effort"] = "high"
    ad = build_adapter(name, cfg, ROOT)
    msgs = [{"role": "system", "content": SISTEMA}, {"role": "user", "content": "## Entrada\n```json\n" + json.dumps(entrada, ensure_ascii=False, indent=1) + "\n```"}]
    for intento in range(4):
        try:
            r = ad.complete(msgs, SCHEMA)
            d = json.loads(r.text)
            back = {"req_id": req, "handlers": d["handlers"], "semillas": d["semillas"]}
            qa = {"req_id": req, "suites": d["suites"]}
            files = sandbox.render_app(entrada["api_design"], entrada["data_model"], back)
            rt = sandbox.run_tests(files, qa)
            if rt["collected"] >= 6 and rt["passed"] == rt["collected"]:
                return {"req_id": req, "autor": prov, "modelo": cfg["model"], "estado": "ok", "intentos": intento + 1,
                        "pruebas": rt["collected"], "servicio_limpio": back, "pruebas_aceptacion": qa}
            fallos = "\n".join(f"- {f['prueba']}: {f['detalle'][:300]}" for f in rt["fallos"][:8]) or f"recolectadas {rt['collected']} (mínimo 6)"
            msgs = msgs[:2] + [{"role": "assistant", "content": r.text[:20000]},
                               {"role": "user", "content": f"Las pruebas no pasan contra tu servicio:\n{fallos}\nCorrige el servicio o las pruebas (sin bajar la exigencia) y responde de nuevo el JSON completo."}]
        except Exception as e:  # noqa: BLE001
            msgs = msgs[:2] + [{"role": "user", "content": f"Error: {str(e)[:400]}. Responde de nuevo el JSON completo."}]
    return {"req_id": req, "autor": prov, "estado": "descartado"}


with ThreadPoolExecutor(max_workers=6) as ex:
    res = list(ex.map(generar, casos))
out = Path("/tmp/ref"); out.mkdir()
for x in res:
    d = out / x["req_id"]; d.mkdir()
    for k in ("servicio_limpio", "pruebas_aceptacion"):
        if k in x:
            (d / f"{k}.json").write_text(json.dumps(x.pop(k), ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "autoria.json").write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
api.upload_folder(folder_path=str(out), path_in_repo="runs/eval_n3/casos", repo_id=RUNS, repo_type="dataset", commit_message="eval_n3: referencias de frontera")
print("RESUMEN", json.dumps({"casos": len(res), "por_autor": {a: sum(x["autor"] == a for x in res) for a in ("claude", "hf_glm53", "hf_dsv4pro")},
                             "ok": sum(x["estado"] == "ok" for x in res), "descartados": [x["req_id"] for x in res if x["estado"] == "descartado"]}, ensure_ascii=False))
