"""Normaliza los artefactos de entrada de un requerimiento (data/requerimientos/<id>/input/*) al contrato
BusinessRequest. Es código determinista: no interviene ningún modelo.
v1.1 (G1, D-C7): además de brief.md y restricciones.json incorpora historia_original.md, criterios_aceptacion.md y
notas_refinamiento.md como texto (obligatorios). v1.0 se conserva para comparar el adaptador de product-analyst (G4)."""
import json, re
from pathlib import Path


def _section(md: str, title: str) -> str:
    m = re.search(rf"^##\s+{re.escape(title)}\s*\n(.*?)(?=^##\s|\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def _table_field(md: str, field: str) -> str:
    m = re.search(rf"^\|\s*{re.escape(field)}\s*\|\s*(.*?)\s*\|\s*$", md, re.M)
    return m.group(1).strip() if m else ""


CONTEXTO_V11 = ("historia_original", "criterios_aceptacion", "notas_refinamiento")


class IntakeError(ValueError):
    pass


def _texto(md: str) -> str:
    """Contenido del .md sin el título de primer nivel."""
    lineas = md.strip().splitlines()
    if lineas and lineas[0].startswith("# "):
        lineas = lineas[1:]
    return "\n".join(lineas).strip()


def load_business_request(req_dir: Path, version: str = "1.1") -> dict:
    if version not in ("1.0", "1.1"):
        raise IntakeError(f"versión de BusinessRequest no soportada: {version}")
    inp = Path(req_dir) / "input"
    brief = (inp / "brief.md").read_text(encoding="utf-8")
    restr = json.loads((inp / "restricciones.json").read_text(encoding="utf-8"))
    titulo = re.search(r"^#\s+Brief\s+[—-]\s+(.*)$", brief, re.M)
    restricciones = [l.lstrip("- ").strip() for l in _section(brief, "Restricciones conocidas").splitlines() if l.strip().startswith("-")]
    tipo = restr.get("tipo", "Funcional")
    if tipo not in ("Funcional", "No funcional", "Técnico", "Regulatorio"):
        tipo = "Funcional"
    br = {"contract_version": version,
          "req_id": restr["req_id"],
          "proyecto": _table_field(brief, "Proyecto") or "SIM",
          "titulo": titulo.group(1).strip() if titulo else _table_field(brief, "Requerimiento"),
          "tipo": tipo,
          "origen": restr.get("origen", ""),
          "solicitante": _table_field(brief, "Solicitante"),
          "campana": restr.get("campana", ""),
          "necesidad": _section(brief, "Necesidad de negocio"),
          "resultado_esperado": _section(brief, "Resultado esperado"),
          "restricciones": restricciones,
          "reglas_negocio": [r[:6] for r in restr.get("reglas_negocio_referenciadas", [])],
          "preguntas_abiertas": restr.get("preguntas_abiertas", []),
          "puntos_historia": int(restr.get("puntos_historia", 3)),
          "datos_personales": bool(restr.get("datos_personales_involucrados", False))}
    if restr.get("fecha_release_comprometida"):
        br["fecha_release_comprometida"] = restr["fecha_release_comprometida"]
    if version == "1.1":
        faltan = [n for n in CONTEXTO_V11 if not (inp / f"{n}.md").exists()]
        if faltan:
            raise IntakeError(f"BusinessRequest v1.1 requiere {', '.join(f + '.md' for f in faltan)} en {inp}")
        for n in CONTEXTO_V11:
            br[n] = _texto((inp / f"{n}.md").read_text(encoding="utf-8"))
    return br
