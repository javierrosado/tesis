"""Ejecución real y aislada de los artefactos de Ingeniería y Calidad (sin modelo de lenguaje).

- render_app: genera el servicio FastAPI desde api_design + data_model + handlers de backend-developer.
- import_check / smoke: importa el servicio y llama cada endpoint con datos de ejemplo (TestClient).
- run_tests: ejecuta las suites pytest de qa-automation contra el servicio.
- static_analysis: ruff + bandit sobre el código generado.
- ddl_check: ejecuta el DDL (up y down) del modelo de datos en SQLite en memoria.
Todo corre en un directorio temporal con subprocess y límite de tiempo. Resultados memoizados por contenido."""
import hashlib, json, keyword, os, re, shutil, sqlite3, subprocess, sys, tempfile, textwrap
from pathlib import Path
import xml.etree.ElementTree as ET

_PY = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "array": "list", "object": "dict"}
_SAMPLE = {"string": "x1", "integer": 1, "number": 1.0, "boolean": True, "array": [], "object": {}}
_CACHE: dict = {}


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _ident(name: str) -> str:
    return name + "_" if keyword.iskeyword(name) else name


# ---------------------------------------------------------------- DDL
_SQL = {"TEXT": "TEXT", "INTEGER": "INTEGER", "REAL": "REAL", "BOOLEAN": "INTEGER", "DATE": "TEXT", "TIMESTAMP": "TEXT"}


def render_ddl(data_model: dict) -> tuple[str, str]:
    up, down = [], []
    for t in data_model.get("tablas", []):
        cols = [f'  "{c["nombre"]}" {_SQL[c["tipo"]]}{"" if c["nulo"] or c["pk"] else " NOT NULL"}' for c in t["columnas"]]
        pks = [c["nombre"] for c in t["columnas"] if c["pk"]]
        if pks:
            cols.append("  PRIMARY KEY (" + ", ".join(f'"{p}"' for p in pks) + ")")
        for fk in t.get("fks", []):
            cols.append(f'  FOREIGN KEY ("{fk["columna"]}") REFERENCES "{fk["tabla_ref"]}" ("{fk["columna_ref"]}")')
        up.append(f'CREATE TABLE "{t["nombre"]}" (\n' + ",\n".join(cols) + "\n);")
        down.insert(0, f'DROP TABLE "{t["nombre"]}";')
    return "\n\n".join(up) + "\n", "\n".join(down) + "\n"


def ddl_check(data_model: dict) -> dict:
    k = _key("ddl", data_model)
    if k in _CACHE:
        return _CACHE[k]
    up, down = render_ddl(data_model)
    res = {"ok": True, "error": None}
    try:
        names = {t["nombre"]: {c["nombre"] for c in t["columnas"]} for t in data_model.get("tablas", [])}
        for t in data_model.get("tablas", []):
            for fk in t.get("fks", []):
                if fk["tabla_ref"] not in names or fk["columna_ref"] not in names[fk["tabla_ref"]] or fk["columna"] not in names[t["nombre"]]:
                    raise ValueError(f'{t["id"]}: FK {fk["columna"]} → {fk["tabla_ref"]}.{fk["columna_ref"]} no existe')
        con = sqlite3.connect(":memory:"); con.execute("PRAGMA foreign_keys = ON")
        con.executescript(up); con.executescript(down); con.executescript(up); con.close()
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": str(e)[:300]}
    _CACHE[k] = res
    return res


# ---------------------------------------------------------------- servicio FastAPI
def render_app(api_design: dict, data_model: dict, backend: dict) -> dict[str, str]:
    handlers = {h["endpoint"]: h["lineas"] for h in backend.get("handlers", [])}
    seeds = {s["tabla"]: s["filas"] for s in backend.get("semillas", [])}
    tables = [t["nombre"] for t in data_model.get("tablas", [])]
    db = {t: seeds.get(t, []) for t in tables}
    for t, rows in seeds.items():
        db.setdefault(t, rows)
    out = ['"""Servicio generado por el pipeline multiagente (tesis UNI). No editar a mano."""',
           "from datetime import date, datetime, timedelta  # noqa: F401",
           "from typing import Any, Optional  # noqa: F401",
           "from fastapi import Body, FastAPI, Header, HTTPException, Query, Response  # noqa: F401", "",
           f'app = FastAPI(title={json.dumps(api_design.get("titulo_api", "API"), ensure_ascii=False)}, version={json.dumps(api_design.get("version_api", "v1"))})',
           f"DB: dict = {json.dumps(db, ensure_ascii=False, indent=1)}", "", ""]
    for ep in api_design.get("endpoints", []):
        fn = ep["id"].replace("-", "_").lower()
        params, call = [], []
        for p in ep.get("parametros", []):
            n, t = _ident(p["nombre"]), _PY[p["tipo"]]
            if p["en"] == "path":
                params.append(f"{n}: {t}")
            elif p["en"] == "query":
                params.append(f"{n}: Optional[{t}] = Query({'...' if p['requerido'] else 'None'}, alias={json.dumps(p['nombre'])})")
            else:
                params.append(f"{n}: Optional[str] = Header(None, alias={json.dumps(p['nombre'])})")
            call.append(f"{n}={n}")
        if ep.get("cuerpo"):
            params.append("body: dict = Body(...)"); call.append("body=body")
        status = (ep.get("respuestas") or [{"status": 200}])[0]["status"]
        lines = handlers.get(ep["id"]) or ['raise HTTPException(status_code=501, detail="no implementado")']
        body = textwrap.indent("\n".join(lines), "    ")
        sig = ", ".join(params)
        out += [f"def _{fn}({sig}):", body, "", "",
                f'@app.{ep["metodo"].lower()}({json.dumps(ep["ruta"])}, status_code={status}, summary={json.dumps(ep["resumen"], ensure_ascii=False)})',
                f"def {fn}({sig}):",
                f"    result = _{fn}({', '.join(call)})",
                "    return Response(status_code=204) if " + ("True" if status == 204 else "False") + " else result", "", ""]
    return {"app/__init__.py": "", "app/main.py": "\n".join(out) + "\n"}


def _workdir(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp(prefix="pipe_"))
    for rel, txt in files.items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(txt, encoding="utf-8")
    return d


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(cwd), "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(cwd)}
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, e.stdout or "", f"timeout {timeout}s")


def smoke(files: dict[str, str], api_design: dict) -> dict:
    k = _key("smoke", files, api_design)
    if k in _CACHE:
        return _CACHE[k]
    eps = [{"id": e["id"], "metodo": e["metodo"], "ruta": e["ruta"], "parametros": e.get("parametros", []),
            "cuerpo": {p["nombre"]: _SAMPLE[p["tipo"]] for s in api_design.get("esquemas", []) if s["nombre"] == e.get("cuerpo") for p in s["propiedades"]} if e.get("cuerpo") else None}
           for e in api_design.get("endpoints", [])]
    script = textwrap.dedent(f"""
        import json, sys
        try:
            from fastapi.testclient import TestClient
            from app.main import app, DB
        except Exception as e:
            print(json.dumps({{"import_ok": False, "error": repr(e)[:300]}})); sys.exit(0)
        c = TestClient(app, raise_server_exceptions=False)
        EPS = json.loads({json.dumps(json.dumps(eps, ensure_ascii=False))})
        def sample(name, tipo):
            for rows in DB.values():
                for r in rows:
                    if isinstance(r, dict) and name in r:
                        return r[name]
            return {{"integer": 1, "number": 1.0, "boolean": True}}.get(tipo, "1")
        res = []
        for e in EPS:
            path = e["ruta"]; q = {{}}; h = {{"Authorization": "Bearer prueba"}}
            for p in e["parametros"]:
                v = sample(p["nombre"], p["tipo"])
                if p["en"] == "path": path = path.replace("{{" + p["nombre"] + "}}", str(v))
                elif p["en"] == "query" and p["requerido"]: q[p["nombre"]] = v
                elif p["en"] == "header": h[p["nombre"]] = str(v)
            try:
                r = c.request(e["metodo"], path, params=q, headers=h, json=e["cuerpo"])
                vacia = r.status_code < 300 and r.status_code != 204 and r.content.strip() in (b"null", b"")
                res.append({{"id": e["id"], "status": 598 if vacia else r.status_code, **({{"error": "respuesta 2xx vacía (el handler no retorna nada)"}} if vacia else {{}})}})
            except Exception as ex:
                res.append({{"id": e["id"], "status": 599, "error": repr(ex)[:200]}})
        print(json.dumps({{"import_ok": True, "resultados": res}}))
    """)
    d = _workdir({**files, "_smoke.py": script})
    p = _run([sys.executable, "_smoke.py"], d, 120)
    shutil.rmtree(d, ignore_errors=True)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        res = {"import_ok": False, "error": (p.stderr or p.stdout)[-300:]}
    _CACHE[k] = res
    return res


_CONFTEST = '''import copy
import pytest
from fastapi.testclient import TestClient
from app.main import app, DB

_SEED = copy.deepcopy(DB)


@pytest.fixture
def db():
    DB.clear()
    DB.update(copy.deepcopy(_SEED))
    return DB


@pytest.fixture
def client(db):
    return TestClient(app, raise_server_exceptions=False)
'''


def run_tests(files: dict[str, str], qa_suite: dict) -> dict:
    k = _key("tests", files, qa_suite)
    if k in _CACHE:
        return _CACHE[k]
    tests = {f"tests/test_{s['id'].replace('-', '_').lower()}.py": "\n".join(s["lineas"]) + "\n" for s in qa_suite.get("suites", [])}
    d = _workdir({**files, **tests, "tests/conftest.py": _CONFTEST, "tests/__init__.py": ""})
    p = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=r.xml", "tests"], d, 180)
    res = {"returncode": p.returncode, "collected": 0, "passed": 0, "failed": 0, "errors": 0, "fallos": []}
    try:
        root = ET.parse(d / "r.xml").getroot()
        suites = [root] if root.tag == "testsuite" else list(root)
        for s in suites:
            for tc in s.iter("testcase"):
                res["collected"] += 1
                bad = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
                if bad is None and tc.find("skipped") is None:
                    res["passed"] += 1
                elif bad is not None:
                    res["failed" if bad.tag == "failure" else "errors"] += 1
                    res["fallos"].append({"prueba": f'{tc.get("classname")}::{tc.get("name")}', "detalle": (bad.get("message") or "")[:200]})
    except Exception as e:  # noqa: BLE001
        res["fallos"].append({"prueba": "<colección>", "detalle": (p.stdout + p.stderr)[-300:] or str(e)})
    res["suite_runs"] = p.returncode in (0, 1) and res["collected"] > 0
    res["pass_rate"] = round(res["passed"] / res["collected"], 3) if res["collected"] else 0.0
    shutil.rmtree(d, ignore_errors=True)
    _CACHE[k] = res
    return res


def static_analysis(files: dict[str, str]) -> dict:
    k = _key("static", files)
    if k in _CACHE:
        return _CACHE[k]
    d = _workdir(files)
    ruff = _run([sys.executable, "-m", "ruff", "check", "--output-format", "json", "--select", "E9,F,B", "--quiet", "app"], d, 60)
    band = _run([sys.executable, "-m", "bandit", "-q", "-f", "json", "-r", "app"], d, 60)
    res = {"ruff": [], "bandit": []}
    try:
        res["ruff"] = [{"archivo": Path(x["filename"]).relative_to(d).as_posix(), "linea": x["location"]["row"], "regla": x["code"], "mensaje": x["message"][:150]}
                       for x in json.loads(ruff.stdout or "[]")]
    except Exception:  # noqa: BLE001
        pass
    try:
        res["bandit"] = [{"archivo": Path(x["filename"]).as_posix().removeprefix("./"), "linea": x["line_number"], "regla": x["test_id"],
                          "severidad": x["issue_severity"], "mensaje": x["issue_text"][:150]} for x in json.loads(band.stdout or "{}").get("results", [])]
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(d, ignore_errors=True)
    _CACHE[k] = res
    return res


def handler_spans(files: dict[str, str]) -> dict[str, tuple[int, int]]:
    """Líneas (1-based, inclusivas) del cuerpo de cada handler en app/main.py: lo único escrito por el agente."""
    lines = files.get("app/main.py", "").splitlines(); spans = {}
    for i, l in enumerate(lines):
        m = re.match(r"def _(ep_\d{3})\(", l)
        if m:
            j = i + 1
            while j < len(lines) and (lines[j].startswith("    ") or not lines[j].strip()) and not lines[j].startswith("@app"):
                if not lines[j].strip() and j + 1 < len(lines) and not lines[j + 1].startswith("    "):
                    break
                j += 1
            spans["EP-" + m.group(1)[3:]] = (i + 2, j)
    return spans


def handler_code(files: dict[str, str]) -> dict[str, list[str]]:
    lines = files.get("app/main.py", "").splitlines()
    return {ep: [f"{n:4d}| {lines[n - 1]}" for n in range(a, b + 1)] for ep, (a, b) in handler_spans(files).items()}


def in_handlers(files: dict[str, str], archivo: str, linea: int) -> bool:
    return archivo == "app/main.py" and any(a <= linea <= b for a, b in handler_spans(files).values())


def numbered(files: dict[str, str]) -> dict[str, list[str]]:
    """Código con número de línea, para que code-review cite archivo y línea exactos."""
    return {f: [f"{i + 1:4d}| {l}" for i, l in enumerate(t.splitlines())] for f, t in files.items() if t}
