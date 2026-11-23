"""Criterios F5 evaluados en código (no por el modelo). Cada función recibe el artefacto y el contexto y
devuelve métricas; `evaluate` compara contra las reglas de agent.yaml."""
import re, unicodedata


def metrics_product_analyst(out: dict, ctx: dict) -> dict:
    hs = out.get("historias", [])
    gwt = sum(1 for h in hs if any(all(len(c.get(k, "")) >= 5 for k in ("given", "when", "then")) for c in h.get("criterios", [])))
    brs_req = {b[:6] for b in ctx.get("business_request", {}).get("reglas_negocio", [])}
    brs_out = {b for h in hs for b in h.get("reglas_negocio", [])}
    return {"gwt_ratio": gwt / len(hs) if hs else 0.0,
            "br_coverage": (len(brs_req & brs_out) / len(brs_req)) if brs_req else 1.0}


def norm(t: str) -> str:
    """Compara nombres sin distinguir mayúsculas, tildes, espacios ni guiones (Zona de entrega == ZonaEntrega)."""
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def metrics_domain_modeling(out: dict, ctx: dict) -> dict:
    ents = {norm(e["nombre"]) for e in out.get("entidades", [])}
    terms = {norm(t["termino"]) for t in out.get("lenguaje_ubicuo", [])}
    evs = {e["nombre"] for e in out.get("eventos", [])}
    trs = out.get("transiciones", [])
    covered = {e for e in ents if any(e == t or (len(e) >= 4 and e in t) for t in terms)}   # "Pedido" ⊂ "Pedido de campaña"
    return {"ubiquitous_coverage": (len(covered) / len(ents)) if ents else 0.0,
            "transitions_complete": (sum(1 for t in trs if t["evento"] in evs) / len(trs)) if trs else 0.0}


def metrics_ux(out: dict, ctx: dict) -> dict:
    stories = {h["id"] for h in ctx.get("user_story_set", {}).get("historias", [])}
    covered = {s for p in out.get("pantallas", []) for s in p.get("historias", [])}
    return {"story_coverage": (len(stories & covered) / len(stories)) if stories else 0.0,
            "error_states": len(out.get("estados_vacios_error", []))}


def metrics_governance(out: dict, ctx: dict) -> dict:
    major = [h for h in out.get("hallazgos", []) if h["severidad"] in ("bloqueante", "mayor")]
    return {"findings_actionable": (sum(1 for h in major if h.get("ubicacion")) / len(major)) if major else 1.0}


def metrics_solution_architect(out: dict, ctx: dict) -> dict:
    adrs = out.get("adrs", [])
    ents = {norm(e["nombre"]) for e in ctx.get("domain_model", {}).get("entidades", [])}
    assigned = {norm(e) for c in out.get("componentes", []) for e in c.get("entidades", [])}
    comps = {c["id"] for c in out.get("componentes", [])}
    ints = out.get("integraciones", [])
    return {"adr_options": (sum(1 for a in adrs if len(a.get("opciones", [])) >= 2 and a.get("consecuencias")) / len(adrs)) if adrs else 0.0,
            "entity_coverage": (len(ents & assigned) / len(ents)) if ents else 1.0,
            "int_refs_valid": (sum(1 for i in ints if i["origen"] in comps and i["destino"] in comps and i["origen"] != i["destino"]) / len(ints)) if ints else 1.0}


def openapi_errors(design: dict) -> list[str]:
    """Valida el OpenAPI 3.1 renderizado y la coherencia de parámetros de ruta."""
    from openapi_spec_validator import validate
    from .render import openapi_from_design
    errs = []
    for ep in design.get("endpoints", []):
        declared = {p["nombre"] for p in ep.get("parametros", []) if p["en"] == "path"}
        used = set(re.findall(r"{([^}]+)}", ep["ruta"]))
        if used != declared:
            errs.append(f"{ep['id']}: parámetros de ruta {sorted(used)} y declarados en path {sorted(declared)} no coinciden")
        for n in [ep.get("cuerpo")] + [r.get("esquema") for r in ep.get("respuestas", [])]:
            if n and n not in {s["nombre"] for s in design.get("esquemas", [])}:
                errs.append(f"{ep['id']}: el esquema {n} no está declarado en esquemas")
    for ep in design.get("endpoints", []):
        for r in ep.get("respuestas", []):
            if r["status"] == 204 and r.get("esquema"):
                errs.append(f"{ep['id']}: la respuesta 204 no lleva cuerpo; quita el esquema {r['esquema']}")
    seen = {}
    for ep in design.get("endpoints", []):
        k = (ep["ruta"], ep["metodo"])
        if k in seen:
            errs.append(f"{ep['id']}: duplica {ep['metodo']} {ep['ruta']} de {seen[k]}")
        seen[k] = ep["id"]
    try:
        validate(openapi_from_design(design))
    except Exception as e:  # noqa: BLE001
        errs.append(f"OpenAPI 3.1 inválido: {str(e).splitlines()[0][:200]}")
    return errs


def metrics_api_designer(out: dict, ctx: dict) -> dict:
    need = {i["id"] for i in ctx.get("solution_architecture", {}).get("integraciones", []) if i.get("tipo") in ("comando", "consulta")}
    eps = out.get("endpoints", [])
    got = {i for e in eps for i in e.get("integraciones", [])}
    errs = {e["id"] for e in out.get("errores", [])}; secs = {s["id"] for s in out.get("esquemas_seguridad", [])}
    refs_ok = sum(1 for e in eps if e["seguridad"] in secs and set(e.get("errores", [])) <= errs)
    return {"openapi_valid": not openapi_errors(out),
            "int_coverage": (len(need & got) / len(need)) if need else 1.0,
            "refs_declared": (refs_ok / len(eps)) if eps else 0.0}


def _criteria(ctx: dict) -> set:
    return {(h["id"], n) for h in ctx.get("user_story_set", {}).get("historias", []) for n in range(1, len(h.get("criterios", [])) + 1)}


def _strip_code_fences(code: str) -> str:
    t = code.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t


def code_text(code) -> str:
    """codigo_pytest llega como lista de líneas (contrato v1.1) o como texto (compatibilidad)."""
    return "\n".join(code) if isinstance(code, list) else str(code or "")


def pytest_code_ok(code) -> bool:
    import ast, textwrap
    code = code_text(code)
    try:
        tree = ast.parse(textwrap.dedent(_strip_code_fences(code)))
    except SyntaxError:
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_") for n in ast.walk(tree))


def metrics_test_cases(out: dict, ctx: dict) -> dict:
    cases = out.get("casos", [])
    crit = _criteria(ctx); cov = {(c["historia"], c["criterio"]) for c in cases}
    eps = {e["id"] for e in ctx.get("api_design", {}).get("endpoints", [])}
    ints = [c for c in cases if c["tipo"] == "integracion"]
    return {"criteria_coverage": (len(crit & cov) / len(crit)) if crit else 0.0,
            "int_endpoints_valid": (sum(1 for c in ints if c.get("endpoint") in eps) / len(ints)) if ints else 1.0,
            "pytest_compiles": (sum(1 for c in cases if pytest_code_ok(c.get("codigo_pytest", ""))) / len(cases)) if cases else 0.0}


# Acciones de GitHub verificadas (existen y se usan en la organización). Cualquier otra se rechaza.
ALLOWED_ACTIONS = {"actions/checkout", "actions/setup-python", "actions/setup-node", "actions/setup-java", "actions/cache",
                   "actions/upload-artifact", "actions/download-artifact", "docker/setup-buildx-action", "docker/login-action",
                   "docker/build-push-action", "aquasecurity/trivy-action"}


def workflow_errors(p: dict) -> list[str]:
    """Valida el workflow renderizado: jobs únicos, needs a jobs existentes y sin ciclos, cada paso con run o uses."""
    import yaml
    from .render import workflow_yaml
    errs, ids = [], [j["id"] for j in p.get("jobs", [])]
    if len(ids) != len(set(ids)):
        errs.append(f"{p['id']}: ids de job repetidos")
    for j in p.get("jobs", []):
        for n in j.get("needs", []):
            if n not in ids or n == j["id"]:
                errs.append(f"{p['id']}/{j['id']}: needs '{n}' no es otro job del pipeline")
        # Regla v2 (la usada para entrenar y evaluar el LoRA de cicd en F3): solo el job de pytest. El checkout del resto de jobs
        # lo añade el empaquetado del despliegue como adaptación determinista registrada (core/deploy.py, needs_checkout).
        if any("pytest" in (s.get("run") or "") for s in j["steps"]) and not any((s.get("uses") or "").startswith("actions/checkout@") for s in j["steps"]):
            errs.append(f"{p['id']}/{j['id']}: el job que ejecuta pytest debe hacer checkout del código en sus propios pasos (cada job corre en una máquina nueva)")
        for s in j["steps"]:
            if s.get("uses") and s["uses"].split("@")[0] not in ALLOWED_ACTIONS:
                errs.append(f"{p['id']}/{j['id']}: la acción {s['uses']} no está en la lista verificada ({', '.join(sorted(ALLOWED_ACTIONS))})")
            if bool(s.get("run")) == bool(s.get("uses")):
                errs.append(f"{p['id']}/{j['id']}: el paso '{s['nombre']}' debe tener run o uses (uno solo)")
    deps = {j["id"]: set(j.get("needs", [])) for j in p.get("jobs", [])}
    done = set()
    while True:
        ready = {k for k, v in deps.items() if k not in done and v <= done}
        if not ready:
            break
        done |= ready
    if len(done) < len(deps):
        errs.append(f"{p['id']}: dependencias needs con ciclo")
    try:
        doc = yaml.safe_load(workflow_yaml(p))
        assert doc.get("on", doc.get(True)) and doc["jobs"]
    except Exception as e:  # noqa: BLE001
        errs.append(f"{p['id']}: YAML no serializable ({e})")
    return errs


def workflow_ok(p: dict) -> bool:
    return not workflow_errors(p)


def _runs(p: dict) -> str:
    return " ".join(s.get("run", "") for j in p.get("jobs", []) for s in j["steps"])


def metrics_cicd(out: dict, ctx: dict) -> dict:
    pipes = out.get("pipelines", [])
    prod = [p for p in pipes if p["ambiente"] == "prod"]
    return {"yaml_valid": (sum(1 for p in pipes if workflow_ok(p)) / len(pipes)) if pipes else 0.0,
            "env_coverage": len({p["ambiente"] for p in pipes} & {"dev", "staging", "prod"}) / 3,
            "test_stage": (sum(1 for p in pipes if "pytest" in _runs(p)) / len(pipes)) if pipes else 0.0,
            "prod_manual_gate": 1.0 if prod and all(any(g["etapa"] == "deploy" and g["tipo"] == "manual" for g in p["gates"]) for p in prod) else 0.0}


# ---------------------------------------------------------------- F4: agentes con verificación por ejecución real
def metrics_security(out: dict, ctx: dict) -> dict:
    secs = {r["id"] for r in ctx.get("solution_architecture", {}).get("requisitos_seguridad", [])}
    comps = {c["id"] for c in ctx.get("solution_architecture", {}).get("componentes", [])}
    covered = {r for c in out.get("controles", []) for r in c.get("requisitos", [])}
    ctrls = out.get("controles", [])
    return {"sec_coverage": (len(secs & covered) / len(secs)) if secs else 1.0,
            "comps_valid": (sum(1 for c in ctrls if set(c["aplica_a"]) <= comps) / len(ctrls)) if ctrls else 0.0}


def metrics_data_model(out: dict, ctx: dict) -> dict:
    from .tools.sandbox import ddl_check
    ents = {norm(e["nombre"]) for e in ctx.get("domain_model", {}).get("entidades", [])}
    got = {norm(t["entidad"]) for t in out.get("tablas", [])} | {norm(t["nombre"]) for t in out.get("tablas", [])}
    cols = [c for t in out.get("tablas", []) for c in t["columnas"]]
    pii = [c for c in cols if c["pii"]]
    return {"entity_coverage": (len({e for e in ents if any(e == g or e in g for g in got)}) / len(ents)) if ents else 1.0,
            "ddl_ok": ddl_check(out)["ok"] and all(any(c["pk"] for c in t["columnas"]) for t in out.get("tablas", [])),
            "pii_protected": (sum(1 for c in pii if c["enmascarado"]) / len(pii)) if pii else 1.0}


def app_files(ctx: dict, backend: dict | None = None) -> dict:
    from .tools.sandbox import render_app
    return render_app(ctx.get("api_design", {}), ctx.get("data_model", {}), backend if backend is not None else ctx.get("backend_code", {}))


def metrics_backend(out: dict, ctx: dict) -> dict:
    from .tools.sandbox import smoke
    eps = [e["id"] for e in ctx.get("api_design", {}).get("endpoints", [])]
    hs = {h["endpoint"] for h in out.get("handlers", [])}
    sm = smoke(app_files(ctx, out), ctx.get("api_design", {}))
    res = sm.get("resultados", [])
    nested = any(l.lstrip().startswith(("def ", "async def ", "import ", "from ")) and not l.startswith(" ") for h in out.get("handlers", []) for l in h["lineas"])
    return {"compiles": bool(sm.get("import_ok")) and not nested,
            "routes_coverage": (len(set(eps) & hs) / len(eps)) if eps else 0.0,
            "smoke_ok": (sum(1 for r in res if r["status"] < 500) / len(res)) if res else 0.0}


def metrics_qa(out: dict, ctx: dict) -> dict:
    from .tools.sandbox import run_tests
    tcs = {c["id"] for c in ctx.get("test_cases", {}).get("casos", [])}
    got = {c for s in out.get("suites", []) for c in s.get("casos", [])}
    rt = run_tests(app_files(ctx), out)
    propios = [f for f in rt["fallos"] if QA_OWN_ERROR.search(f["detalle"])]   # la prueba falla por su propio código, no por el servicio
    return {"tc_coverage": (len(tcs & got) / len(tcs)) if tcs else 1.0, "suite_runs": rt["suite_runs"] and rt["errors"] == 0 and not propios, "pass_rate": rt["pass_rate"]}


USES_REPO = re.compile(r"pytest|\./|requirements|deploy|uvicorn|python ")


def needs_checkout(job: dict) -> bool:
    """El job usa archivos del repositorio pero no los descarga (cada job de GitHub Actions corre en una máquina nueva)."""
    return any(USES_REPO.search(s.get("run") or "") for s in job.get("steps", [])) and not any((s.get("uses") or "").startswith("actions/checkout@") for s in job.get("steps", []))


QA_OWN_ERROR = re.compile(r"ModuleNotFoundError|ImportError|NameError|SyntaxError|fixture '[^']+' not found")


def quality_facts(ctx: dict) -> dict:
    """Hechos objetivos de calidad del requerimiento (pruebas reales + hallazgos críticos)."""
    from .tools.sandbox import run_tests
    from .tools.sandbox import in_handlers
    files = app_files(ctx)
    rt = run_tests(files, ctx.get("qa_suite", {})) if ctx.get("qa_suite") else {"failed": 0, "errors": 0, "collected": 0}
    crit = [h for h in ctx.get("code_review", {}).get("hallazgos", []) if h["severidad"] == "critico" and in_handlers(files, h["archivo"], h["linea"])]
    return {"pruebas_fallidas": rt.get("failed", 0) + rt.get("errors", 0), "pruebas_total": rt.get("collected", 0), "criticos": len(crit)}


def metrics_code_review(out: dict, ctx: dict) -> dict:
    from .tools.sandbox import static_analysis, run_tests, in_handlers
    files = app_files(ctx)
    sa = static_analysis(files)
    serious = {(b["archivo"], b["linea"]) for b in sa["bandit"] if b["severidad"] in ("HIGH", "MEDIUM") and in_handlers(files, b["archivo"], b["linea"])}
    found = {(h["archivo"], h["linea"]) for h in out.get("hallazgos", [])}
    rt = run_tests(files, ctx.get("qa_suite", {})) if ctx.get("qa_suite") else {"failed": 0, "errors": 0}
    hs = out.get("hallazgos", [])
    must_change = any(h["severidad"] == "critico" for h in hs) or (rt.get("failed", 0) + rt.get("errors", 0)) > 0
    return {"findings_in_handlers": (sum(1 for h in hs if in_handlers(files, h["archivo"], h["linea"])) / len(hs)) if hs else 1.0,
            "bandit_covered": (len(serious & found) / len(serious)) if serious else 1.0,
            "verdict_consistent": 1.0 if (out.get("veredicto") == "cambios_requeridos") == must_change else 0.0}


def metrics_release(out: dict, ctx: dict) -> dict:
    from . import calendario
    r = out.get("release", {})
    window_ok = calendario.ventana_valida(r.get("ventana", ""), ctx.get("hoy") or calendario.hoy_lima(), ctx.get("calendario"))
    q = quality_facts(ctx)
    facts_ok = q["pruebas_fallidas"] == 0 and q["criticos"] == 0 and q["pruebas_total"] > 0
    go = r.get("decision") == "go"
    checklist_ok = all(c["cumple"] for c in r.get("checklist", []))
    return {"window_valid": window_ok, "decision_consistent": go == (facts_ok and checklist_ok) and not (go and not facts_ok)}


METRICS = {"product-analyst-agent": metrics_product_analyst, "domain-modeling-agent": metrics_domain_modeling,
           "ux-ui-copilot-agent": metrics_ux, "governance-agent": metrics_governance,
           "solution-architect-agent": metrics_solution_architect, "api-designer-agent": metrics_api_designer,
           "test-case-generator-agent": metrics_test_cases, "cicd-pipeline-agent": metrics_cicd,
           "security-compliance-agent": metrics_security, "data-model-agent": metrics_data_model, "backend-developer-agent": metrics_backend,
           "qa-automation-agent": metrics_qa, "code-review-agent": metrics_code_review, "release-manager-agent": metrics_release}

_RULE = re.compile(r"^(\w+)\s*(==|>=|<=|>|<)\s*([\d.]+|true|false)$")


def evaluate(agent, out: dict, ctx: dict, extra: dict) -> tuple[bool, dict]:
    m = {"schema_valid": True, **extra, **METRICS.get(agent.name, lambda o, c: {})(out, ctx)}
    results = {}
    for v in agent.verification:
        mm = _RULE.match(v["rule"].strip())
        if not mm:
            raise ValueError(f"regla no parseable: {v['rule']}")
        name, op, val = mm.groups()
        val = {"true": 1.0, "false": 0.0}.get(val, None) if val in ("true", "false") else float(val)
        cur = float(m.get(name, 0))
        ok = {"==": cur == val, ">=": cur >= val, "<=": cur <= val, ">": cur > val, "<": cur < val}[op]
        results[v["id"]] = {"ok": ok, "value": m.get(name), "rule": v["rule"]}
    return all(r["ok"] for r in results.values()), results
