"""Adaptación del schema a la gramática de vLLM: no pierde estructura ni límites de cardinalidad."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry                         # noqa: E402
from core.adapters.openai_compat import _grammar_safe      # noqa: E402


def test_grammar_safe_conserva_limites():
    s = Registry(ROOT).agents["api-designer-agent"].output_schema
    g = _grammar_safe(s)
    ep = g["properties"]["endpoints"]
    assert ep["maxItems"] == 12 and ep["items"]["properties"]["respuestas"]["maxItems"] == 3
    assert ep["items"]["properties"]["respuestas"]["items"]["properties"]["status"]["maximum"] == 299
    ruta = ep["items"]["properties"]["ruta"]
    assert "pattern" in ruta and "maxLength" not in ruta
    assert "pattern" not in json.dumps(_grammar_safe(s, drop_patterns=True))
