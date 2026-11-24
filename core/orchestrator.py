"""Orquestador del DAG (skill-orchestrator, F3/F4): ejecuta etapas, paraleliza los nodos de un `parallel`,
pasa cada artefacto por governance (determinista), resuelve los gates humanos (RACI) con aprobación por
riesgo, ejecuta el bucle de calidad (pruebas reales + revisión + remediación) y el despliegue.

Reanudable: cada artefacto se guarda con su decisión en data/requerimientos/<id>/output/. Si un gate de
riesgo alto queda pendiente, el requerimiento se detiene (PendingApproval) y la siguiente corrida retoma
desde ahí leyendo output/aprobaciones/<artefacto>.json (decisión humana con timestamp real)."""
import hashlib, json, os, random
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
import jsonschema
from .intake import load_business_request
from .model_port import ModelPort, ContractError
from .registry import Registry
from .telemetry import Telemetry
from .tools.rag import KnowledgeRag
from . import verify, governance

ARTEFACT_NAME = {"product-analyst-agent": "user_story_set", "domain-modeling-agent": "domain_model",
                 "ux-ui-copilot-agent": "ux_spec", "solution-architect-agent": "solution_architecture",
                 "security-compliance-agent": "security_compliance", "api-designer-agent": "api_design",
                 "data-model-agent": "data_model", "backend-developer-agent": "backend_code",
                 "test-case-generator-agent": "test_cases", "qa-automation-agent": "qa_suite",
                 "code-review-agent": "code_review", "cicd-pipeline-agent": "cicd_pipeline",
                 "release-manager-agent": "release_plan"}
RAG_QUERIES = {"ux-ui-copilot-agent": ["convenciones de interfaz componentes", "accesibilidad"],
               "domain-modeling-agent": ["glosario pedido estado", "especificación pedidos"],
               "solution-architect-agent": ["decisión de arquitectura ADR", "patrones integración eventos", "política de seguridad datos"],
               "security-compliance-agent": ["política de seguridad datos personales", "autenticación segundo factor", "registro de accesos"],
               "api-designer-agent": ["convenciones de API versionado paginación", "errores RFC 7807 correlation", "openapi pedidos"],
               "data-model-agent": ["nomenclatura base de datos", "datos personales enmascaramiento"],
               "backend-developer-agent": ["convenciones de código", "reglas de negocio"],
               "test-case-generator-agent": ["convenciones de código pruebas", "criterios de aceptación"],
               "qa-automation-agent": ["convenciones de código pruebas"],
               "code-review-agent": ["convenciones de código", "política de seguridad"],
               "cicd-pipeline-agent": ["política de release ventanas despliegue", "política de seguridad secretos pipeline"],
               "release-manager-agent": ["política de release ventanas despliegue cierre de campaña"]}


class PendingApproval(Exception):
    """Un gate de riesgo alto espera la decisión humana; el requerimiento se reanuda en otra corrida."""


class Scheduled(Exception):
    """El despliegue está programado para una ventana futura (política de release)."""


class ModelDeferred(Exception):
    """El modelo que atiende al agente no se levantó en esta corrida (p. ej. el maestro, D-F4-1 C): el requerimiento
    se pausa y sigue en la próxima ventana con ese modelo; nunca se sustituye por otro modelo."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class Orchestrator:
    def __init__(self, root: Path, telemetry: Telemetry, seed: int = 2026, today: str | None = None):
        self.root = Path(root)
        self.reg = Registry(self.root)
        self.tel = telemetry
        self.rag = KnowledgeRag(self.root / "data/knowledge")
        self.rng = random.Random(seed)
        self.gov = self.reg.agents["governance-agent"]
        import os
        if os.environ.get("GATES_MODE"):                 # p. ej. humo técnico con gates simulados; el piloto usa manual
            self.reg.gates["mode"] = os.environ["GATES_MODE"]
        from . import calendario
        self.calendario = calendario.config()                # protocolo F5 v2: días de release y feriados del piloto (PILOT)
        self.today = today or calendario.hoy_lima()
        self.examples: list[dict] = []           # F2-A: pares (mensajes ronda 0 → salida aprobada) para destilación
        self.rejections: list[dict] = []         # diagnóstico: salidas rechazadas por governance con sus hallazgos

    # ---------- utilidades ----------
    def _port(self, agent, correccion: bool = False):
        alt = self.reg.correccion_provider(agent.name) if correccion else None     # D-E1: la corrección tras devolución humana la hace el maestro
        name, cfg = alt if alt else self.reg.provider_for(agent.name)
        if name in [x for x in os.environ.get("PROVIDERS_DOWN", "").split(",") if x]:
            raise ModelDeferred(f"{agent.name}: {name}")
        return ModelPort(self.reg.adapter_by_name(name, cfg) if alt else self.reg.adapter_for(agent.name), self.tel, max_retries=2)

    def _out_dir(self, req_id: str) -> Path:
        d = self.root / "data/requerimientos" / req_id / "output"; d.mkdir(parents=True, exist_ok=True)
        return d

    def _messages(self, agent, payload: dict, knowledge: str, feedback: list[dict] | None = None, anterior: dict | None = None) -> list[dict]:
        user = (f"## Entrada ({agent.spec.get('input_schema') or 'contexto'})\n```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```\n\n"
                f"## Conocimiento recuperado (cita los ids en provenance.knowledge_refs)\n{knowledge or '(sin resultados)'}\n\n"
                f"## Esquema de salida (JSON Schema)\n```json\n{json.dumps(agent.output_schema, ensure_ascii=False)}\n```")
        msgs = [{"role": "system", "content": agent.prompt}, {"role": "user", "content": user}]
        if anterior is not None:          # ensayo1 (23/11/2026): sin la versión devuelta, el agente rehacía el artefacto y perdía correcciones previas
            msgs.append({"role": "user", "content": "Esta es la versión que el revisor humano te devolvió. Parte de ella: conserva todo lo que no se pide "
                                                    "cambiar y aplica TODAS las devoluciones de la lista siguiente (las anteriores siguen vigentes):\n```json\n"
                                                    + json.dumps({k: v for k, v in anterior.items() if k != "provenance"}, ensure_ascii=False, indent=1) + "\n```"})
        if feedback:
            reglas = "\n".join(f"- {v['id']}: {v['rule']}" + (f" ({v['description']})" if v.get("description") else "") for v in agent.verification if v["id"] != "refinement_rounds")
            msgs.append({"role": "user", "content": "Hallazgos de gobernanza sobre tu versión anterior; corrígelos todos:\n"
                                                    + json.dumps(feedback, ensure_ascii=False, indent=1)
                                                    + "\n\nDevuelve el artefacto COMPLETO corregido y verifica que siga cumpliendo TODOS los criterios, no solo los señalados:\n" + reglas})
        return msgs

    def _queries_for(self, agent, ctx: dict) -> list[str]:
        br = ctx["business_request"]
        return [br["titulo"], br["necesidad"][:200]] + br["reglas_negocio"] + RAG_QUERIES.get(agent.name, [])

    # ---------- estado del requerimiento (lead time) ----------
    def _estado(self, req_id: str, **upd) -> dict:
        p = self._out_dir(req_id) / "estado.json"
        from . import calendario
        st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"req_id": req_id, "inicio": _now(), "estado": "en_curso"}
        if "entrada_pipeline" not in st:                 # protocolo F5 v2 (C3): inicio del lead time = alta en el orquestador
            st["entrada_pipeline"] = calendario.a_lima(st["inicio"])
        st.update(upd); p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        return st

    # ---------- governance (determinista) ----------
    def _review(self, producer, artefact: dict, ctx: dict, round_: int) -> tuple[dict, bool, dict]:
        verdict, ok_f5, f5 = governance.review(producer, artefact, ctx, round_)
        verdict["artefacto"] = ARTEFACT_NAME[producer.name]
        self.tel.emit(event="governance_verdict", agent=self.gov.name, req_id=ctx["req_id"], target=producer.name, round=round_,
                      verdict=verdict["veredicto"], findings=len(verdict["hallazgos"]), provider="deterministic", model_id=None)
        return verdict, ok_f5, f5

    # ---------- gate humano (RACI) con aprobación por riesgo ----------
    def _risk(self, artefact: str, out: dict) -> str:
        r = self.reg.gates.get("riesgo", {}).get(artefact, "bajo")
        if r == "pii":
            r = "alto" if any(c.get("pii") for t in out.get("tablas", []) for c in t.get("columnas", [])) else "bajo"
        return r

    def _gate(self, producer, verdict: dict, ctx: dict, out: dict, forzar_humano: str | None = None) -> dict:
        g = producer.gate
        role = self.reg.gates["roles"][g["role"]]
        art = g["artefact"]
        if self.reg.gates.get("mode", "auto") == "manual":
            risk = "alto" if forzar_humano else self._risk(art, out)
            if risk == "bajo":
                decision = {"decision": "approved", "role": g["role"], "by": "politica_riesgo_bajo", "riesgo": "bajo", "delay_h": 0.0, "ts": _now()}
                if art == "backend_code":
                    decision["sujeto_a"] = "bucle_calidad"      # las pruebas y la revisión de código deciden después (puerta code_review)
            else:
                req = {"artefacto": art, "rol": g["role"], "hash": _hash(out), "solicitado": _now(), "agente": producer.name,
                       "hallazgos_governance": verdict["hallazgos"] + ([{"severidad": "mayor", "regla": "calidad_pruebas", "detalle": forzar_humano,
                                                                          "ubicacion": "suites"}] if forzar_humano else [])}
                pend = self._out_dir(ctx["req_id"]) / "pendientes"; pend.mkdir(exist_ok=True)
                (pend / f"{art}.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
                decision = {"decision": "pending", "role": g["role"], "by": "human", "riesgo": "alto", "hash": req["hash"], "solicitado": req["solicitado"]}
        else:
            pol = role["auto_policy"]; sev = {h["severidad"] for h in verdict["hallazgos"]}
            ok = (not sev and pol["approve_if_no_findings"]) or (sev <= {"menor"} and pol["approve_if_only_minor"])
            s = pol["delay_hours_sampler"]; mu = __import__("math").log(s["median"]); sigma = (__import__("math").log(s["p90"]) - mu) / 1.2816
            delay = round(self.rng.lognormvariate(mu, sigma), 2)
            delegated = delay > role["sla_hours"] and role.get("delegable")
            decision = {"decision": "approved" if ok else "returned", "role": g["role"], "by": role.get("delegate_to") if delegated else g["role"],
                        "delegated": bool(delegated), "delay_h": delay}
        self.tel.emit(event="human_gate", req_id=ctx["req_id"], agent=producer.name, artefact=art, **{k: v for k, v in decision.items() if k != "hash"})
        return decision

    def _human_decision(self, req_id: str, art: str, meta_gate: dict) -> dict | None:
        p = self._out_dir(req_id) / "aprobaciones" / f"{art}.json"
        if not p.exists():
            return None
        a = json.loads(p.read_text(encoding="utf-8"))
        if a.get("hash") and a["hash"] != meta_gate.get("hash"):
            return None                                   # la aprobación corresponde a otra versión del artefacto
        t0 = datetime.fromisoformat(meta_gate["solicitado"]); t1 = datetime.fromisoformat(a["ts"])
        return {"decision": a["decision"], "role": meta_gate["role"], "by": a.get("por", "humano"), "riesgo": "alto",
                "motivo": a.get("motivo", ""), "ts": a["ts"], "delay_h": round((t1 - t0).total_seconds() / 3600, 2),
                "ventana": a.get("ventana"), "dictamen_ia": (a.get("dictamen_ia") or {}).get("recomendacion"), "coincide_con_ia": a.get("coincide_con_ia")}

    def _devoluciones(self, req_id: str, art: str) -> list[dict]:
        f = self._out_dir(req_id) / "devoluciones" / f"{art}.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []

    def _registrar_devolucion(self, req_id: str, art: str, h: dict) -> list[dict]:
        """Acumula las devoluciones humanas de un artefacto (output/devoluciones/<art>.jsonl) y devuelve el historial completo."""
        d = self._out_dir(req_id) / "devoluciones"; d.mkdir(exist_ok=True); f = d / f"{art}.jsonl"
        previos = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []
        if not any(p["ts"] == h["ts"] for p in previos):
            previos.append({"ts": h["ts"], "motivo": h.get("motivo", ""), "por": h.get("by"), "rol": h.get("role")})
            f.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in previos), encoding="utf-8")
        return previos

    # ---------- nodo = agente + governance + gate ----------
    def _load(self, req_id: str, name: str):
        d = self._out_dir(req_id)
        if (d / f"{name}.json").exists() and (d / f"{name}.decision.json").exists():
            return json.loads((d / f"{name}.json").read_text(encoding="utf-8")), json.loads((d / f"{name}.decision.json").read_text(encoding="utf-8"))
        return None

    def run_agent(self, agent_name: str, payload: dict, ctx: dict, feedback0: list | None = None, force: bool = False, defer_gate: bool = False) -> dict:
        agent = self.reg.agents[agent_name]; name = ARTEFACT_NAME[agent_name]; req_id = ctx["req_id"]
        anterior = None
        saved = None if force else self._load(req_id, name)
        if saved:
            out, meta = saved
            g = meta.get("gate", {})
            if g.get("decision") == "approved" or (defer_gate and g.get("decision") in ("deferred", "approved")):
                ctx[name] = out
                return out
            if g.get("decision") == "pending":
                h = self._human_decision(req_id, name, g)
                if h is None:
                    ctx[name] = out
                    raise PendingApproval(f"{req_id}/{name}")
                self.tel.emit(event="human_gate", req_id=req_id, agent=agent_name, artefact=name, **h)
                if h["decision"] == "approved":
                    meta["gate"] = h; self._save(ctx, name, out, meta)
                    return out
                previos = self._registrar_devolucion(req_id, name, h)
                feedback0 = [{"severidad": "mayor", "regla": "gate_humano", "detalle": f"devuelto por {h['role']} ({p['ts']}): {p['motivo']}",
                              "ubicacion": "<raíz>"} for p in previos]
                anterior = out
        max_rounds = agent.spec.get("max_governance_rounds", self.reg.dag.get("retry", {}).get("max_governance_rounds", 2))
        knowledge, _ = self.rag.context_block(self._queries_for(agent, ctx))
        self.tel.emit(event="handoff", req_id=req_id, to=agent_name, frm=agent.spec.get("consumes_from"), mode="auto")
        feedback = feedback0
        correccion = anterior is not None
        if correccion:
            self.tel.emit(event="correccion_humana", req_id=req_id, agent=agent_name, artefact=name, devoluciones=len(feedback0 or []))
        for round_ in range(max_rounds + 1):
            out, stats = self._port(agent, correccion).run(agent, req_id, self._messages(agent, payload, knowledge, feedback, anterior), variant=f"r{round_}")
            self._stamp_provenance(agent, out, req_id)
            verdict, ok_f5, f5 = self._review(agent, out, ctx, round_)
            if verdict["veredicto"] == "rechazado":
                rj = {"agent": agent_name, "req_id": req_id, "round": round_, "ts": _now(), "hallazgos": verdict["hallazgos"], "output": out}
                self.rejections.append(rj)
                with (self._out_dir(req_id) / "rechazos.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rj, ensure_ascii=False) + "\n")
            self.tel.emit(event="f5_check", req_id=req_id, agent=agent_name, round=round_, ok=ok_f5, metrics=f5)
            if verdict["veredicto"] == "aprobado":
                if defer_gate:
                    gate = {"decision": "deferred"}
                else:
                    gate = self._gate(agent, verdict, ctx, out) if agent.gate else {"decision": "approved"}
                self._save(ctx, name, out, {"verdict": verdict, "f5": f5, "gate": gate, "model": stats, "rounds": round_})
                self.examples.append({"agent": agent_name, "req_id": req_id, "rounds": round_, "f5": {k: v["value"] for k, v in f5.items()},
                                      "messages": self._messages(agent, payload, knowledge), "output": out})
                if gate["decision"] == "pending":
                    raise PendingApproval(f"{req_id}/{name}")
                if gate["decision"] == "returned":
                    feedback = [{"severidad": "mayor", "regla": "gate_humano", "detalle": f"devuelto por {gate['role']}", "ubicacion": "<raíz>"}]
                    continue
                return out
            feedback = (feedback0 or []) + verdict["hallazgos"]   # las devoluciones humanas siguen vigentes en las rondas de governance
            anterior = None
        self.tel.emit(event="escalation", req_id=req_id, agent=agent_name, round=max_rounds, to=agent.gate["role"] if agent.gate else "tech_lead", reason="max_rounds")
        if self.reg.gates.get("mode") == "manual" and agent.gate:
            # Escalamiento (F3 de cada ficha): el humano decide sobre la última versión con los hallazgos a la vista
            req = {"artefacto": name, "rol": agent.gate["role"], "hash": _hash(out), "solicitado": _now(), "agente": agent_name,
                   "escalado": True, "hallazgos_governance": verdict["hallazgos"]}
            pend = self._out_dir(req_id) / "pendientes"; pend.mkdir(exist_ok=True)
            (pend / f"{name}.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
            gate = {"decision": "pending", "role": agent.gate["role"], "by": "human", "riesgo": "escalado", "hash": req["hash"], "solicitado": req["solicitado"]}
            self._save(ctx, name, out, {"verdict": verdict, "f5": f5, "gate": gate, "model": stats, "rounds": max_rounds, "escalado": True})
            raise PendingApproval(f"{req_id}/{name} (escalado)")
        raise ContractError(f"{agent_name}/{req_id}: rechazado por gobernanza {max_rounds + 1} veces")

    @staticmethod
    def _stamp_provenance(agent, out: dict, req_id: str) -> None:
        """Los hechos de origen (requerimiento, agente, fase, versión de contrato) los conoce el orquestador:
        se sellan en código para que la trazabilidad (H5) no dependa del modelo. El modelo aporta inputs y knowledge_refs."""
        prov = out.get("provenance")
        if isinstance(prov, dict):
            prov.update({"contract_version": "1.0", "req_id": req_id, "agent": agent.name.removesuffix("-agent"),
                         "phase": agent.spec.get("phase", prov.get("phase"))})
        if "req_id" in out:
            out["req_id"] = req_id

    def _save(self, ctx, name, artefact, meta):
        out_dir = self._out_dir(ctx["req_id"])
        (out_dir / f"{name}.json").write_text(json.dumps(artefact, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"{name}.decision.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        from . import render                                  # formatos estándar derivados de forma determinista
        from .tools import sandbox
        if name == "api_design":
            (out_dir / "api_design.openapi.yaml").write_text(render.openapi_yaml(artefact), encoding="utf-8")
        if name == "cicd_pipeline":
            for p in artefact.get("pipelines", []):
                (out_dir / f"{p['id']}.{p['ambiente']}.workflow.yaml").write_text(render.workflow_yaml(p), encoding="utf-8")
        if name == "data_model":
            up, down = sandbox.render_ddl(artefact)
            (out_dir / "data_model.up.sql").write_text(up, encoding="utf-8"); (out_dir / "data_model.down.sql").write_text(down, encoding="utf-8")
        ctx[name] = artefact
        if name == "backend_code":
            for rel, txt in verify.app_files(ctx).items():
                p = out_dir / "servicio" / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(txt, encoding="utf-8")

    # ---------- entradas especiales (información que el orquestador calcula con herramientas) ----------
    def _backend_payload(self, ctx: dict) -> dict:
        from .tools import sandbox
        return {"api_design": ctx["api_design"], "data_model": ctx["data_model"],
                "firmas_handlers": sandbox.signatures(ctx["api_design"]),
                "tablas_db": {t["nombre"]: [c["nombre"] for c in t["columnas"]] for t in ctx["data_model"].get("tablas", [])}}

    def _special_payload(self, agent_name: str, ctx: dict):
        from .tools import sandbox
        if agent_name == "backend-developer-agent":
            return self._backend_payload(ctx)
        if agent_name == "qa-automation-agent":
            return {"test_cases": ctx["test_cases"], "api_design": ctx["api_design"],
                    "servicio": {"rutas": [{"endpoint": e["id"], "metodo": e["metodo"], "ruta": e["ruta"]} for e in ctx["api_design"]["endpoints"]],
                                 "semillas": ctx["backend_code"].get("semillas", [])}}
        if agent_name == "code-review-agent":
            files = verify.app_files(ctx)
            rt = sandbox.run_tests(files, ctx.get("qa_suite", {}))
            sa = sandbox.static_analysis(files)
            keep = lambda xs: [x for x in xs if sandbox.in_handlers(files, x["archivo"], x["linea"])]
            return {"codigo_handlers": sandbox.handler_code(files), "analisis_estatico": {"ruff": keep(sa["ruff"]), "bandit": keep(sa["bandit"])},
                    "reporte_pruebas": {k: rt[k] for k in ("collected", "passed", "failed", "errors", "fallos")}}
        if agent_name == "release-manager-agent":
            q = verify.quality_facts(ctx)
            from . import calendario
            return {"hoy": self.today, "dias_release_permitidos": calendario.dias_release_desde(self.today, self.calendario),
                    "estado_calidad": {**q, "veredicto_revision": ctx["code_review"]["veredicto"]},
                    "security_compliance": {"gates": ctx["security_compliance"]["gates"], "hallazgos": ctx["security_compliance"]["hallazgos"]},
                    "cicd_pipeline": [{"id": p["id"], "ambiente": p["ambiente"], "gates": p["gates"]} for p in ctx["cicd_pipeline"]["pipelines"]]}
        return None

    # ---------- bucle de calidad: pruebas reales + revisión + remediación del backend ----------
    def quality_loop(self, ctx: dict, stage_art: dict, max_cycles: int = 2) -> dict:
        """Bucle de calidad: pruebas reales + revisión + remediación del backend.
        Protocolo F5 v2.1 (ensayo1, ronda 11): (a) las devoluciones humanas de code_review siguen vigentes en TODOS los ciclos
        de remediación, no solo en el primero; (b) qa_suite no se aprueba por riesgo bajo si hay pruebas fallidas o pruebas que no
        llaman al servicio: queda para el QA Lead, que puede devolverla; (c) backend_code queda sujeto a esta revisión."""
        req_id = ctx["req_id"]
        saved = self._load(req_id, "code_review")
        humanos: list[dict] = []
        devuelto_cr = False
        ctx.pop("_qa_pendiente", None)
        if saved and saved[1].get("gate", {}).get("decision") in ("approved", "pending"):
            self.run_agent("qa-automation-agent", self._special_payload("qa-automation-agent", ctx), ctx, defer_gate=True)
            out, meta = saved
            if meta["gate"]["decision"] == "approved":
                ctx["code_review"] = out
                return out
            h = self._human_decision(req_id, "code_review", meta["gate"])
            if h is None:
                ctx["code_review"] = out
                raise PendingApproval(f"{req_id}/code_review")
            self.tel.emit(event="human_gate", req_id=req_id, agent="code-review-agent", artefact="code_review", **h)
            if h["decision"] == "approved":
                meta["gate"] = h; self._save(ctx, "code_review", out, meta)
                return out
            previos = self._registrar_devolucion(req_id, "code_review", h)
            devuelto_cr = True
            humanos = [{"severidad": "mayor", "regla": "gate_humano", "detalle": f"Tech Lead devolvió el código ({p['ts']}): {p['motivo']}", "ubicacion": "handlers"}
                       for p in previos]
        # D-E3: las devoluciones humanas del propio backend_code también siguen vigentes en los ciclos de remediación
        humanos += [{"severidad": "mayor", "regla": "gate_humano", "detalle": f"Tech Lead devolvió el código ({p.get('ts')}): {p.get('motivo')}", "ubicacion": "handlers"}
                    for p in self._devoluciones(req_id, "backend_code")]
        if devuelto_cr:
            self.tel.emit(event="remediation", req_id=req_id, ciclo=0, motivo="gate_humano", devoluciones=len(humanos))
            self.run_agent("backend-developer-agent", self._backend_payload(ctx), ctx, feedback0=humanos, force=True)
        for cycle in range(max_cycles + 1):
            self.run_agent("qa-automation-agent", self._special_payload("qa-automation-agent", ctx), ctx, defer_gate=True)
            review = self.run_agent("code-review-agent", self._special_payload("code-review-agent", ctx), ctx, force=True, defer_gate=True)
            q = verify.quality_facts(ctx)
            from . import calendario
            fecha = calendario.ahora_lima()       # protocolo F5 v2 (C5): defectos previos a la puerta, con etapa de origen y de detección
            for _ in range(q["pruebas_fallidas"]):
                self.tel.emit(event="defect_detected", req_id=req_id, origen="qa-automation", ciclo=cycle, deteccion="pre_gate",
                              etapa_origen="backend-developer-agent", etapa_deteccion="qa-automation-agent", severidad="sin_clasificar", fecha=fecha)
            for h in [h for h in review["hallazgos"] if h["severidad"] == "critico"]:
                self.tel.emit(event="defect_detected", req_id=req_id, origen="code-review", ciclo=cycle, find=h["id"], deteccion="pre_gate",
                              etapa_origen="backend-developer-agent", etapa_deteccion="code-review-agent", severidad="critico", fecha=fecha)
            if (q["pruebas_fallidas"] == 0 and q["criticos"] == 0) or cycle == max_cycles:
                break
            from .tools import sandbox
            rt = sandbox.run_tests(verify.app_files(ctx), ctx["qa_suite"])
            fb = humanos + \
                 [{"severidad": "mayor", "regla": "prueba_fallida", "detalle": f["prueba"] + ": " + f["detalle"], "ubicacion": "handlers"} for f in rt["fallos"][:10]] + \
                 [{"severidad": "mayor", "regla": h["regla"], "detalle": h["descripcion"] + " → " + h["recomendacion"], "ubicacion": f'{h["archivo"]}:{h["linea"]}'}
                  for h in review["hallazgos"] if h["severidad"] == "critico"]
            self.tel.emit(event="remediation", req_id=req_id, ciclo=cycle + 1, fallos=q["pruebas_fallidas"], criticos=q["criticos"], devoluciones=len(humanos))
            self.run_agent("backend-developer-agent", self._backend_payload(ctx), ctx, feedback0=fb, force=True)
        self._gate_qa_suite(ctx, q)
        out, meta = self._load(req_id, "code_review")
        gate = self._gate(self.reg.agents["code-review-agent"], meta["verdict"], ctx, out)
        meta["gate"] = gate; self._save(ctx, "code_review", out, meta)
        if gate["decision"] == "pending" or ctx.get("_qa_pendiente"):
            raise PendingApproval(f"{req_id}/code_review")
        return out

    def _gate_qa_suite(self, ctx: dict, q: dict) -> None:
        """Puerta de qa_suite al cerrar el bucle: aprobación automática solo con todas las pruebas en verde y llamando al servicio."""
        saved = self._load(ctx["req_id"], "qa_suite")
        g = saved[1].get("gate", {}) if saved else {}
        # se evalúa al cerrar el bucle; también se reevalúa una aprobación automática anterior (no una decisión humana)
        if not saved or not (g.get("decision") in ("deferred", None) or g.get("by") == "politica_riesgo_bajo"):
            return
        out, meta = saved
        agent = self.reg.agents["qa-automation-agent"]
        if q["pruebas_fallidas"] == 0 and q.get("pruebas_sin_servicio", 0) == 0:
            gate = self._gate(agent, meta["verdict"], ctx, out)
        else:
            gate = self._gate(agent, meta["verdict"], ctx, out, forzar_humano=f'{q["pruebas_fallidas"]} pruebas fallidas, {q.get("pruebas_sin_servicio", 0)} sin llamar al servicio')
        meta["gate"] = gate; self._save(ctx, "qa_suite", out, meta)
        ctx["_qa_pendiente"] = gate["decision"] == "pending"

    # ---------- DAG ----------
    def _payload(self, node: dict, ctx: dict, stage_art: dict):
        sp = self._special_payload(node["agent"], ctx) if node.get("agent") else None
        if sp is not None:
            return sp
        ins = node.get("inputs", [])
        if ins == ["intake"]:
            return ctx["business_request"]
        if len(ins) == 1:
            return ctx[stage_art[ins[0]]]
        return {stage_art[i]: ctx[stage_art[i]] for i in ins}

    def run(self, req_id: str) -> dict:
        req_dir = self.root / "data/requerimientos" / req_id
        ctx = {"req_id": req_id, "hoy": self.today, "calendario": self.calendario}
        nodes = [n for st in self.reg.dag["stages"] for n in (st.get("parallel") or [st])]
        stage_art = {n["id"]: ARTEFACT_NAME[n["agent"]] for n in nodes if n.get("agent")}
        st = self._estado(req_id)
        if st.get("estado") == "desplegado":
            return ctx
        self.tel.emit(event="pipeline_started", req_id=req_id, dag=self.reg.dag["pipeline"], inicio=st["inicio"], entrada_pipeline=st["entrada_pipeline"])
        try:
            for stage in self.reg.dag["stages"]:
                if stage.get("action") == "load_business_request":
                    br = load_business_request(req_dir)
                    jsonschema.validate(br, self.reg.agents["product-analyst-agent"].input_schema)
                    ctx["business_request"] = br
                    self.tel.emit(event="intake", req_id=req_id, puntos=br["puntos_historia"], reglas=br["reglas_negocio"])
                elif stage.get("action") == "emit_handoff":
                    self.tel.emit(event="handoff", req_id=req_id, frm=stage.get("from", "discovery"), to=stage.get("to", "arquitectura"), mode="auto",
                                  artefacts=[stage_art[i] for i in stage.get("inputs", []) if i in stage_art and stage_art[i] in ctx])
                elif stage.get("action") == "quality_loop":
                    self.quality_loop(ctx, stage_art, stage.get("max_cycles", 2))
                elif stage.get("action") == "deploy":
                    from . import deploy
                    deploy.run(self, ctx)
                elif "parallel" in stage:
                    with ThreadPoolExecutor(max_workers=len(stage["parallel"])) as ex:
                        futs = [ex.submit(self.run_agent, n["agent"], self._payload(n, ctx, stage_art), ctx) for n in stage["parallel"]]
                        errs = []
                        for f in futs:
                            try:
                                f.result()
                            except PendingApproval as e:
                                errs.append(e)
                        if errs:
                            raise errs[0]
                else:
                    self.run_agent(stage["agent"], self._payload(stage, ctx, stage_art), ctx)
        except PendingApproval as e:
            self._estado(req_id, estado="esperando_aprobacion", pendiente=str(e))
            self.tel.emit(event="pipeline_paused", req_id=req_id, reason="pending_approval", pendiente=str(e))
            ctx["_estado"] = "esperando_aprobacion"
            return ctx
        except ModelDeferred as e:
            self._estado(req_id, estado="esperando_modelo", modelo=str(e))
            self.tel.emit(event="pipeline_paused", req_id=req_id, reason="model_deferred", modelo=str(e))
            ctx["_estado"] = "esperando_modelo"
            return ctx
        except Scheduled as e:
            self._estado(req_id, estado="programado", ventana=str(e))
            self.tel.emit(event="pipeline_paused", req_id=req_id, reason="scheduled", ventana=str(e))
            ctx["_estado"] = "programado"
            return ctx
        self.tel.emit(event="pipeline_completed", req_id=req_id, artefacts=[k for k in ARTEFACT_NAME.values() if k in ctx])
        ctx["_estado"] = self._estado(req_id)["estado"]
        return ctx
