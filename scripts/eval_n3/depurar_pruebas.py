#!/usr/bin/env python3
"""eval_n3 · paso 3b: depura las pruebas de aceptación de referencia para que solo exijan lo que la entrada fija.

Humo 6b073c94 (25/11/2026): los 4 modelos pasaron solo el 12–19 % de las pruebas de referencia. 42 de 96 fallos venían de
una convención del generador de referencias (detail = id del catálogo, p. ej. 'ERR-101'), que el prompt del backend del
pipeline no pide, y otros de literales que la entrada no especifica ('ENVIADO', el formato del cursor). Una prueba así mide
el parecido con la referencia, no el cumplimiento del diseño.

Regla (por cada `assert` de cada prueba):
- se quita si compara o busca un id del catálogo de errores (`ERR-nnn`);
- se quita si compara contra un texto literal que no aparece en la entrada del backend (diseño de API, modelo de datos y
  firmas), ni entre los identificadores de las semillas de referencia, ni en el resto de la misma prueba (p. ej. el
  payload que envía).
Se conservan los asserts de código de estado, de estructura y de efectos en la base. Una prueba sin asserts sale.
El caso queda si el servicio limpio pasa todas las pruebas depuradas y quedan al menos 4. Los mutantes de lógica se
vuelven a evaluar: el que ya no muere con las pruebas depuradas queda marcado `muerto_por_pruebas: false` (sigue siendo un
defecto para code-review, pero ya no aparece en el reporte de pruebas).

  python scripts/eval_n3/depurar_pruebas.py --casos <carpeta con los casos>
Escribe por caso pruebas_aceptacion.json (depuradas), pruebas_aceptacion.v0.json (originales) y depuracion.json."""
import argparse, ast, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.tools import sandbox   # noqa: E402

ERR = re.compile(r"\bERR-\d+\b")


def _textos_valor(expr: ast.AST) -> list[str]:
    """Constantes de texto usadas como valor (no como clave de un subíndice: data['estado'] → 'estado' es nombre de campo)."""
    claves = {id(n.slice) for n in ast.walk(expr) if isinstance(n, ast.Subscript)}
    return [n.value for n in ast.walk(expr) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in claves]


def depurar_suite(lineas: list[str], permitido: str) -> tuple[list[str], dict]:
    arbol = ast.parse("\n".join(lineas))
    quitados = {"err": 0, "literal": 0, "pruebas_sin_asserts": 0}
    cuerpo = []
    for nodo in arbol.body:
        if not (isinstance(nodo, ast.FunctionDef) and nodo.name.startswith("test")):
            cuerpo.append(nodo); continue
        en_asserts = {id(n) for a in ast.walk(nodo) if isinstance(a, ast.Assert) for n in ast.walk(a)}
        propios = " ".join(n.value for n in ast.walk(nodo) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                           and id(n) not in en_asserts)

        class Filtro(ast.NodeTransformer):
            def visit_Assert(self, a):
                ts = _textos_valor(a.test)
                if any(ERR.search(t) for t in ts):
                    quitados["err"] += 1; return None
                if any(t and t not in permitido and t not in propios for t in ts):
                    quitados["literal"] += 1; return None
                return a
        nuevo = Filtro().visit(nodo)
        for n in ast.walk(nuevo):                   # un if/for/with que se quedó sin cuerpo al quitar sus asserts
            for campo in ("body", "orelse", "finalbody"):
                if campo == "body" and isinstance(getattr(n, campo, None), list) and not getattr(n, campo) and not isinstance(n, ast.Module):
                    setattr(n, campo, [ast.Pass()])
        if not any(isinstance(n, ast.Assert) for n in ast.walk(nuevo)):
            quitados["pruebas_sin_asserts"] += 1; continue
        if not nuevo.body:
            nuevo.body = [ast.Pass()]
        cuerpo.append(nuevo)
    arbol.body = cuerpo
    return ast.unparse(ast.fix_missing_locations(arbol)).splitlines(), quitados


def depurar_caso(caso: Path) -> dict:
    ent = json.loads((caso / "entradas" / "backend-developer-agent.json").read_text(encoding="utf-8"))
    limpio = json.loads((caso / "servicio_limpio.json").read_text(encoding="utf-8"))
    v0p = caso / "pruebas_aceptacion.v0.json"
    orig = json.loads((v0p if v0p.exists() else caso / "pruebas_aceptacion.json").read_text(encoding="utf-8"))
    # de las semillas de referencia solo valen los identificadores (la prueba busca registros por id); sus otros valores
    # ('ENVIADO', montos, fechas) los fija la referencia, no la entrada
    ids = [str(v) for t in limpio.get("semillas", []) for f in t.get("filas", []) for k, v in f.items()
           if k == "id" or k.endswith("_id") or k.endswith("Id")]
    permitido = json.dumps(ent, ensure_ascii=False) + " ".join(ids)
    suites, tot = [], {"err": 0, "literal": 0, "pruebas_sin_asserts": 0}
    for s in orig["suites"]:
        lineas, q = depurar_suite(s["lineas"], permitido)
        tot = {k: tot[k] + q[k] for k in tot}
        suites.append({**s, "lineas": lineas})
    nuevas = {**orig, "suites": suites}
    files = sandbox.render_app(ent["api_design"], ent["data_model"], limpio)
    rt = sandbox.run_tests(files, nuevas)
    rep = {"caso": caso.name, "quitados": tot, "pruebas": rt["collected"], "pasan_limpio": rt["passed"],
           "valido": rt["collected"] >= 4 and rt["passed"] == rt["collected"]}
    if not rep["valido"]:
        rep["fallos"] = [f"{f['prueba']}: {f['detalle'][:200]}" for f in rt["fallos"][:5]]
        return rep
    if not v0p.exists():
        v0p.write_text(json.dumps(orig, ensure_ascii=False, indent=1), encoding="utf-8")
    (caso / "pruebas_aceptacion.json").write_text(json.dumps(nuevas, ensure_ascii=False, indent=1), encoding="utf-8")
    vivos = 0
    for f in sorted((caso / "defectos").glob("D*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("tipo") != "logica":
            continue
        r2 = sandbox.run_tests(sandbox.render_app(ent["api_design"], ent["data_model"], d["backend_code"]), nuevas)
        d["muerto_por_pruebas"] = r2["passed"] < r2["collected"]
        vivos += not d["muerto_por_pruebas"]
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    rep["mutantes_vivos"] = vivos
    (caso / "depuracion.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--casos", required=True)
    a = ap.parse_args()
    res = [depurar_caso(c) for c in sorted(Path(a.casos).iterdir()) if (c / "servicio_limpio.json").exists()]
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
