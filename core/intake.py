"""Normaliza los artefactos de entrada de un requerimiento (data/requerimientos/<id>/input/*) al contrato
BusinessRequest v1.0. Es código determinista: no interviene ningún modelo."""
import json, re
from pathlib import Path


def _section(md: str, title: str) -> str:
    m = re.search(rf"^##\s+{re.escape(title)}\s*\n(.*?)(?=^##\s|\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def _table_field(md: str, field: str) -> str:
    m = re.search(rf"^\|\s*{re.escape(field)}\s*\|\s*(.*?)\s*\|\s*$", md, re.M)
    return m.group(1).strip() if m else ""


def load_business_request(req_dir: Path) -> dict:
    inp = Path(req_dir) / "input"
    brief = (inp / "brief.md").read_text(encoding="utf-8")
    restr = json.loads((inp / "restricciones.json").read_text(encoding="utf-8"))
    titulo = re.search(r"^#\s+Brief\s+[—-]\s+(.*)$", brief, re.M)
    restricciones = [l.lstrip("- ").strip() for l in _section(brief, "Restricciones conocidas").splitlines() if l.strip().startswith("-")]
    tipo = restr.get("tipo", "Funcional")
    if tipo not in ("Funcional", "No funcional", "Técnico", "Regulatorio"):
        tipo = "Funcional"
    br = {"contract_version": "1.0",
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
    return br
