"""Orquestador del DAG (F3): ejecuta etapas, paraleliza los nodos de un `parallel`, pasa cada artefacto
por governance-agent, aplica los criterios F5 en código y resuelve los gates humanos (RACI).
Escribe artefactos en data/requerimientos/<id>/output/ y eventos en telemetría."""
import json, random
from concurrent.futures import ThreadPoolExecutor
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
                 "api-designer-agent": "api_design", "test-case-generator-agent": "test_cases",
                 "cicd-pipeline-agent": "cicd_pipeline"}
RAG_QUERIES = {"ux-ui-copilot-agent": ["convenciones de interfaz componentes", "accesibilidad"],
               "domain-modeling-agent": ["glosario pedido estado", "especificación pedidos"],
               "solution-architect-agent": ["decisión de arquitectura ADR", "patrones integración eventos", "política de seguridad datos"],
               "api-designer-agent": ["convenciones de API versionado paginación", "errores RFC 7807 correlation", "openapi pedidos"],
               "test-case-generator-agent": ["convenciones de código pruebas", "criterios de aceptación"],
               "cicd-pipeline-agent": ["política de release ventanas despliegue", "política de seguridad secretos pipeline"]}


class Orchestrator:
    def __init__(self, root: Path, telemetry: Telemetry, seed: int = 2026):
        self.root = Path(root)
        self.reg = Registry(self.root)
        self.tel = telemetry
        self.rag = KnowledgeRag(self.root / "data/knowledge")
        self.rng = random.Random(seed)
        self.gov = self.reg.agents["governance-agent"]
        self.examples: list[dict] = []           # F2-A: pares (mensajes ronda 0 → salida aprobada) para destilación

    # ---------- utilidades ----------
    def _port(self, agent):
        return ModelPort(self.reg.adapter_for(agent.name), self.tel, max_retries=2)

    def _messages(self, agent, payload: dict, knowledge: str, feedback: list[dict] | None = None) -> list[dict]:
        user = (f"## Entrada ({agent.spec.get('input_schema') or 'contexto'})\n```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```\n\n"
                f"## Conocimiento recuperado (cita los ids en provenance.knowledge_refs)\n{knowledge or '(sin resultados)'}\n\n"
                f"## Esquema de salida (JSON Schema)\n```json\n{json.dumps(agent.output_schema, ensure_ascii=False)}\n```")
        msgs = [{"role": "system", "content": agent.prompt}, {"role": "user", "content": user}]
        if feedback:
            msgs.append({"role": "user", "content": "Hallazgos de gobernanza sobre tu versión anterior; corrígelos todos:\n"
                                                    + json.dumps(feedback, ensure_ascii=False, indent=1)})
        return msgs

    def _queries_for(self, agent, ctx: dict) -> list[str]:
        br = ctx["business_request"]
        qs = [br["titulo"], br["necesidad"][:200]] + br["reglas_negocio"]
        return qs + RAG_QUERIES.get(agent.name, [])

    # ---------- governance (determinista, F1.1) ----------
    def _review(self, producer, artefact: dict, ctx: dict, round_: int) -> tuple[dict, bool, dict]:
        verdict, ok_f5, f5 = governance.review(producer, artefact, ctx, round_)
        verdict["artefacto"] = ARTEFACT_NAME[producer.name]
        self.tel.emit(event="governance_verdict", agent=self.gov.name, req_id=ctx["req_id"], target=producer.name, round=round_,
                      verdict=verdict["veredicto"], findings=len(verdict["hallazgos"]), provider="deterministic", model_id=None)
        return verdict, ok_f5, f5

    # ---------- gate humano (RACI) ----------
    def _gate(self, producer, verdict: dict, ctx: dict) -> dict:
        g = producer.gate
        role = self.reg.gates["roles"][g["role"]]
        if self.reg.gates.get("mode", "auto") == "manual":
            decision = {"decision": "pending", "role": g["role"], "by": "human", "delay_h": None}
        else:
            pol = role["auto_policy"]; sev = {h["severidad"] for h in verdict["hallazgos"]}
            ok = (not sev and pol["approve_if_no_findings"]) or (sev <= {"menor"} and pol["approve_if_only_minor"])
            s = pol["delay_hours_sampler"]; mu = __import__("math").log(s["median"]); sigma = (__import__("math").log(s["p90"]) - mu) / 1.2816
            delay = round(self.rng.lognormvariate(mu, sigma), 2)
            delegated = delay > role["sla_hours"] and role.get("delegable")
            decision = {"decision": "approved" if ok else "returned", "role": g["role"], "by": role.get("delegate_to") if delegated else g["role"],
                        "delegated": bool(delegated), "delay_h": delay}
        self.tel.emit(event="human_gate", req_id=ctx["req_id"], agent=producer.name, artefact=g["artefact"], **decision)
        return decision

    # ---------- nodo = agente + governance + gate ----------
    def run_agent(self, agent_name: str, payload: dict, ctx: dict) -> dict:
        agent = self.reg.agents[agent_name]
        req_id = ctx["req_id"]
        max_rounds = self.reg.dag.get("retry", {}).get("max_governance_rounds", 2)
        knowledge, refs = self.rag.context_block(self._queries_for(agent, ctx))
        self.tel.emit(event="handoff", req_id=req_id, to=agent_name, frm=agent.spec.get("consumes_from"), mode="auto")
        feedback = None
        for round_ in range(max_rounds + 1):
            out, stats = self._port(agent).run(agent, req_id, self._messages(agent, payload, knowledge, feedback), variant=f"r{round_}")
            verdict, ok_f5, f5 = self._review(agent, out, ctx, round_)
            self.tel.emit(event="f5_check", req_id=req_id, agent=agent_name, round=round_, ok=ok_f5, metrics=f5)
            blocking = any(h["severidad"] in ("bloqueante", "mayor") for h in verdict["hallazgos"])
            if verdict["veredicto"] == "aprobado" and not blocking:
                gate = self._gate(agent, verdict, ctx) if agent.gate else {"decision": "approved"}
                if gate["decision"] in ("approved", "pending"):
                    self._save(ctx, ARTEFACT_NAME[agent_name], out, {"verdict": verdict, "f5": f5, "gate": gate, "model": stats})
                    self.examples.append({"agent": agent_name, "req_id": req_id, "rounds": round_, "f5": {k: v["value"] for k, v in f5.items()},
                                          "messages": self._messages(agent, payload, knowledge), "output": out})
                    return out
                feedback = [{"severidad": "mayor", "regla": "gate_humano", "detalle": f"devuelto por {gate['role']}", "ubicacion": "<raíz>"}]
            elif verdict["veredicto"] == "escalar":
                self.tel.emit(event="escalation", req_id=req_id, agent=agent_name, round=round_, to=self.reg.gates["escalation"]["to"])
                self._save(ctx, ARTEFACT_NAME[agent_name], out, {"verdict": verdict, "f5": f5, "escalated": True, "model": stats})
                return out
            else:
                feedback = verdict["hallazgos"]
        self.tel.emit(event="escalation", req_id=req_id, agent=agent_name, round=max_rounds, to=self.reg.gates["escalation"]["to"], reason="max_rounds")
        raise ContractError(f"{agent_name}/{req_id}: rechazado por gobernanza {max_rounds + 1} veces")

    def _save(self, ctx, name, artefact, meta):
        out_dir = self.root / "data/requerimientos" / ctx["req_id"] / "output"; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{name}.json").write_text(json.dumps(artefact, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"{name}.decision.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        from . import render                                  # formatos estándar derivados de forma determinista
        if name == "api_design":
            (out_dir / "api_design.openapi.yaml").write_text(render.openapi_yaml(artefact), encoding="utf-8")
        if name == "cicd_pipeline":
            for p in artefact.get("pipelines", []):
                (out_dir / f"{p['id']}.{p['ambiente']}.workflow.yaml").write_text(render.workflow_yaml(p), encoding="utf-8")
        ctx[name] = artefact

    # ---------- DAG ----------
    def _payload(self, node: dict, ctx: dict, stage_art: dict):
        ins = node.get("inputs", [])
        if ins == ["intake"]:
            return ctx["business_request"]
        if len(ins) == 1:
            return ctx[stage_art[ins[0]]]
        return {stage_art[i]: ctx[stage_art[i]] for i in ins}

    def run(self, req_id: str) -> dict:
        req_dir = self.root / "data/requerimientos" / req_id
        ctx = {"req_id": req_id}
        nodes = [n for st in self.reg.dag["stages"] for n in (st.get("parallel") or [st])]
        stage_art = {n["id"]: ARTEFACT_NAME[n["agent"]] for n in nodes if n.get("agent")}
        self.tel.emit(event="pipeline_started", req_id=req_id, dag=self.reg.dag["pipeline"])
        for stage in self.reg.dag["stages"]:
            if stage.get("action") == "load_business_request":
                br = load_business_request(req_dir)
                jsonschema.validate(br, self.reg.agents["product-analyst-agent"].input_schema)
                ctx["business_request"] = br
                self.tel.emit(event="intake", req_id=req_id, puntos=br["puntos_historia"], reglas=br["reglas_negocio"])
            elif stage.get("action") == "emit_handoff":
                self.tel.emit(event="handoff", req_id=req_id, frm=stage.get("from", "discovery"), to=stage.get("to", "arquitectura"), mode="auto",
                              artefacts=[stage_art[i] for i in stage.get("inputs", []) if i in stage_art and stage_art[i] in ctx])
            elif "parallel" in stage:
                with ThreadPoolExecutor(max_workers=len(stage["parallel"])) as ex:
                    futs = [ex.submit(self.run_agent, n["agent"], self._payload(n, ctx, stage_art), ctx) for n in stage["parallel"]]
                    for f in futs:
                        f.result()
            else:
                self.run_agent(stage["agent"], self._payload(stage, ctx, stage_art), ctx)
        self.tel.emit(event="pipeline_completed", req_id=req_id, artefacts=[k for k in ARTEFACT_NAME.values() if k in ctx])
        return ctx
