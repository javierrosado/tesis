"""Pruebas de contrato y de DAG con el proveedor mock (sin red, sin GPU). Se ejecutan en CI."""
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
    assert {"product-analyst-agent", "domain-modeling-agent", "ux-ui-copilot-agent", "governance-agent"} <= set(REG.agents)
    for a in REG.agents.values():
        assert a.prompt.strip(), a.name
        jsonschema.Draft202012Validator.check_schema(a.output_schema)


def test_schemas_have_provenance():
    for n in ("product-analyst-agent", "domain-modeling-agent", "ux-ui-copilot-agent"):
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


def test_dag_runs_with_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_PROVIDER", "mock")
    tel = Telemetry(tmp_path / "ev.jsonl")
    ctx = Orchestrator(ROOT, tel, seed=1).run("SIM-P05-R001")
    assert {"user_story_set", "domain_model", "ux_spec"} <= set(ctx)
    ev = tel.read()
    kinds = [e["event"] for e in ev]
    assert kinds[0] == "pipeline_started" and kinds[-1] == "pipeline_completed"
    assert sum(1 for e in ev if e["event"] == "governance_verdict" and e["verdict"] == "rechazado") == 1   # ronda 0 rechazada
    assert all("provider" in e and "model_id" in e for e in ev if e["event"] == "agent_completed")   # trazabilidad del proveedor
    gates = [e for e in ev if e["event"] == "human_gate"]
    assert {g["artefact"] for g in gates} == {"user_story_set", "domain_model", "ux_spec"}


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
