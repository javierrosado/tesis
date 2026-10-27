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


METRICS = {"product-analyst-agent": metrics_product_analyst, "domain-modeling-agent": metrics_domain_modeling,
           "ux-ui-copilot-agent": metrics_ux, "governance-agent": metrics_governance}

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
