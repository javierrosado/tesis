"""Humo ADR-009 (26/11): llamadas de prueba sin parámetros requeridos o con response.json[...]."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.verify import llamadas_invalidas  # noqa: E402

API = {"endpoints": [{"id": "EP-001", "metodo": "GET", "ruta": "/v1/pedidos", "parametros": [{"nombre": "consultoraId", "en": "query", "requerido": True}]},
                     {"id": "EP-002", "metodo": "GET", "ruta": "/v1/pedidos/{pedidoId}", "parametros": [{"nombre": "pedidoId", "en": "path", "requerido": True}]}]}


def _suite(*cuerpos):
    lineas = []
    for i, c in enumerate(cuerpos):
        lineas += [f"def test_{i}(client, db):"] + ["    " + x for x in c] + [""]
    return {"suites": [{"id": "SA-001", "casos": [], "lineas": lineas}]}


def test_detecta_parametro_requerido_y_json_sin_llamar():
    malas = llamadas_invalidas(_suite(["r = client.get('/v1/pedidos', params={'estado': 'x'})", "assert r.status_code == 200"],
                                      ["r = client.get('/v1/pedidos/P-1')", "assert r.json['estado'] == 'ok'"]), API)
    assert len(malas) == 2 and "consultoraId" in malas[0] and "response.json()" in malas[1]


def test_llamadas_correctas_pasan():
    ok = _suite(["r = client.get('/v1/pedidos', params={'consultoraId': 'C-1'})", "assert r.json()['pedidos'] == []"],
                ["r = client.get('/v1/pedidos?consultoraId=C-1')", "assert r.status_code == 200"],
                ["r = client.get('/v1/pedidos/P-1')", "assert r.status_code == 404"])
    assert llamadas_invalidas(ok, API) == []
