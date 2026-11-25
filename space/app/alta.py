"""D2 · Alta de requerimientos (formulario o ZIP de la carpeta input/), validada con intake v1.1 y el JSON Schema."""
from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

import jsonschema

from core.intake import CONTEXTO_V11, IntakeError, load_business_request

from . import vistas

ARCHIVOS = ("brief.md", "restricciones.json") + tuple(f"{n}.md" for n in CONTEXTO_V11)
MAX_BYTES = 200_000
REQ_ID = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,40}$")


class AltaError(ValueError):
    pass


def desde_formulario(f: dict) -> dict[str, bytes]:
    """Campos del formulario → los 5 archivos con el formato que espera intake."""
    restr = {"req_id": f["req_id"].strip(), "tipo": f.get("tipo", "Funcional"), "origen": f.get("origen", ""),
             "campana": f.get("campana", ""), "fecha_registro": f.get("fecha_registro", ""),
             "fecha_release_comprometida": f.get("fecha_release_comprometida") or None,
             "puntos_historia": int(f.get("puntos_historia") or 3),
             "datos_personales_involucrados": str(f.get("datos_personales", "")).lower() in ("1", "true", "si", "sí", "on"),
             "reglas_negocio_referenciadas": [x.strip() for x in f.get("reglas_negocio", "").split(",") if x.strip()],
             "preguntas_abiertas": [x.strip() for x in f.get("preguntas_abiertas", "").splitlines() if x.strip()]}
    restr = {k: v for k, v in restr.items() if v is not None}
    rest = "\n".join(f"- {x.strip()}" for x in f.get("restricciones", "").splitlines() if x.strip()) or "- Ninguna"
    brief = (f"# Brief — {f['titulo'].strip()}\n\n| Campo | Valor |\n|---|---|\n| Requerimiento | {restr['req_id']} |\n"
             f"| Proyecto | {f.get('proyecto', 'SIM').strip()} |\n| Solicitante | {f.get('solicitante', '').strip()} |\n\n"
             f"## Necesidad de negocio\n\n{f['necesidad'].strip()}\n\n## Resultado esperado\n\n{f['resultado_esperado'].strip()}\n\n"
             f"## Restricciones conocidas\n\n{rest}\n")
    arch = {"brief.md": brief.encode(), "restricciones.json": json.dumps(restr, ensure_ascii=False, indent=1).encode()}
    titulos = {"historia_original": "Historia original", "criterios_aceptacion": "Criterios de aceptación",
               "notas_refinamiento": "Notas de refinamiento"}
    for n in CONTEXTO_V11:
        txt = (f.get(n) or "").strip() or "_No documentados_"
        arch[f"{n}.md"] = f"# {titulos[n]}\n\n{txt}\n".encode()
    return arch


def desde_zip(datos: bytes) -> dict[str, bytes]:
    """Solo se toman los 5 archivos conocidos (por nombre base); se ignoran rutas y cualquier otro contenido."""
    if len(datos) > 5 * MAX_BYTES:
        raise AltaError("ZIP demasiado grande")
    arch = {}
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        for info in z.infolist():
            nombre = Path(info.filename).name
            if info.is_dir() or nombre not in ARCHIVOS:
                continue
            if info.file_size > MAX_BYTES:
                raise AltaError(f"{nombre} supera {MAX_BYTES} bytes")
            arch[nombre] = z.read(info)
    return arch


def sha(arch: dict[str, bytes]) -> str:
    """Mismo cálculo que vistas.sha_input (nombre + contenido, en orden)."""
    h = hashlib.sha256()
    for n in sorted(arch):
        h.update(n.encode()); h.update(arch[n])
    return h.hexdigest()


def validar(arch: dict[str, bytes]) -> dict:
    faltan = [n for n in ARCHIVOS if n not in arch]
    if faltan:
        raise AltaError("faltan archivos: " + ", ".join(faltan))
    with tempfile.TemporaryDirectory() as d:
        inp = Path(d) / "input"; inp.mkdir()
        for n, b in arch.items():
            (inp / n).write_bytes(b)
        try:
            br = load_business_request(Path(d), version="1.1")
        except (IntakeError, KeyError, ValueError, json.JSONDecodeError) as e:
            raise AltaError(f"intake v1.1: {e}") from e
    if not REQ_ID.match(br["req_id"]):
        raise AltaError(f"req_id inválido: {br['req_id']}")
    schema = json.loads((vistas.REPO / "contracts" / "business_request.schema.json").read_text(encoding="utf-8"))
    errores = sorted(jsonschema.Draft202012Validator(schema).iter_errors(br), key=lambda e: list(e.path))
    if errores:
        raise AltaError("schema: " + "; ".join(f"{'/'.join(map(str, e.path)) or '(raíz)'}: {e.message}" for e in errores[:5]))
    return {"business_request": br, "sha256": sha(arch), "archivos": sorted(arch)}
