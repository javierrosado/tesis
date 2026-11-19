"""Casos F5 de governance-agent (Tabla 19): conforme → aprobado; campo ausente → rechazado con regla y ubicación."""
import copy, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry   # noqa: E402
from core import governance          # noqa: E402

REG = Registry(ROOT)
PA = REG.agents["product-analyst-agent"]
FIX = json.loads(next((ROOT / "tests/fixtures/product-analyst-agent").glob("*.json")).read_text(encoding="utf-8"))
CTX = {"req_id": FIX["provenance"]["req_id"], "business_request": {"reglas_negocio": sorted({b for h in FIX["historias"] for b in h.get("reglas_negocio", [])})}}


def test_conforme_aprobado():
    v, ok, _ = governance.review(PA, FIX, CTX, 0)
    assert v["veredicto"] == "aprobado" and ok, v["hallazgos"]
    assert v["requiere_humano"] is True


def test_campo_ausente_rechazado():
    bad = copy.deepcopy(FIX); bad.pop("provenance")
    v, ok, _ = governance.review(PA, bad, CTX, 0)
    assert v["veredicto"] == "rechazado" and not ok
    assert all(h["regla"] and h["ubicacion"] for h in v["hallazgos"])


def test_procedencia_sin_refs_rechazado():
    bad = copy.deepcopy(FIX); bad["provenance"]["knowledge_refs"] = []
    v, _, _ = governance.review(PA, bad, CTX, 0)
    assert v["veredicto"] == "rechazado" and any(h["regla"] == "procedencia_h5" for h in v["hallazgos"])


def test_veredicto_cumple_contrato_governance():
    import jsonschema
    v, _, _ = governance.review(PA, FIX, CTX, 0)
    jsonschema.validate(v, REG.agents["governance-agent"].output_schema)
