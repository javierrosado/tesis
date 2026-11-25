"""Pruebas de contrato y de DAG con el proveedor prueba_offline (sin modelo, sin red, sin GPU). Se ejecutan en CI."""
import json, os, sys
from pathlib import Path
import jsonschema, pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry            # noqa: E402
from core.intake import load_business_request  # noqa: E402
from core.telemetry import Telemetry           # noqa: E402
from core.orchestrator import Orchestrator     # noqa: E402

REG = Registry(ROOT)


def test_all_agents_load():
    assert len(REG.agents) == 14   # 13 funcionales + governance (knowledge-rag y skill-orchestrator son herramienta y orquestador)
    for a in REG.agents.values():
        assert a.prompt.strip(), a.name
        jsonschema.Draft202012Validator.check_schema(a.output_schema)


def test_schemas_have_provenance():
    for n in [a for a in REG.agents if a != "governance-agent"]:
        props = REG.agents[n].output_schema["properties"]
        assert "provenance" in props and "knowledge_refs" in props["provenance"]["properties"], n


def test_fixtures_match_contracts():
    for d in (ROOT / "tests/fixtures").iterdir():
        agent = REG.agents[d.name]
        for f in d.glob("*.json"):
            jsonschema.validate(json.loads(f.read_text(encoding="utf-8")), agent.output_schema)


def test_intake_matches_business_request_contract():
    br = load_business_request(ROOT / "data/requerimientos/SIM-P05-R001")
    jsonschema.validate(br, REG.agents["product-analyst-agent"].input_schema)
    assert br["reglas_negocio"] == ["BR-010", "BR-011"]


def test_dag_runs_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROVIDER", "prueba_offline")
    tel = Telemetry(tmp_path / "ev.jsonl")
    import shutil
    shutil.rmtree(ROOT / "data/requerimientos/SIM-P05-R001/output", ignore_errors=True)
    orch = Orchestrator(ROOT, tel, seed=1, today="2026-11-24"); orch.reg.gates["mode"] = "auto"
    ctx = orch.run("SIM-P05-R001")
    assert {"user_story_set", "domain_model", "ux_spec"} <= set(ctx)
    ev = tel.read()
    kinds = [e["event"] for e in ev]
    assert kinds[0] == "pipeline_started" and kinds[-1] == "pipeline_completed"
    assert sum(1 for e in ev if e["event"] == "governance_verdict" and e["verdict"] == "rechazado") == 1   # ronda 0 rechazada
    assert all("provider" in e and "model_id" in e for e in ev if e["event"] == "agent_completed")   # trazabilidad del proveedor
    gates = [e for e in ev if e["event"] == "human_gate"]
    from core.orchestrator import ARTEFACT_NAME
    assert {g["artefact"] for g in gates} == set(ARTEFACT_NAME.values())
    assert ctx["_estado"] == "validado_sin_despliegue"


def test_capability_check_blocks_unfit_provider():
    class Weak:
        name = "weak"
        def capabilities(self): return {"json_mode": False, "context_tokens": 2000, "tools": []}
        def complete(self, *a, **k): raise AssertionError("no debería llamarse")
    from core.model_port import ModelPort, ContractError
    port = ModelPort(Weak(), Telemetry(Path(os.devnull)))
    with pytest.raises(ContractError):
        port.run(REG.agents["product-analyst-agent"], "X", [])


def test_dataset_builder_produces_contract_valid_examples(tmp_path, monkeypatch):
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_dataset.py"), "--variants", "3", "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    agent = REG.agents["product-analyst-agent"]
    train = [json.loads(l) for l in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    test = [json.loads(l) for l in (tmp_path / "test.jsonl").read_text(encoding="utf-8").splitlines()]
    assert train and test and not ({e["req_id"] for e in train} & {e["req_id"] for e in test})   # sin fuga entre particiones
    for e in train[:20]:
        jsonschema.validate(json.loads(e["messages"][2]["content"]), agent.output_schema)
    from core.eval_dataset import evaluate_predictions
    res = evaluate_predictions(agent, test, [e["messages"][2]["content"] for e in test])   # el oro contra sí mismo
    assert res["aggregate"]["f5_pass"] == 1.0


def test_intake_v11_incluye_contexto_y_cumple_el_contrato():
    """G1 (D-C7): BusinessRequest v1.1 lleva historia_original, criterios_aceptacion y notas_refinamiento."""
    schema = REG.agents["product-analyst-agent"].input_schema
    for d in sorted((ROOT / "data/requerimientos").iterdir()):
        if (d / "input").exists():
            br = load_business_request(d)
            jsonschema.validate(br, schema)
            assert br["contract_version"] == "1.1" and all(br[k] for k in ("historia_original", "criterios_aceptacion", "notas_refinamiento"))
    br0 = load_business_request(ROOT / "data/requerimientos/SIM-P05-R001", version="1.0")
    jsonschema.validate(br0, schema)
    assert "historia_original" not in br0
    sin = dict(br0, contract_version="1.1")
    import pytest
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(sin, schema)


def test_intake_v11_exige_los_tres_archivos(tmp_path):
    import pytest, shutil
    from core.intake import IntakeError
    shutil.copytree(ROOT / "data/requerimientos/SIM-P05-R001/input", tmp_path / "input")
    (tmp_path / "input" / "notas_refinamiento.md").unlink()
    with pytest.raises(IntakeError, match="notas_refinamiento"):
        load_business_request(tmp_path)


def test_inputs_auditables_y_eventos_en_vivo(tmp_path, monkeypatch, capsys):
    """G2: cada llamada a un agente deja <artefacto>.input.r<n>.json; G3: cada evento sale también como línea EVENT."""
    import shutil
    monkeypatch.setenv("PIPELINE_PROVIDER", "prueba_offline")
    monkeypatch.setenv("MODEL_REVS", json.dumps({"base": "Qwen/Qwen3-8B@abc", "modelos": {}, "loras": {}}))
    tel = Telemetry(tmp_path / "ev.jsonl", echo=True)
    out = ROOT / "data/requerimientos/SIM-P05-R001/output"
    shutil.rmtree(out, ignore_errors=True)
    orch = Orchestrator(ROOT, tel, seed=1, today="2026-11-24"); orch.reg.gates["mode"] = "auto"
    orch.run("SIM-P05-R001")
    rec = json.loads((out / "user_story_set.input.r0.json").read_text(encoding="utf-8"))
    assert rec["agente"] == "product-analyst-agent" and rec["ronda"] == 0
    assert set(rec["inputs"]) and all(v.startswith("sha256:") for v in rec["inputs"].values())
    assert rec["knowledge_sha256"].startswith("sha256:") and rec["prompt_sha256"].startswith("sha256:")
    assert rec["ts"].endswith("-05:00") and rec["proveedor"]
    eventos = [l for l in capsys.readouterr().out.splitlines() if l.startswith("EVENT ")]
    assert eventos and json.loads(eventos[0][6:])["event"]
    assert len(eventos) == len(tel.read())


def test_g4_contexto_v11_sintetico():
    """G4: el contexto v1.1 de los casos de prueba solo agrega los tres textos y respeta el contrato."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import g4_contexto as g4
    br10 = load_business_request(ROOT / "data/requerimientos/SIM-P05-R001", version="1.0")
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "## Entrada (x)\n```json\n" + json.dumps(br10, indent=1) + "\n```\n\nresto"}]
    assert g4.leer_br(msgs) == br10
    br11 = g4.br_v11(br10, "[Correo] texto libre del pedido original, informal y con algo de ambigüedad.", None)
    jsonschema.validate(br11, REG.agents["product-analyst-agent"].input_schema)
    assert {k for k in br11 if br11.get(k) != br10.get(k)} == {"contract_version", "historia_original", "criterios_aceptacion", "notas_refinamiento"}
    assert g4.leer_br(g4.con_br(msgs, br11)) == br11 and br11["criterios_aceptacion"].startswith("_No documentados")
    ids = [f"SIM-T01-R{i:03d}" for i in range(24)]
    assert len(g4.documentados(ids)) == 7 and g4.documentados(ids) == g4.documentados(list(reversed(ids)))
