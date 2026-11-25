"""Usuarios autorizados y permisos de la consola (D-C3, D-P2).

Lista blanca en la variable CONSOLA_USUARIOS (JSON usuario-HF → roles). Para piloto1 (D-P2) solo está Javier, con los
tres roles; el asesor no entra a la app y recibe el paquete de evidencia (R4). Si más adelante se agrega su cuenta, va
con el rol `auditor` (solo lectura).
"""
from __future__ import annotations

import json
import os

POR_DEFECTO = {"jrosado1974": ["operador", "registrador", "aprobador"]}

# acción → roles que pueden ejecutarla
PERMISOS = {
    "consultar": {"operador", "registrador", "aprobador", "auditor"},
    "alta": {"operador", "registrador"},
    "decidir": {"aprobador"},
    "reanudar": {"operador"},
    "registrar": {"operador"},          # defectos escapados y resultado post-despliegue
    "exportar": {"operador", "auditor"},
    "auditoria": {"operador", "auditor"},
}

NOMBRES = {"jrosado1974": "Javier Rosado"}


def usuarios() -> dict[str, list[str]]:
    raw = os.environ.get("CONSOLA_USUARIOS")
    return json.loads(raw) if raw else POR_DEFECTO


def roles_de(usuario: str | None) -> list[str]:
    return usuarios().get(usuario or "", [])


def puede(usuario: str | None, accion: str) -> bool:
    return bool(set(roles_de(usuario)) & PERMISOS[accion])


def nombre(usuario: str) -> str:
    return json.loads(os.environ.get("CONSOLA_NOMBRES", "{}")).get(usuario) or NOMBRES.get(usuario, usuario)
