"""Calendario del piloto (protocolo F5 v2): días de release, feriados, días hábiles y marcas de tiempo en hora de Lima.

El piloto activo se elige con la variable PILOT; su calendario está en config/piloto.yaml. Sin piloto configurado
se aplica la regla general de la política de release: martes o jueves."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LIMA = timezone(timedelta(hours=-5), "America/Lima")      # Perú no usa horario de verano


def config(pilot: str | None = None) -> dict | None:
    pilot = pilot if pilot is not None else os.environ.get("PILOT")
    if not pilot:
        return None
    data = yaml.safe_load((ROOT / "config/piloto.yaml").read_text(encoding="utf-8")) or {}
    cfg = data.get(pilot)
    if cfg is None:
        return None
    norm = lambda xs: [x if isinstance(x, date) else date.fromisoformat(str(x)) for x in xs]
    out = dict(cfg)
    for k in ("inicio", "fin"):
        out[k] = cfg[k] if isinstance(cfg[k], date) else date.fromisoformat(str(cfg[k]))
    out["dias_release"] = norm(cfg.get("dias_release", []))
    out["feriados"] = norm(cfg.get("feriados", []))
    out["releases_movidos"] = {str(k): str(v) for k, v in (cfg.get("releases_movidos") or {}).items()}
    out["nombre"] = pilot
    return out


def ahora_lima() -> str:
    return datetime.now(LIMA).isoformat(timespec="seconds")


def hoy_lima() -> str:
    return datetime.now(LIMA).date().isoformat()


def a_lima(ts: str) -> str:
    """Convierte un ISO-8601 (con zona) a hora de Lima."""
    return datetime.fromisoformat(ts).astimezone(LIMA).isoformat(timespec="seconds")


def es_dia_release(d: date, cfg: dict | None) -> bool:
    if cfg and cfg.get("dias_release"):
        return d in cfg["dias_release"]
    feriados = cfg.get("feriados", []) if cfg else []
    return d.weekday() in (1, 3) and d not in feriados


def ventana_valida(ventana: str, hoy: str, cfg: dict | None) -> bool:
    try:
        v = date.fromisoformat(ventana)
    except (TypeError, ValueError):
        return False
    return v >= date.fromisoformat(hoy) and es_dia_release(v, cfg)


def dias_release_desde(hoy: str, cfg: dict | None, n: int = 4) -> list[str]:
    """Próximos días de release permitidos, a partir de hoy (incluido)."""
    h = date.fromisoformat(hoy)
    if cfg and cfg.get("dias_release"):
        return [d.isoformat() for d in cfg["dias_release"] if d >= h][:n]
    out, d = [], h
    while len(out) < n:
        if es_dia_release(d, cfg):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def es_habil(d: date, feriados: list[date]) -> bool:
    return d.weekday() < 5 and d not in feriados


def sumar_dias_habiles(d: date, n: int, feriados: list[date]) -> date:
    """Fecha que cae n días hábiles después de d (sin contar d)."""
    x, k = d, 0
    while k < n:
        x += timedelta(days=1)
        if es_habil(x, feriados):
            k += 1
    return x


def dias_entre(t0: str, t1: str) -> float:
    """Días (con decimales) entre dos marcas ISO-8601."""
    return round((datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds() / 86400, 3)
