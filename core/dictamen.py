"""Dictamen IA de las puertas humanas (G5, decisión D-C4 / D-P3).

Cada vez que una puerta queda pendiente de decisión humana, el job genera un dictamen con dos partes:
1. governance determinista: veredicto, hallazgos y métricas F5 del artefacto (lo que una regla puede verificar);
2. el modelo maestro del pipeline (Qwen3-32B-AWQ), que aplica el checklist v1.0 del rol (docs/checklists_gates.md).

El dictamen se guarda en pendientes/<artefacto>.json, aparte de la decisión humana, para medir la concordancia
humano–IA (R3). No reemplaza al aprobador. En backend, qa y code_review el maestro también produce el artefacto:
esa autoevaluación queda marcada en el propio dictamen (`autoevaluacion: true`) y se declara como limitación.
Si el maestro no está disponible, el dictamen queda solo con la parte determinista (`estado: solo_governance`)."""
import json, re
from pathlib import Path

SECCION = {"user_story_set": "PO", "solution_architecture": "TL-A", "security_compliance": "SA", "data_model": "DA",
           "code_review": "TL-C", "release_plan": "RM"}
ITEM = re.compile(r"^\|\s*((?:PO|TL-A|SA|DA|TL-C|RM)-\d+)\s*\|\s*(.*?)\s*\|")
MAX_ARTEFACTO = 24000          # caracteres del artefacto que entran al prompt

SCHEMA = {"title": "dictamen_gate", "type": "object", "additionalProperties": False,
          "required": ["recomendacion", "items", "motivo_sugerido"],
          "properties": {"recomendacion": {"enum": ["approved", "returned"]},
                         "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                              "required": ["id", "cumple", "evidencia"],
                                                              "properties": {"id": {"type": "string"}, "cumple": {"type": "boolean"},
                                                                             "evidencia": {"type": "string", "maxLength": 500}}}},
                         "motivo_sugerido": {"type": "string", "maxLength": 1500}}}

SISTEMA = ("Eres el asistente de revisión de una puerta humana de un pipeline de software. Evalúas un artefacto con el "
           "checklist del rol y propones una decisión; la decisión final la toma una persona. Reglas: (1) governance ya "
           "verificó contrato y métricas: no las repitas, juzga el contenido; (2) recomienda 'approved' solo si TODOS los "
           "ítems se cumplen; (3) si devuelves, el motivo cita el ítem y dice qué cambiar, en una o dos frases por ítem; "
           "(4) usa solo la evidencia que está en el artefacto y en el contexto; si no hay evidencia suficiente, marca el "
           "ítem como no cumplido y dilo. Responde solo con el JSON pedido.")


def checklist(root: Path) -> dict[str, list[tuple[str, str]]]:
    items: dict[str, list[tuple[str, str]]] = {}
    for linea in (Path(root) / "docs/checklists_gates.md").read_text(encoding="utf-8").splitlines():
        m = ITEM.match(linea)
        if m:
            items.setdefault(m.group(1).rsplit("-", 1)[0], []).append((m.group(1), m.group(2)))
    return items


def _governance(verdict: dict, f5: dict | None, escalado: bool) -> dict:
    return {"veredicto": "rechazado (escalado)" if escalado else verdict.get("veredicto", "aprobado"),
            "hallazgos": len(verdict.get("hallazgos", [])),
            "f5_ok": all(v.get("ok", True) for v in (f5 or {}).values()) if isinstance(f5, dict) else None}


def _mensajes(art: str, rol: str, items: list, out: dict, contexto: dict, verdict: dict) -> list[dict]:
    lista = "\n".join(f"- {i}: {t}" for i, t in items) or "- (este rol no tiene checklist: juzga si el artefacto cumple su propósito)"
    cuerpo = json.dumps({k: v for k, v in out.items() if k != "provenance"}, ensure_ascii=False)
    if len(cuerpo) > MAX_ARTEFACTO:
        cuerpo = cuerpo[:MAX_ARTEFACTO] + " …(truncado)"
    user = (f"## Puerta\nArtefacto `{art}` · rol `{rol}`\n\n## Checklist\n{lista}\n\n"
            f"## Resultado de governance\n```json\n{json.dumps({'veredicto': verdict.get('veredicto'), 'hallazgos': verdict.get('hallazgos', [])}, ensure_ascii=False)}\n```\n\n"
            f"## Contexto\n```json\n{json.dumps(contexto, ensure_ascii=False)[:8000]}\n```\n\n"
            f"## Artefacto\n```json\n{cuerpo}\n```\n\n"
            f"## Salida\nJSON con `recomendacion` (approved|returned), `items` (uno por ítem del checklist: id, cumple, evidencia) "
            f"y `motivo_sugerido` (vacío si apruebas).")
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": user}]


def dictaminar(root: Path, adapter, art: str, rol: str, out: dict, verdict: dict, f5: dict | None, contexto: dict,
               escalado: bool = False, autoevaluacion: bool = False, ts: str = "") -> dict:
    """Devuelve el dictamen IA de una puerta. `adapter` es el proveedor del maestro o None si no está disponible."""
    gov = _governance(verdict, f5, escalado)
    items = checklist(root).get(SECCION.get(art, ""), [])
    base = {"governance": gov, "checklist": SECCION.get(art), "autoevaluacion": autoevaluacion, "ts": ts,
            "recomendacion_governance": "returned" if escalado or gov["hallazgos"] else "approved"}
    if adapter is None:
        return {**base, "estado": "solo_governance", "recomendacion": base["recomendacion_governance"], "items": [],
                "motivo_sugerido": "", "modelo": None, "proveedor": None, "discrepancia_governance": False}
    try:
        r = adapter.complete(_mensajes(art, rol, items, out, contexto, verdict), SCHEMA)
        d = json.loads(r.text.strip().removeprefix("```json").removesuffix("```").strip())
        ids = {i for i, _ in items}
        its = [x for x in d.get("items", []) if not ids or x.get("id") in ids]
        rec = d.get("recomendacion")
        if any(not x.get("cumple") for x in its):          # regla común 2 del checklist: un «No» basta para devolver
            rec = "returned"
        return {**base, "estado": "ok", "recomendacion": rec, "items": its, "motivo_sugerido": d.get("motivo_sugerido", ""),
                "items_faltantes": sorted(ids - {x.get("id") for x in its}), "modelo": r.model_id, "proveedor": r.provider,
                "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "latency_ms": r.latency_ms,
                "discrepancia_governance": rec != base["recomendacion_governance"]}
    except Exception as e:  # noqa: BLE001
        return {**base, "estado": "error_modelo", "error": str(e)[:300], "recomendacion": base["recomendacion_governance"],
                "items": [], "motivo_sugerido": "", "modelo": getattr(adapter, "model", None), "proveedor": getattr(adapter, "name", None),
                "discrepancia_governance": False}
