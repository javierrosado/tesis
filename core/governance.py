"""governance-agent determinista (F1.1). No usa un modelo de lenguaje: el veredicto sale de reglas
verificables, para que la trazabilidad (H5) y la coordinación (H6) no dependan del azar del modelo.

Reglas, en orden:
  1. Contrato   — el artefacto valida contra el JSON Schema del agente productor (bloqueante).
  2. F5         — cada criterio de verificación de la ficha del productor (bloqueante si falla),
                  con un detalle accionable que se devuelve como feedback en el reintento.
  3. Procedencia — provenance coherente con el requerimiento y el agente; knowledge_refs no vacío (mayor).
Veredicto: rechazado si hay hallazgos bloqueantes o mayores; aprobado en otro caso. El escalamiento
lo decide el orquestador al agotar las rondas (max_governance_rounds)."""
import jsonschema
from . import verify

POLICIES = ["contrato_json_schema", "criterios_f5", "procedencia_h5"]


def _f5_detail(agent_name: str, key: str, out: dict, ctx: dict, res: dict) -> tuple[str, str]:
    """Explica qué falta para cumplir el criterio, no solo el valor."""
    if agent_name == "domain-modeling-agent" and key == "ubiquitous_coverage":
        terms = {t.get("termino") for t in out.get("lenguaje_ubicuo", [])}
        miss = [e["nombre"] for e in out.get("entidades", []) if e.get("nombre") not in terms]
        return (f"Cada entidad debe tener una entrada en lenguaje_ubicuo con el mismo nombre exacto. "
                f"Faltan: {', '.join(miss) or '(ninguna entidad definida)'}", "lenguaje_ubicuo")
    if agent_name == "domain-modeling-agent" and key == "transitions_complete":
        evs = {e.get("nombre") for e in out.get("eventos", [])}
        miss = sorted({t.get("evento") for t in out.get("transiciones", []) if t.get("evento") not in evs})
        return f"Toda transición debe referir un evento declarado en eventos. No declarados: {', '.join(miss) or '(sin transiciones)'}", "transiciones"
    if agent_name == "ux-ui-copilot-agent" and key == "story_coverage":
        stories = [h["id"] for h in ctx.get("user_story_set", {}).get("historias", [])]
        cov = {s for p in out.get("pantallas", []) for s in p.get("historias", [])}
        return f"Cada historia debe estar cubierta por al menos una pantalla. Sin cubrir: {', '.join(s for s in stories if s not in cov)}", "pantallas[].historias"
    if agent_name == "product-analyst-agent" and key == "br_coverage":
        req = [b[:6] for b in ctx.get("business_request", {}).get("reglas_negocio", [])]
        got = {b for h in out.get("historias", []) for b in h.get("reglas_negocio", [])}
        return f"Toda regla de negocio del requerimiento debe estar en alguna historia. Faltan: {', '.join(b for b in req if b not in got)}", "historias[].reglas_negocio"
    if agent_name == "product-analyst-agent" and key == "gwt_ratio":
        bad = [h.get("id") for h in out.get("historias", []) if not any(all(len(c.get(k, "")) >= 5 for k in ("given", "when", "then")) for c in h.get("criterios", []))]
        return f"Cada historia necesita al menos un criterio Given/When/Then completo. Sin criterio válido: {', '.join(map(str, bad))}", "historias[].criterios"
    return f"{res['rule']} (valor actual {res['value']})", "<artefacto>"


def review(producer, artefact: dict, ctx: dict, round_: int) -> tuple[dict, bool, dict]:
    findings: list[dict] = []
    # 1. contrato
    errs = sorted(jsonschema.Draft202012Validator(producer.output_schema).iter_errors(artefact), key=lambda e: list(e.path))
    for e in errs[:10]:
        findings.append({"severidad": "bloqueante", "regla": "contrato_json_schema", "detalle": e.message[:300],
                         "ubicacion": "/".join(map(str, e.path)) or "<raíz>"})
    # 2. F5 (solo si el contrato es válido: las métricas asumen la estructura)
    ok_f5, f5 = (False, {}) if errs else verify.evaluate(producer, artefact, ctx, {"refinement_rounds": round_})
    for k, v in f5.items():
        if not v["ok"] and k != "refinement_rounds":
            detail, loc = _f5_detail(producer.name, k, artefact, ctx, v)
            findings.append({"severidad": "bloqueante", "regla": f"F5.{k}", "detalle": detail, "ubicacion": loc})
    # 3. procedencia
    prov = artefact.get("provenance", {}) if isinstance(artefact, dict) else {}
    if not errs:
        if prov.get("req_id") != ctx["req_id"]:
            findings.append({"severidad": "mayor", "regla": "procedencia_h5", "detalle": f"provenance.req_id debe ser {ctx['req_id']}", "ubicacion": "provenance.req_id"})
        if not producer.name.startswith(str(prov.get("agent", "")).replace("-agent", "")) or not prov.get("agent"):
            findings.append({"severidad": "mayor", "regla": "procedencia_h5", "detalle": f"provenance.agent debe identificar a {producer.name}", "ubicacion": "provenance.agent"})
        if not prov.get("knowledge_refs"):
            findings.append({"severidad": "mayor", "regla": "procedencia_h5", "detalle": "provenance.knowledge_refs vacío: cita los ids del conocimiento recuperado (BR-xxx, ADR-xxx)", "ubicacion": "provenance.knowledge_refs"})
    blocking = any(f["severidad"] in ("bloqueante", "mayor") for f in findings)
    verdict = {"req_id": ctx["req_id"], "artefacto": producer.spec.get("produces") or producer.name, "agente_evaluado": producer.name,
               "veredicto": "rechazado" if blocking else "aprobado", "hallazgos": findings, "politicas_aplicadas": POLICIES,
               "requiere_humano": bool(producer.gate), "provenance": {"contract_version": "1.0", "req_id": ctx["req_id"],
               "agent": "governance", "phase": prov.get("phase", "discovery") if prov.get("phase") in ("discovery", "arquitectura", "ingenieria", "calidad", "devops") else "discovery",
               "inputs": [producer.name], "knowledge_refs": POLICIES, "assumptions": []}}
    if producer.gate:
        verdict["rol_humano"] = producer.gate["role"]
    return verdict, (ok_f5 and not errs), f5
