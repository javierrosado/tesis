"""v2 · eval_n3: congelamiento de entradas y defectos sembrados (sobre los artefactos de ejemplo de tests/fixtures)."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "eval_n3"))
FX = ROOT / "tests" / "fixtures"


def _caso(tmp_path):
    c = tmp_path / "SIM-E01-R001"; (c / "pipeline_v1").mkdir(parents=True)
    for art, ag in (("api_design", "api-designer-agent"), ("data_model", "data-model-agent")):
        (c / "pipeline_v1" / f"{art}.json").write_text((FX / ag / "SIM-P05-R001.json").read_text(encoding="utf-8"), encoding="utf-8")
    (c / "servicio_limpio.json").write_text((FX / "backend-developer-agent" / "SIM-P05-R001.json").read_text(encoding="utf-8"), encoding="utf-8")
    (c / "pruebas_aceptacion.json").write_text((FX / "qa-automation-agent" / "SIM-P05-R001.json").read_text(encoding="utf-8"), encoding="utf-8")
    return c


def test_mutaciones_de_linea():
    import sembrar
    assert sembrar._mutar_linea("    if a == b and c:", None)[0] == 2
    assert sembrar._mutar_linea("    if a == b and c:", 0)[0] == "    if a != b and c:"
    assert {sembrar._mutar_linea("return x + 1", k)[0] for k in (0, 1)} == {"return x + 2", "return x - 1"}
    assert sembrar._mutar_linea("raise HTTPException(status_code=404, detail='ERR-101')", None)[0] == 1


def test_sembrar_produce_defectos_detectables(tmp_path):
    import sembrar
    ds = sembrar.sembrar(_caso(tmp_path), n_logica=1, n_seguridad=1)
    tipos = {d["tipo"] for d in ds}
    assert "seguridad" in tipos
    for d in ds:
        assert (tmp_path / "SIM-E01-R001" / "defectos" / f"{d['id']}.json").exists()
        if d["tipo"] == "logica":
            assert d["pruebas_que_fallan"] >= 1
        else:
            assert d["bandit_detecta"]
