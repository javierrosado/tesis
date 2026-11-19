"""Criterios F5 evaluados en código (no por el modelo). Cada función recibe el artefacto y el contexto y
devuelve métricas; `evaluate` compara contra las reglas de agent.yaml."""
import re


def metrics_product_analyst(out: dict, ctx: dict) -> dict:
    hs = out.get("historias", [])
    gwt = sum(1 for h in hs if any(all(len(c.get(k, "")) >= 5 for k in ("given", "when", "then")) for c in h.get("criterios", [])))
    brs_req = {b[:6] for b in ctx.get("business_request", {}).get("reglas_negocio", [])}
    brs_out = {b for h in hs for b in h.get("reglas_negocio", [])}
    return {"gwt_ratio": gwt / len(hs) if hs else 0.0,
            "br_coverage": (len(brs_req & brs_out) / len(brs_req)) if brs_req else 1.0}


def metrics_domain_modeling(out: dict, ctx: dict) -> dict:
    ents = {e["nombre"] for e in out.get("entidades", [])}
    terms = {t["termino"] for t in out.get("lenguaje_ubicuo", [])}
    evs = {e["nombre"] for e in out.get("eventos", [])}
    trs = out.get("transiciones", [])
    return {"ubiquitous_coverage": (len(ents & terms) / len(ents)) if ents else 0.0,
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
    ents = {e["nombre"] for e in ctx.get("domain_model", {}).get("entidades", [])}
    assigned = {e for c in out.get("componentes", []) for e in c.get("entidades", [])}
    comps = {c["id"] for c in out.get("componentes", [])}
    ints = out.get("integraciones", [])
    return {"adr_options": (sum(1 for a in adrs if len(a.get("opciones", [])) >= 2 and a.get("consecuencias")) / len(adrs)) if adrs else 0.0,
            "entity_coverage": (len(ents & assigned) / len(ents)) if ents else 1.0,
            "int_refs_valid": (sum(1 for i in ints if i["origen"] in comps and i["destino"] in comps) / len(ints)) if ints else 1.0}


def openapi_ok(text: str) -> bool:
    import yaml
    try:
        from openapi_spec_validator import validate
        doc = yaml.safe_load(text)
        if not isinstance(doc, dict) or not str(doc.get("openapi", "")).startswith("3.1"):
            return False
        validate(doc)
        return True
    except Exception:  # noqa: BLE001
        return False


def metrics_api_designer(out: dict, ctx: dict) -> dict:
    need = {i["id"] for i in ctx.get("solution_architecture", {}).get("integraciones", []) if i.get("tipo") in ("comando", "consulta")}
    eps = out.get("endpoints", [])
    got = {i for e in eps for i in e.get("integraciones", [])}
    errs = {e["id"] for e in out.get("errores", [])}; secs = {s["id"] for s in out.get("esquemas_seguridad", [])}
    refs_ok = sum(1 for e in eps if e["seguridad"] in secs and set(e.get("errores", [])) <= errs)
    return {"openapi_valid": openapi_ok(out.get("openapi_yaml", "")),
            "int_coverage": (len(need & got) / len(need)) if need else 1.0,
            "refs_declared": (refs_ok / len(eps)) if eps else 0.0}


def _criteria(ctx: dict) -> set:
    return {(h["id"], n) for h in ctx.get("user_story_set", {}).get("historias", []) for n in range(1, len(h.get("criterios", [])) + 1)}


def pytest_code_ok(code: str) -> bool:
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in ast.walk(tree))


def metrics_test_cases(out: dict, ctx: dict) -> dict:
    cases = out.get("casos", [])
    crit = _criteria(ctx); cov = {(c["historia"], c["criterio"]) for c in cases}
    eps = {e["id"] for e in ctx.get("api_design", {}).get("endpoints", [])}
    ints = [c for c in cases if c["tipo"] == "integracion"]
    return {"criteria_coverage": (len(crit & cov) / len(crit)) if crit else 0.0,
            "int_endpoints_valid": (sum(1 for c in ints if c.get("endpoint") in eps) / len(ints)) if ints else 1.0,
            "pytest_compiles": (sum(1 for c in cases if pytest_code_ok(c.get("codigo_pytest", ""))) / len(cases)) if cases else 0.0}


def workflow_ok(text: str) -> bool:
    import yaml
    try:
        doc = yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(doc, dict):
        return False
    on = doc.get("on", doc.get(True))           # PyYAML lee la clave `on` como True
    jobs = doc.get("jobs")
    return bool(on) and isinstance(jobs, dict) and bool(jobs) and all(
        isinstance(j, dict) and j.get("runs-on") and isinstance(j.get("steps"), list) and j["steps"] for j in jobs.values())


def metrics_cicd(out: dict, ctx: dict) -> dict:
    pipes = out.get("pipelines", [])
    prod = [p for p in pipes if p["ambiente"] == "prod"]
    return {"yaml_valid": (sum(1 for p in pipes if workflow_ok(p["yaml"])) / len(pipes)) if pipes else 0.0,
            "env_coverage": len({p["ambiente"] for p in pipes} & {"dev", "staging", "prod"}) / 3,
            "test_stage": (sum(1 for p in pipes if "pytest" in p["yaml"]) / len(pipes)) if pipes else 0.0,
            "prod_manual_gate": 1.0 if prod and all(any(g["etapa"] == "deploy" and g["tipo"] == "manual" for g in p["gates"]) for p in prod) else 0.0}


METRICS = {"product-analyst-agent": metrics_product_analyst, "domain-modeling-agent": metrics_domain_modeling,
           "ux-ui-copilot-agent": metrics_ux, "governance-agent": metrics_governance,
           "solution-architect-agent": metrics_solution_architect, "api-designer-agent": metrics_api_designer,
           "test-case-generator-agent": metrics_test_cases, "cicd-pipeline-agent": metrics_cicd}

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
