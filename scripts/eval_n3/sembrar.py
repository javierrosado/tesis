#!/usr/bin/env python3
"""eval_n3 · paso 4: defectos sembrados sobre el servicio limpio de cada caso (una variante por defecto).

- Lógica: operadores de mutación al estilo de mutmut (comparaciones, operadores aritméticos y booleanos, constantes,
  `return` y condiciones), aplicados SOLO a las líneas de los handlers. Se reimplementan sobre el AST de cada línea porque
  mutmut muta el archivo completo (incluidos el marco, las semillas y el catálogo de errores, que no escribe el modelo).
  Un mutante entra solo si las pruebas de aceptación del caso lo detectan (mutante "muerto"): es un defecto de
  comportamiento real.
- Seguridad: patrones OWASP/bandit insertados en un handler sin cambiar su comportamiento (las pruebas de aceptación
  siguen pasando) y que bandit detecta en el código sembrado.

  python scripts/eval_n3/sembrar.py --caso <carpeta del caso> [--logica 3 --seguridad 2]
Escribe <caso>/defectos/Dnn.json con {id, tipo, origen, endpoint, linea_handler, descripcion, severidad, cwe, owasp,
backend_code (variante completa)}."""
import argparse, ast, copy, hashlib, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.tools import sandbox   # noqa: E402

CMP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
       ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
BOOL = {ast.And: ast.Or, ast.Or: ast.And}

SEGURIDAD = [  # (id, descripción, cwe, owasp, bandit, líneas a insertar al inicio del handler)
    ("SEC-SECRETO", "Credencial escrita en el código", "CWE-798", "A07", "B105",
     ["_clave_servicio = 'sk_live_9f3a7c21e4b84d0fa6'", "_ = _clave_servicio"]),
    ("SEC-EVAL", "Evaluación dinámica de un valor de la petición con eval()", "CWE-95", "A03", "B307",
     ["_eco = eval(repr({param}))"]),
    ("SEC-HASH", "Hash débil (MD5) usado para un identificador", "CWE-328", "A02", "B324",
     ["import hashlib as _h", "_huella = _h.md5(str({param}).encode()).hexdigest()"]),
    ("SEC-SQL", "Consulta SQL armada concatenando un valor de la petición", "CWE-89", "A03", "B608",
     ["_consulta = \"SELECT * FROM registros WHERE id = '\" + str({param}) + \"'\"", "_ = _consulta"]),
    ("SEC-SHELL", "Comando del sistema con shell=True armado con un valor de la petición", "CWE-78", "A03", "B602",
     ["import subprocess as _sp", "_ = _sp.run('echo ' + str({param}), shell=True, capture_output=True)"]),
]


class _Mutador(ast.NodeTransformer):
    """Aplica la k-ésima mutación posible de una línea (o cuenta cuántas hay con k=None)."""

    def __init__(self, k):
        self.k, self.n, self.hecho = k, 0, None

    def _toca(self, desc):
        self.n += 1
        if self.k is not None and self.n - 1 == self.k:
            self.hecho = desc
            return True
        return False

    def visit_Compare(self, node):
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            if type(op) in CMP and self._toca(f"{type(op).__name__} → {CMP[type(op)].__name__}"):
                node.ops[i] = CMP[type(op)]()
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if type(node.op) in BIN and self._toca(f"{type(node.op).__name__} → {BIN[type(node.op)].__name__}"):
            node.op = BIN[type(node.op)]()
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if type(node.op) in BOOL and self._toca(f"{type(node.op).__name__} → {BOOL[type(node.op)].__name__}"):
            node.op = BOOL[type(node.op)]()
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, bool) and self._toca(f"{node.value} → {not node.value}"):
            return ast.copy_location(ast.Constant(not node.value), node)
        if type(node.value) is int and self._toca(f"{node.value} → {node.value + 1}"):
            return ast.copy_location(ast.Constant(node.value + 1), node)
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._toca("not x → x"):
            return node.operand
        return node


def _mutar_linea(linea: str, k):
    """Devuelve (línea mutada, descripción) o (n_posibles, None) si k es None."""
    txt = linea.strip()
    sufijo = ":" if txt.endswith(":") else ""
    cuerpo = txt[:-1] if sufijo else txt
    for pref in ("if ", "elif ", "while ", "return ", "for "):
        if cuerpo.startswith(pref) and pref != "for ":
            expr, cab = cuerpo[len(pref):], pref
            break
    else:
        expr, cab = cuerpo, ""
    try:
        arbol = ast.parse(expr, mode="eval" if cab else "exec")
    except SyntaxError:
        return (0, None) if k is None else (None, None)
    m = _Mutador(k)
    nuevo = m.visit(copy.deepcopy(arbol))
    if k is None:
        return m.n, None
    if not m.hecho:
        return None, None
    sangria = linea[:len(linea) - len(linea.lstrip())]
    return sangria + cab + ast.unparse(nuevo) + sufijo, m.hecho


def _pruebas_pasan(ctx, backend) -> tuple[int, int]:
    files = sandbox.render_app(ctx["api_design"], ctx["data_model"], backend)
    rt = sandbox.run_tests(files, ctx["pruebas_aceptacion"])
    return rt["passed"], rt["collected"]


def _bandit(ctx, backend) -> set[str]:
    files = sandbox.render_app(ctx["api_design"], ctx["data_model"], backend)
    return {x.get("regla") or x.get("test_id") or x.get("codigo") for x in sandbox.static_analysis(files)["bandit"]}


def sembrar(caso: Path, n_logica=3, n_seguridad=2, semilla=2027) -> list[dict]:
    ctx = {k: json.loads((caso / f).read_text(encoding="utf-8")) for k, f in
           (("api_design", "pipeline_v1/api_design.json"), ("data_model", "pipeline_v1/data_model.json"),
            ("servicio", "servicio_limpio.json"), ("pruebas_aceptacion", "pruebas_aceptacion.json"))}
    limpio = ctx["servicio"]
    ok, tot = _pruebas_pasan(ctx, limpio)
    if ok != tot or tot == 0:
        raise SystemExit(f"{caso.name}: el servicio limpio no pasa sus pruebas ({ok}/{tot})")
    rng = random.Random(int(hashlib.sha256(f"{semilla}:{caso.name}".encode()).hexdigest()[:8], 16))
    candidatos = [(hi, li, k) for hi, h in enumerate(limpio["handlers"]) for li, l in enumerate(h["lineas"])
                  for k in range(_mutar_linea(l, None)[0])]
    rng.shuffle(candidatos)
    defectos, base_bandit = [], _bandit(ctx, limpio)
    for hi, li, k in candidatos:
        if sum(d["tipo"] == "logica" for d in defectos) >= n_logica:
            break
        if any(d["tipo"] == "logica" and d["endpoint"] == limpio["handlers"][hi]["endpoint"] and d["linea_handler"] == li + 1 for d in defectos):
            continue
        nueva, desc = _mutar_linea(limpio["handlers"][hi]["lineas"][li], k)
        if not nueva:
            continue
        var = copy.deepcopy(limpio); var["handlers"][hi]["lineas"][li] = nueva
        try:
            ok2, tot2 = _pruebas_pasan(ctx, var)
        except Exception:  # noqa: BLE001
            continue
        if ok2 < tot2:                                    # mutante muerto: defecto de comportamiento real
            defectos.append({"tipo": "logica", "origen": "mutacion (operadores de mutmut)", "endpoint": limpio["handlers"][hi]["endpoint"],
                             "linea_handler": li + 1, "descripcion": f"Mutación {desc}: «{limpio['handlers'][hi]['lineas'][li].strip()}» → «{nueva.strip()}»",
                             "severidad": "mayor", "pruebas_que_fallan": tot2 - ok2, "backend_code": var})
    patrones = SEGURIDAD[:]; rng.shuffle(patrones)
    for sid, desc, cwe, owasp, regla, plantilla in patrones:
        if sum(d["tipo"] == "seguridad" for d in defectos) >= n_seguridad:
            break
        firmas = sandbox.signatures(ctx["api_design"])
        for hi in rng.sample(range(len(limpio["handlers"])), len(limpio["handlers"])):
            h = limpio["handlers"][hi]
            params = [p.split(":")[0].strip() for p in firmas.get(h["endpoint"], "").split("(", 1)[-1].rstrip("):").split(",") if p.strip()]
            if not params:
                continue
            var = copy.deepcopy(limpio)
            var["handlers"][hi]["lineas"] = [l.format(param=params[0]) for l in plantilla] + h["lineas"]
            try:
                ok2, tot2 = _pruebas_pasan(ctx, var)
                det = _bandit(ctx, var) - base_bandit
            except Exception:  # noqa: BLE001
                continue
            if ok2 == tot2 and det:
                defectos.append({"tipo": "seguridad", "origen": f"patrón OWASP/bandit ({regla})", "endpoint": h["endpoint"], "linea_handler": 1,
                                 "descripcion": desc, "severidad": "critico", "cwe": cwe, "owasp": owasp, "id_patron": sid,
                                 "bandit_detecta": sorted(det), "backend_code": var})
                break
    d = caso / "defectos"; d.mkdir(exist_ok=True)
    for i, x in enumerate(defectos, 1):
        x["id"] = f"D{i:02d}"
        (d / f"{x['id']}.json").write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
    return defectos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caso", required=True); ap.add_argument("--logica", type=int, default=3); ap.add_argument("--seguridad", type=int, default=2)
    a = ap.parse_args()
    ds = sembrar(Path(a.caso), a.logica, a.seguridad)
    print(json.dumps([{k: v for k, v in x.items() if k != "backend_code"} for x in ds], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
