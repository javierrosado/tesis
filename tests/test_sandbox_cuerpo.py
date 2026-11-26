"""Normalización del cuerpo de los handlers en render_app (eval_n3 25/11, humo N4 26/11)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tools.sandbox import _cuerpo  # noqa: E402


def test_quita_def_y_sangria_comun():
    assert _cuerpo(["def _ep_001(x):", "    if x:", "        return 1", "    return 2"]) == ["if x:", "    return 1", "return 2"]
    assert _cuerpo(["    y = 1", "    return y"]) == ["y = 1", "return y"]


def test_cuerpo_correcto_no_cambia():
    v1 = ["for p in DB['pedido']:", "    if p['id'] == x:", "        return p", "raise HTTPException(status_code=404, detail='no')"]
    assert _cuerpo(v1) == v1 and _cuerpo(None) == []
