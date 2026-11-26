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


def test_contenido_vacio_reintenta_con_mas_tokens(monkeypatch):
    """eval_n3 (25/11): DeepSeek V4-Pro devolvía content=None al agotar los tokens razonando."""
    from core.adapters.openai_compat import OpenAICompatAdapter
    ad = OpenAICompatAdapter({"model": "m", "max_new_tokens": 100})
    vistos = []

    def post(body):
        vistos.append(body["max_tokens"])
        txt = None if len(vistos) == 1 else '{"ok": 1}'
        return {"choices": [{"message": {"content": txt}, "finish_reason": "length" if txt is None else "stop"}], "usage": {}}
    monkeypatch.setattr(ad, "_post", post)
    assert ad.complete([{"role": "user", "content": "x"}]).text == '{"ok": 1}' and vistos == [100, 200]


def test_anthropic_cae_a_tool_choice_auto(monkeypatch):
    """25/11: claude-opus-5-5 responde 400 a tool_choice forzado; el adaptador reintenta con auto."""
    import sys, types
    llamadas = []

    class Msgs:
        def create(self, **kw):
            llamadas.append(kw["tool_choice"]["type"])
            if kw["tool_choice"]["type"] == "tool":
                raise RuntimeError('400 tool_choice: type "tool" and "any" are not supported for this model.')
            b = types.SimpleNamespace(type="tool_use", input={"ok": 1})
            return types.SimpleNamespace(content=[b], model="claude-opus-5-5", usage=types.SimpleNamespace(input_tokens=1000, output_tokens=500))
    fake = types.SimpleNamespace(Anthropic=lambda **kw: types.SimpleNamespace(messages=Msgs()))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    from core.adapters.anthropic_adapter import AnthropicAdapter
    ad = AnthropicAdapter({"model": "claude-opus-5-5"})
    r = ad.complete([{"role": "user", "content": "x"}], {"type": "object"})
    assert r.text == '{"ok": 1}' and llamadas == ["tool", "auto"] and r.meta["costo_usd"] == 0.014
    ad.complete([{"role": "user", "content": "x"}], {"type": "object"})
    assert llamadas[-1] == "auto"


def test_respuesta_cortada_por_longitud_reintenta(monkeypatch):
    """humo N4 (26/11): finish_reason=length con JSON a medias se trata como vacío."""
    from core.adapters.openai_compat import OpenAICompatAdapter
    ad = OpenAICompatAdapter({"model": "m", "max_new_tokens": 100})
    vistos = []

    def post(body):
        vistos.append(body["max_tokens"])
        corta = len(vistos) == 1
        return {"choices": [{"message": {"content": '{"a": [1,' if corta else '{"a": [1, 2]}'}, "finish_reason": "length" if corta else "stop"}],
                "usage": {"cost": 0.01}}
    monkeypatch.setattr(ad, "_post", post)
    r = ad.complete([{"role": "user", "content": "x"}])
    assert r.text == '{"a": [1, 2]}' and vistos == [100, 200]
