"""Evaluación de un modelo sobre el conjunto de prueba del dataset (ablación Fase 3).
Métricas por ejemplo: validez JSON, validez de contrato (schema), gwt_ratio, br_coverage (F5),
y coincidencia exacta del conjunto de reglas BR citadas. Agregadas como promedio.
Uso: generar `pred` por cada ejemplo del test con el modelo (texto) y llamar evaluate_predictions."""
import json, re
import jsonschema
from .model_port import _strip_fences
from . import verify


def _business_request_from_prompt(user_msg: str) -> dict:
    m = re.search(r"## Entrada.*?```json\n(.*?)\n```", user_msg, re.S)
    return json.loads(m.group(1)) if m else {}


def evaluate_predictions(agent, examples: list[dict], preds: list[str]) -> dict:
    rows = []
    for ex, pred in zip(examples, preds):
        br = _business_request_from_prompt(ex["messages"][1]["content"])
        gold = json.loads(ex["messages"][2]["content"])
        row = {"req_id": ex["req_id"], "json_valid": 0, "schema_valid": 0, "gwt_ratio": 0.0, "br_coverage": 0.0, "br_exact": 0}
        try:
            out = json.loads(_strip_fences(pred)); row["json_valid"] = 1
            jsonschema.validate(out, agent.output_schema); row["schema_valid"] = 1
            m = verify.metrics_product_analyst(out, {"business_request": br})
            row["gwt_ratio"], row["br_coverage"] = m["gwt_ratio"], m["br_coverage"]
            row["br_exact"] = int({b for h in out["historias"] for b in h["reglas_negocio"]} == {b for h in gold["historias"] for b in h["reglas_negocio"]})
        except Exception:  # noqa: BLE001
            pass
        rows.append(row)
    n = len(rows) or 1
    agg = {k: round(sum(r[k] for r in rows) / n, 3) for k in ("json_valid", "schema_valid", "gwt_ratio", "br_coverage", "br_exact")}
    agg["n"] = len(rows)
    agg["f5_pass"] = round(sum(1 for r in rows if r["schema_valid"] and r["gwt_ratio"] >= 0.9 and r["br_coverage"] == 1.0) / n, 3)
    return {"aggregate": agg, "rows": rows}
