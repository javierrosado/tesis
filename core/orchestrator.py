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
from . import verify

ARTEFACT_NAME = {"product-analyst-agent": "user_story_set", "domain-modeling-agent": "domain_model",
                 "ux-ui-copilot-agent": "ux_spec"}


class Orchestrator:
    def __init__(self, root: Path, telemetry: Telemetry, seed: int = 2026):
        self.root = Path(root)
        self.reg = Registry(self.root)
        self.tel = telemetry
        self.rag = KnowledgeRag(self.root / "data/knowledge")
        self.rng = random.Random(seed)
        self.gov = self.reg.agents["governance-agent"]

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
        if agent.name == "ux-ui-copilot-agent":
            qs += ["convenciones de interfaz componentes", "accesibilidad"]
        if agent.name == "domain-modeling-agent":
            qs += ["glosario pedido estado", "especificación pedidos"]
        return qs

    # ---------- governance ----------
    def _review(self, producer, artefact: dict, ctx: dict, round_: int) -> dict:
        payload = {"artefacto": ARTEFACT_NAME[producer.name], "agente_evaluado": producer.name, "ronda": round_,
                   "criterios_f5": producer.verification, "gate": producer.gate, "contenido": artefact}
        knowledge, refs = self.rag.context_block(["política", "seguridad", "release"] + ctx["business_request"]["reglas_negocio"], k=3)
        out, stats = self._port(self.gov).run(self.gov, ctx["req_id"], self._messages(self.gov, payload, knowledge), variant=f"{producer.name}-r{round_}")
        self.tel.emit(event="governance_verdict", agent=self.gov.name, req_id=ctx["req_id"], target=producer.name, round=round_,
                      verdict=out["veredicto"], findings=len(out["hallazgos"]), provider=stats["provider"], model_id=stats["model_id"])
        return out

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
            verdict = self._review(agent, out, ctx, round_)
            ok_f5, f5 = verify.evaluate(agent, out, ctx, {"refinement_rounds": round_})
            self.tel.emit(event="f5_check", req_id=req_id, agent=agent_name, round=round_, ok=ok_f5, metrics=f5)
            blocking = any(h["severidad"] == "bloqueante" for h in verdict["hallazgos"])
            if not ok_f5:                                   # F5 se evalúa en código: manda sobre el veredicto del modelo
                feedback = [{"severidad": "bloqueante", "regla": f"F5.{k}", "detalle": f"{v['rule']} (valor {v['value']})", "ubicacion": "<artefacto>"}
                            for k, v in f5.items() if not v["ok"] and k != "refinement_rounds"] + verdict["hallazgos"]
                if any(h["severidad"] == "bloqueante" for h in feedback):
                    continue
            if verdict["veredicto"] == "aprobado" and not blocking:
                gate = self._gate(agent, verdict, ctx) if agent.gate else {"decision": "approved"}
                if gate["decision"] in ("approved", "pending"):
                    self._save(ctx, ARTEFACT_NAME[agent_name], out, {"verdict": verdict, "f5": f5, "gate": gate, "model": stats})
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
        ctx[name] = artefact

    # ---------- DAG ----------
    def run(self, req_id: str) -> dict:
        req_dir = self.root / "data/requerimientos" / req_id
        ctx = {"req_id": req_id}
        self.tel.emit(event="pipeline_started", req_id=req_id, dag=self.reg.dag["pipeline"])
        for stage in self.reg.dag["stages"]:
            if stage.get("action") == "load_business_request":
                br = load_business_request(req_dir)
                jsonschema.validate(br, self.reg.agents["product-analyst-agent"].input_schema)
                ctx["business_request"] = br
                self.tel.emit(event="intake", req_id=req_id, puntos=br["puntos_historia"], reglas=br["reglas_negocio"])
            elif stage.get("action") == "emit_handoff":
                self.tel.emit(event="handoff", req_id=req_id, frm="discovery", to="arquitectura", mode="auto",
                              artefacts=[k for k in ARTEFACT_NAME.values() if k in ctx])
            elif "parallel" in stage:
                with ThreadPoolExecutor(max_workers=len(stage["parallel"])) as ex:
                    futs = {ex.submit(self.run_agent, n["agent"], ctx[ARTEFACT_NAME["product-analyst-agent"]], ctx): n for n in stage["parallel"]}
                    for f in futs:
                        f.result()
            else:
                self.run_agent(stage["agent"], ctx["business_request"], ctx)
        self.tel.emit(event="pipeline_completed", req_id=req_id, artefacts=[k for k in ARTEFACT_NAME.values() if k in ctx])
        return ctx
