"""G4 · Contexto v1.1 sintético para el conjunto de prueba de product-analyst (decisión del autor, 24/11/2026, opción A).

Los 24 casos de prueba de tesis-sft-v2 se construyeron con BusinessRequest v1.0 y no tienen historia original, criterios
ni notas de refinamiento. Para medir si el adaptador LoRA de product-analyst baja con entradas v1.1, se generan esos tres
textos para cada caso sin cambiar nada más del BusinessRequest:

- historia_original: la redacta el maestro (Qwen3-32B-AWQ) como texto libre e informal a partir del propio BusinessRequest;
- criterios_aceptacion: en el 70 % de los casos "_No documentados_" (la misma proporción de los 30 requerimientos del piloto,
  21 de 30); en el resto el maestro redacta de 2 a 4 criterios a partir del resultado esperado;
- notas_refinamiento: plantilla determinista con las reglas, las preguntas abiertas y los puntos del propio BusinessRequest.

La asignación es determinista (hash del req_id). Los textos se declaran sintéticos y se publican con los resultados."""
import hashlib, json, re

BLOCK = re.compile(r"(## Entrada[^\n]*\n```json\n)(.*?)(\n```)", re.S)
NO_DOC = ("_No documentados en el registro original._\n\nLas condiciones de aceptación se acordaron verbalmente en el refinamiento; "
          "ver `notas_refinamiento.md`. El pipeline debe derivarlas (product-analyst) y validarlas con el aprobador humano.")
PROPORCION_NO_DOC = 0.7

TEXTO_SCHEMA = {"title": "TextoLibre", "type": "object", "additionalProperties": False, "required": ["texto"],
                "properties": {"texto": {"type": "string", "minLength": 60, "maxLength": 900}}}


def _u(req_id: str, sal: str) -> float:
    return int(hashlib.sha256(f"{sal}:{req_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def documentados(req_ids: list[str]) -> set[str]:
    """Casos con criterios escritos: exactamente round(30 %) de los casos, elegidos por hash (reproducible)."""
    ids = sorted(set(req_ids), key=lambda r: _u(r, "criterios"))
    return set(ids[:round(len(ids) * (1 - PROPORCION_NO_DOC))])


def prompt_historia(br: dict) -> list[dict]:
    return [{"role": "user", "content":
             "Escribe el registro original de este pedido tal como lo dejó el área de negocio: texto libre, informal, de 2 a 5 "
             "frases, a veces ambiguo, sin formato de historia de usuario, sin inventar reglas ni datos que no estén abajo. "
             "Empieza con una línea entre corchetes que diga de dónde salió (correo, reunión, chat o ticket) y quién lo pidió.\n\n"
             f"Solicitante: {br.get('solicitante', '')}\nTítulo: {br['titulo']}\nNecesidad: {br['necesidad']}\n"
             f"Resultado esperado: {br['resultado_esperado']}\nCampaña: {br.get('campana', '')}\n\nResponde solo con el JSON."}]


def prompt_criterios(br: dict) -> list[dict]:
    return [{"role": "user", "content":
             "Escribe entre 2 y 4 criterios de aceptación breves (una viñeta '- ' cada uno), tal como los anotaría el área de "
             "negocio antes del refinamiento: en lenguaje de negocio, sin formato Gherkin y sin cubrir todos los casos. Usa solo "
             f"lo que dice el pedido.\n\nTítulo: {br['titulo']}\nResultado esperado: {br['resultado_esperado']}\n"
             f"Restricciones: {'; '.join(br.get('restricciones', []))}\n\nResponde solo con el JSON."}]


def notas_refinamiento(br: dict, documentado: bool) -> str:
    ciclos = 1 + int(_u(br["req_id"], "ciclos") * 2)
    lineas = [f"Ciclos de refinamiento registrados: **{ciclos}**  ·  Puntos de historia asignados: **{br['puntos_historia']}**", "",
              "## Sesión 1", "", f"- Se presenta la necesidad: {br['necesidad'][:220].rstrip()}",
              "- Reglas de negocio mencionadas: " + (", ".join(br.get("reglas_negocio", [])) or "ninguna")]
    lineas += [f"- Pregunta abierta: {p}  → **sin resolver al cierre de la sesión**" for p in br.get("preguntas_abiertas", [])]
    lineas.append(f"- Estimación: {br['puntos_historia']} puntos. Se pasa a desarrollo sin criterios escritos; el equipo asume el alcance conversado."
                  if not documentado else f"- Estimación: {br['puntos_historia']} puntos. Se revisan los criterios anotados por el negocio.")
    return "\n".join(lineas)


def br_v11(br10: dict, historia: str, criterios: str | None) -> dict:
    br = dict(br10, contract_version="1.1")
    br["historia_original"] = historia.strip()
    br["criterios_aceptacion"] = (criterios or NO_DOC).strip()
    br["notas_refinamiento"] = notas_refinamiento(br10, criterios is not None)
    return br


def leer_br(messages: list[dict]) -> dict:
    return json.loads(BLOCK.search(messages[1]["content"]).group(2))


def con_br(messages: list[dict], br: dict) -> list[dict]:
    """Mismos mensajes del caso de prueba, con el bloque de entrada reemplazado por el BusinessRequest dado (sin el oro)."""
    user = BLOCK.sub(lambda m: m.group(1) + json.dumps(br, ensure_ascii=False, indent=1) + m.group(3), messages[1]["content"], count=1)
    return [messages[0], {"role": "user", "content": user}]
