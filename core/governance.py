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
        terms = {verify.norm(t.get("termino", "")) for t in out.get("lenguaje_ubicuo", [])}
        miss = [e["nombre"] for e in out.get("entidades", []) if not any(verify.norm(e.get("nombre", "")) == t or verify.norm(e.get("nombre", "")) in t for t in terms)]
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
    if agent_name == "solution-architect-agent" and key == "entity_coverage":
        ents = [e["nombre"] for e in ctx.get("domain_model", {}).get("entidades", [])]
        got = {verify.norm(e) for c in out.get("componentes", []) for e in c.get("entidades", [])}
        ents = [e for e in ents if verify.norm(e) not in got]
        return f"Toda entidad del modelo de dominio debe estar en componentes[].entidades con su nombre exacto. Faltan: {', '.join(ents)}", "componentes[].entidades"
    if agent_name == "solution-architect-agent" and key == "int_refs_valid":
        comps = {c["id"] for c in out.get("componentes", [])}
        bad = [i["id"] for i in out.get("integraciones", []) if i["origen"] not in comps or i["destino"] not in comps]
        bad += [i["id"] for i in out.get("integraciones", []) if i["origen"] == i["destino"] and i["id"] not in bad]
        return f"origen y destino deben ser ids COMP-xxx declarados y distintos entre sí. Integraciones inválidas: {', '.join(bad)}", "integraciones"
    if agent_name == "solution-architect-agent" and key == "adr_options":
        bad = [a["id"] for a in out.get("adrs", []) if len(a.get("opciones", [])) < 2 or not a.get("consecuencias")]
        return f"Todo ADR compara ≥2 opciones y lista consecuencias. ADRs incompletos: {', '.join(bad)}", "adrs"
    if agent_name == "api-designer-agent" and key == "openapi_valid":
        return "; ".join(verify.openapi_errors(out))[:600] or "OpenAPI 3.1 inválido", "endpoints"
    if agent_name == "api-designer-agent" and key == "int_coverage":
        need = [i["id"] for i in ctx.get("solution_architecture", {}).get("integraciones", []) if i.get("tipo") in ("comando", "consulta")]
        got = {i for e in out.get("endpoints", []) for i in e.get("integraciones", [])}
        return f"Toda integración comando/consulta necesita un endpoint. Sin endpoint: {', '.join(i for i in need if i not in got)}", "endpoints[].integraciones"
    if agent_name == "api-designer-agent" and key == "refs_declared":
        return "Cada endpoint debe citar un SEC-SCHEME-xxx de esquemas_seguridad y errores ERR-xxx de errores", "endpoints"
    if agent_name == "test-case-generator-agent" and key == "criteria_coverage":
        crit = sorted(verify._criteria(ctx)); cov = {(c["historia"], c["criterio"]) for c in out.get("casos", [])}
        return f"Todo criterio necesita ≥1 caso (historia, posición). Sin cubrir: {', '.join(f'{h}#{n}' for h, n in crit if (h, n) not in cov)}", "casos[].criterio"
    if agent_name == "test-case-generator-agent" and key == "int_endpoints_valid":
        eps = {e["id"] for e in ctx.get("api_design", {}).get("endpoints", [])}
        return f"Los casos de integración deben citar un endpoint existente ({', '.join(sorted(eps))})", "casos[].endpoint"
    if agent_name == "test-case-generator-agent" and key == "pytest_compiles":
        bad = [c["id"] for c in out.get("casos", []) if not verify.pytest_code_ok(c.get("codigo_pytest", ""))]
        return f"codigo_pytest debe ser Python válido con una función def test_. Casos con error: {', '.join(bad)}", "casos[].codigo_pytest"
    if agent_name == "cicd-pipeline-agent" and key == "yaml_valid":
        return "; ".join(e for p in out.get("pipelines", []) for e in verify.workflow_errors(p))[:600], "pipelines[].jobs"
    if agent_name == "cicd-pipeline-agent" and key == "env_coverage":
        have = {p["ambiente"] for p in out.get("pipelines", [])}
        return f"Se requiere un pipeline por ambiente. Faltan: {', '.join(a for a in ('dev', 'staging', 'prod') if a not in have)}", "pipelines[].ambiente"
    if agent_name == "cicd-pipeline-agent" and key == "test_stage":
        return "Todo pipeline debe tener un paso run que ejecute pytest antes de desplegar", "pipelines[].jobs[].steps"
    if agent_name == "cicd-pipeline-agent" and key == "prod_manual_gate":
        return "El pipeline de prod necesita una puerta de etapa deploy y tipo manual", "pipelines[prod].gates"
    if agent_name == "security-compliance-agent" and key == "sec_coverage":
        secs = [r["id"] for r in ctx.get("solution_architecture", {}).get("requisitos_seguridad", [])]
        cov = {r for c in out.get("controles", []) for r in c.get("requisitos", [])}
        return f"Todo requisito SEC-xxx necesita ≥1 control. Sin control: {', '.join(x for x in secs if x not in cov)}", "controles[].requisitos"
    if agent_name == "security-compliance-agent" and key == "comps_valid":
        comps = sorted(c["id"] for c in ctx.get("solution_architecture", {}).get("componentes", []))
        return f"aplica_a solo puede citar componentes declarados: {', '.join(comps)}", "controles[].aplica_a"
    if agent_name == "data-model-agent" and key == "entity_coverage":
        got = {verify.norm(t["entidad"]) for t in out.get("tablas", [])}
        miss = [e["nombre"] for e in ctx.get("domain_model", {}).get("entidades", []) if verify.norm(e["nombre"]) not in got]
        return f"Toda entidad del dominio necesita una tabla (campo entidad). Sin tabla: {', '.join(miss)}", "tablas[].entidad"
    if agent_name == "data-model-agent" and key == "ddl_ok":
        from .tools.sandbox import ddl_check
        sin_pk = [t["id"] for t in out.get("tablas", []) if not any(c["pk"] for c in t["columnas"])]
        return f"El DDL generado no se ejecuta en SQLite: {ddl_check(out)['error'] or ''} {('Tablas sin pk: ' + ', '.join(sin_pk)) if sin_pk else ''}".strip(), "tablas"
    if agent_name == "data-model-agent" and key == "pii_protected":
        bad = [f'{t["nombre"]}.{c["nombre"]}' for t in out.get("tablas", []) for c in t["columnas"] if c["pii"] and not c["enmascarado"]]
        return f"Columnas con datos personales sin enmascarar: {', '.join(bad)}", "tablas[].columnas"
    if agent_name == "backend-developer-agent" and key == "compiles" and any(l.lstrip().startswith(("def ", "async def ", "import ", "from ")) and not l.startswith(" ") for h in out.get("handlers", []) for l in h["lineas"]):
        return "lineas es solo el CUERPO del handler: no definas funciones (def), no importes módulos; empieza directamente con la lógica y termina con return", "handlers[].lineas"
    if agent_name == "backend-developer-agent" and key in ("compiles", "smoke_ok"):
        from .tools.sandbox import smoke
        sm = smoke(verify.app_files(ctx, out), ctx.get("api_design", {}))
        if not sm.get("import_ok"):
            hint = " Escribe todo texto Python (claves, tablas, mensajes, estados) entre comillas SIMPLES, p. ej. DB['pedido'], detail='no encontrado'." if "SyntaxError" in str(sm.get("error", "")) else ""
            return f"El servicio no se puede importar: {sm.get('error', '')}.{hint}", "handlers[].lineas"
        bad = [f'{r["id"]}→{r["status"]}{(" " + r["error"]) if r.get("error") else ""}' for r in sm.get("resultados", []) if r["status"] >= 500]
        return f"Endpoints que responden error 5xx con datos de ejemplo (revisa nombres de tablas/columnas de DB, variables y que todo texto vaya entre comillas simples): {'; '.join(bad)}", "handlers"
    if agent_name == "backend-developer-agent" and key == "routes_coverage":
        eps = [e["id"] for e in ctx.get("api_design", {}).get("endpoints", [])]
        hs = {h["endpoint"] for h in out.get("handlers", [])}
        return f"Falta handler para: {', '.join(e for e in eps if e not in hs)}", "handlers"
    if agent_name == "qa-automation-agent" and key == "tc_coverage":
        tcs = [c["id"] for c in ctx.get("test_cases", {}).get("casos", [])]
        got = {c for s in out.get("suites", []) for c in s.get("casos", [])}
        return f"Casos sin suite: {', '.join(t for t in tcs if t not in got)}", "suites[].casos"
    if agent_name == "qa-automation-agent" and key == "suite_runs":
        from .tools.sandbox import run_tests
        rt = run_tests(verify.app_files(ctx), out)
        errs = [f["prueba"] + ": " + f["detalle"][:160] for f in rt["fallos"] if "setup" in f["detalle"] or "Error" in f["detalle"] or f["prueba"] == "<colección>"][:4]
        return f"Las suites tienen errores propios (fixtures inexistentes, nombres no definidos, sintaxis), no fallos del servicio. Usa solo los fixtures client y db y datos como diccionarios: {'; '.join(errs)}", "suites[].lineas"
    if agent_name == "code-review-agent" and key == "bandit_covered":
        from .tools.sandbox import static_analysis
        sa = static_analysis(verify.app_files(ctx))
        miss = [f'{b["archivo"]}:{b["linea"]} {b["regla"]}' for b in sa["bandit"] if b["severidad"] in ("HIGH", "MEDIUM")]
        return f"Reporta como hallazgo cada problema de bandit HIGH/MEDIUM: {', '.join(miss)}", "hallazgos"
    if agent_name == "code-review-agent" and key == "findings_in_handlers":
        from .tools.sandbox import handler_spans
        sp = verify.app_files(ctx); rng = ", ".join(f"{k}: líneas {a}-{b}" for k, (a, b) in handler_spans(sp).items())
        return f"Solo se revisan los cuerpos de los handlers (el resto lo genera el sistema). Rangos válidos de app/main.py: {rng}", "hallazgos[].linea"
    if agent_name == "code-review-agent" and key == "verdict_consistent":
        return "veredicto debe ser cambios_requeridos si hay hallazgos criticos o pruebas fallidas, y aprobado en caso contrario", "veredicto"
    if agent_name == "release-manager-agent" and key == "window_valid":
        return f"ventana debe ser un martes o jueves igual o posterior a hoy ({ctx.get('hoy')})", "release.ventana"
    if agent_name == "release-manager-agent" and key == "decision_consistent":
        q = verify.quality_facts(ctx)
        return f"decision inconsistente con los hechos: {q['pruebas_fallidas']} pruebas fallidas de {q['pruebas_total']}, {q['criticos']} hallazgos críticos; go solo si todo está en verde y todo el checklist se cumple", "release.decision"
    return f"{res['rule']} (valor actual {res['value']})", "<artefacto>"


def review(producer, artefact: dict, ctx: dict, round_: int) -> tuple[dict, bool, dict]:
    findings: list[dict] = []
    # 1. contrato
    errs = sorted(jsonschema.Draft202012Validator(producer.output_schema).iter_errors(artefact), key=lambda e: list(e.path))
    for e in errs[:10]:
        findings.append({"severidad": "bloqueante", "regla": "contrato_json_schema", "detalle": e.message[:300],
                         "ubicacion": "/".join(map(str, e.path)) or "<raíz>"})
    # 2. F5 (solo si el contrato es válido: las métricas asumen la estructura)
    _, f5 = (False, {}) if errs else verify.evaluate(producer, artefact, ctx, {"refinement_rounds": round_})
    ok_f5 = bool(f5) and all(v["ok"] for k, v in f5.items() if k != "refinement_rounds")   # refinement_rounds es KPI del piloto, no bloquea
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
