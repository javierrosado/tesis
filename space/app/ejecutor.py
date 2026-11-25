"""Jobs de HF desde la consola: reanudar (manual), reanudación automática (Scheduled Jobs), inspeccionar, logs y cancelar.

El job que se lanza es el mismo de siempre (jobs/run_pipeline_job.py), con GATES_MODE=manual y el piloto del dataset
privado. La consola no ejecuta modelos: solo lanza el job de pesos abiertos y lee su salida.
"""
from __future__ import annotations

import json
import os

from . import vistas

ETIQUETA = {"app": "consola-piloto"}


def env_job(pilot: str, reqs: list[str] | None = None) -> dict:
    env = {"PILOT": pilot, "RUNS_REPO": os.environ.get("RUNS_REPO", "jrosado1974/tesis-piloto"), "GATES_MODE": "manual",
           "BRANCH": os.environ.get("CONSOLA_BRANCH", "main"), "TELEMETRY_ECHO": "1"}
    if os.environ.get("CONSOLA_TAG"):
        env["TAG"] = os.environ["CONSOLA_TAG"]        # Fase B: v1.0-piloto (o v1.0.x-piloto tras una desviación)
    env |= json.loads(os.environ.get("CONSOLA_JOB_ENV", "{}"))      # ADAPTERS, NIVELES, WORKERS… fijados al congelar
    if reqs:
        env["REQS"] = ",".join(reqs)
    else:
        env["ALL"] = "1"
    return env


def cron_utc(hhmm: str) -> str:
    """Cierre de ventana en hora de Lima (UTC−5, sin horario de verano) → cron UTC."""
    h, m = map(int, hhmm.split(":"))
    return f"{m} {(h + 5) % 24} * * *"


class Ejecutor:
    def __init__(self, api=None):
        if api is None:
            from huggingface_hub import HfApi
            api = HfApi()
        self.api = api
        self.script = str(vistas.REPO / "jobs" / "run_pipeline_job.py")
        self.flavor = os.environ.get("CONSOLA_FLAVOR", "a100-large")
        self.secrets = {k: os.environ[k] for k in ("HF_TOKEN", "GITHUB_TOKEN") if os.environ.get(k)}

    def reanudar(self, pilot: str, reqs: list[str] | None, por: str) -> dict:
        j = self.api.run_uv_job(self.script, env=env_job(pilot, reqs), secrets=self.secrets, flavor=self.flavor,
                                timeout=os.environ.get("CONSOLA_TIMEOUT", "4h"), labels={**ETIQUETA, "pilot": pilot, "por": por[:40]})
        return {"job_id": j.id, "url": getattr(j, "url", None)}

    def jobs(self) -> list[dict]:
        res = []
        for j in self.api.list_jobs(labels=ETIQUETA):
            res.append({"job_id": j.id, "estado": getattr(j.status, "stage", str(j.status)),
                        "creado": str(getattr(j, "created_at", "")), "labels": getattr(j, "labels", {})})
        return sorted(res, key=lambda x: x["creado"], reverse=True)[:30]

    def inspeccionar(self, job_id: str) -> dict:
        j = self.api.inspect_job(job_id=job_id)
        return {"job_id": j.id, "estado": getattr(j.status, "stage", str(j.status)), "mensaje": getattr(j.status, "message", None)}

    def logs(self, job_id: str, tail: int = 400) -> list[str]:
        return list(self.api.fetch_job_logs(job_id=job_id, tail=tail))

    def cancelar(self, job_id: str) -> None:
        self.api.cancel_job(job_id=job_id)

    # ---- reanudación automática (D-C5): un Scheduled Job por cierre de ventana
    def programacion(self) -> list[dict]:
        return [{"id": s.id, "schedule": getattr(s, "schedule", None), "suspendido": bool(getattr(s, "suspend", False))}
                for s in self.api.list_scheduled_jobs(labels=ETIQUETA)]

    def programar(self, pilot: str, cierres: list[str]) -> list[dict]:
        existentes = {p["schedule"] for p in self.programacion()}
        nuevos = []
        for c in cierres:
            cron = cron_utc(c)
            if cron in existentes:
                continue
            s = self.api.create_scheduled_uv_job(self.script, schedule=cron, concurrency=False, env=env_job(pilot), secrets=self.secrets,
                                                 flavor=self.flavor, timeout=os.environ.get("CONSOLA_TIMEOUT", "4h"),
                                                 labels={**ETIQUETA, "pilot": pilot, "cierre": c.replace(":", "")})
            nuevos.append({"id": s.id, "schedule": cron})
        return nuevos

    def interruptor(self, activo: bool) -> list[dict]:
        for p in self.programacion():
            (self.api.resume_scheduled_job if activo else self.api.suspend_scheduled_job)(scheduled_job_id=p["id"])
        return self.programacion()


def eventos(lineas: list[str], agente: str | None = None) -> list[dict]:
    """Líneas `EVENT {json}` del log (G3) → eventos para el DAG en vivo."""
    res = []
    for ln in lineas:
        i = ln.find("EVENT {")
        if i < 0:
            continue
        try:
            e = json.loads(ln[i + 6:])
        except json.JSONDecodeError:
            continue
        if agente is None or e.get("agent") == agente:
            res.append(e)
    return res

