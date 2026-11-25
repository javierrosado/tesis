"""eval_n3: depuración de pruebas de referencia (solo exigen lo que la entrada fija)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval_n3"))
from depurar_pruebas import depurar_suite  # noqa: E402

SUITE = """def test_a(client, db):
    payload = {'estado': 'PENDIENTE'}
    r = client.post('/v1/x', json=payload)
    assert r.status_code == 201
    assert r.json()['estado'] == 'PENDIENTE'
    assert r.json()['envio'] == 'ENVIADO'
    assert 'ERR-101' not in r.text
    if r.status_code == 201:
        assert r.json()['cursor'] == '2'

def test_b(client, db):
    r = client.get('/v1/x/C-999')
    assert r.json()['detail'] == 'ERR-001'
""".splitlines()


def test_quita_err_y_literales_no_especificados():
    lineas, q = depurar_suite(SUITE, permitido='{"ruta": "/v1/x"} C-999')
    src = "\n".join(lineas)
    compile(src, "t", "exec")                                   # el if que quedó vacío lleva pass
    assert "r.status_code == 201" in src and "'PENDIENTE'" in src  # literal presente en el payload de la propia prueba
    assert "ENVIADO" not in src and "ERR-" not in src and "'2'" not in src
    assert "def test_b" not in src                              # sin asserts → sale
    assert q == {"err": 2, "literal": 2, "pruebas_sin_asserts": 1}
