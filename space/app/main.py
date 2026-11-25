"""Consola del Piloto HAI-SSDLC (Fase C): backend FastAPI + front web/PWA en un HF Docker Space privado.

Sin Claude en el circuito: la consola solo lee el dataset privado, registra decisiones humanas y lanza el job de pesos
abiertos (jobs/run_pipeline_job.py). Cada acción relevante queda en piloto/<p>/accesos.jsonl (R1).

Variables: PILOT (piloto1), RUNS_REPO (jrosado1974/tesis-piloto), CONSOLA_USUARIOS (JSON), CONSOLA_LOCAL (carpeta, pruebas),
           CONSOLA_BRANCH, CONSOLA_JOB_ENV (JSON), CONSOLA_FLAVOR, HF_TOKEN y GITHUB_TOKEN como secrets del Space.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import vistas

sys.path.insert(0, str(vistas.REPO))
sys.path.insert(0, str(vistas.REPO / "scripts"))
import pilot_control as pc

from core import calendario

from . import alta as alta_mod
from . import ejecutor as ej
from . import roles
from .almacen import desde_entorno

PILOT = os.environ.get("PILOT", "piloto1")
STATIC = Path(__file__).parent / "static"


def crear_app(almacen=None, ejecutor=None, usuario_fijo: str | None = None) -> FastAPI:
    """`usuario_fijo` solo para pruebas y modo local; en el Space la identidad viene del OAuth de HF."""
    app = FastAPI(title="Consola del Piloto HAI-SSDLC", docs_url=None, redoc_url=None)
    app.state.almacen = almacen or desde_entorno()
    app.state.ejecutor = ejecutor
    if usuario_fijo is None:
        from huggingface_hub import attach_huggingface_oauth
        attach_huggingface_oauth(app)

    def _ej():
        if app.state.ejecutor is None:
            app.state.ejecutor = ej.Ejecutor()
        return app.state.ejecutor

    # ------------------------------------------------------------ identidad, permisos y R1
    def usuario(request: Request) -> str:
        if usuario_fijo is not None:
            u = request.headers.get("X-Usuario-Prueba", usuario_fijo)
        else:
            from huggingface_hub import parse_huggingface_oauth
            info = parse_huggingface_oauth(request)
            u = info.user_info.preferred_username if info else None
        if not u:
            raise HTTPException(401, "Inicia sesión con Hugging Face")
        if not roles.roles_de(u):
            raise HTTPException(403, f"{u} no está autorizado en la consola")
        return u

    def exigir(accion: str):
        def dep(request: Request, u: str = Depends(usuario)) -> str:
            if not roles.puede(u, accion):
                registrar_acceso(request, u, f"denegado:{accion}", request.url.path)
                raise HTTPException(403, f"tu rol no permite: {accion}")
            return u
        return dep

    def registrar_acceso(request: Request, u: str, accion: str, objetivo: str) -> None:
        reg = {"ts": calendario.ahora_lima(), "usuario": u, "rol": ",".join(roles.roles_de(u)), "accion": accion,
               "objetivo": objetivo, "dispositivo": "pwa" if request.headers.get("X-Consola-Dispositivo") == "pwa" else "desktop"}
        try:
            app.state.almacen.agregar_linea(f"piloto/{PILOT}/accesos.jsonl", json.dumps(reg, ensure_ascii=False), f"acceso {accion}")
        except Exception as e:  # noqa: BLE001 — el registro de accesos no debe tumbar la acción, pero se avisa en el log
            print("R1: no se pudo registrar el acceso:", str(e)[:200], flush=True)

    def carpeta(sub: str = "") -> Path:
        return app.state.almacen.carpeta(f"piloto/{PILOT}" + (f"/{sub}" if sub else ""))

    def telemetria() -> list[dict]:
        d = carpeta("telemetria")
        return [e for f in sorted(d.glob("*.jsonl")) if d.exists() for e in pc_cargar(f)]

    # ------------------------------------------------------------ páginas
    @app.get("/", include_in_schema=False)
    def inicio():
        return FileResponse(STATIC / "index.html")

    @app.get("/sw.js", include_in_schema=False)
    def sw():
        return FileResponse(STATIC / "sw.js", media_type="application/javascript")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/yo")
    def yo(request: Request, u: str = Depends(usuario)):
        registrar_acceso(request, u, "login", "-")
        cfg = calendario.config(PILOT) or {}
        return {"usuario": u, "nombre": roles.nombre(u), "roles": roles.roles_de(u), "pilot": PILOT,
                "permisos": sorted(a for a in roles.PERMISOS if roles.puede(u, a)), "ahora_lima": calendario.ahora_lima(),
                "cierre_ventanas": cfg.get("cierre_ventanas", []), "dias_release": [str(d) for d in cfg.get("dias_release", [])],
                "inicio": str(cfg.get("inicio", "")), "fin": str(cfg.get("fin", ""))}

    # ------------------------------------------------------------ D1 · tablero
    @app.get("/api/tablero")
    def tablero(request: Request, u: str = Depends(exigir("consultar"))):
        registrar_acceso(request, u, "consultar", "tablero")
        return vistas.tablero(carpeta("estado"), carpeta("requerimientos"))

    # ------------------------------------------------------------ D3 · DAG y panel por paso
    @app.get("/api/req/{req}/dag")
    def dag(req: str, request: Request, u: str = Depends(exigir("consultar"))):
        _req_ok(req)
        registrar_acceso(request, u, "consultar", req)
        return vistas.dag(carpeta("estado"), req)

    @app.get("/api/req/{req}/paso/{art}")
    def paso(req: str, art: str, request: Request, u: str = Depends(exigir("consultar"))):
        _req_ok(req)
        registrar_acceso(request, u, "consultar", f"{req}/{art}")
        try:
            return vistas.paso(carpeta("estado"), req, art, telemetria())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    # ------------------------------------------------------------ D4 · gates
    @app.get("/api/gates")
    def gates(request: Request, u: str = Depends(exigir("consultar"))):
        registrar_acceso(request, u, "consultar", "gates")
        return [{**p, "discrepancia": vistas.discrepancia(p)} for p in pc.listar_pendientes(carpeta("estado"))]

    @app.post("/api/gates/decidir")
    async def decidir(request: Request, u: str = Depends(exigir("decidir"))):
        body = await request.json()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        spec = {"ventana": body.get("ventana") or calendario.ahora_lima(), "por": roles.nombre(u), "usuario_hf": u,
                "instruccion": body.get("instruccion", "decisión registrada en la consola"),
                "canal": "pwa" if request.headers.get("X-Consola-Dispositivo") == "pwa" else "desktop",
                "decisiones": body.get("decisiones", [])}
        if not spec["decisiones"]:
            raise HTTPException(400, "sin decisiones")
        app.state.almacen.invalidar()
        try:
            ops, regs = pc.registros_lote(carpeta("estado"), spec, PILOT, ts)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        app.state.almacen.commit(ops, f"{PILOT}: ventana {spec['ventana']} · {len(regs)} decisiones (consola)")
        for r in regs:
            registrar_acceso(request, u, "aprobar" if r["decision"] == "approved" else "devolver", f"{r['req']}/{r['artefacto']}")
        return {"registradas": len(regs), "ts": ts, "registros": regs}

    # ------------------------------------------------------------ D2 · alta
    @app.post("/api/alta")
    async def alta(request: Request, modo: str = Form("validar"), zip: UploadFile | None = File(None),
                   formulario: str | None = Form(None), u: str = Depends(exigir("alta"))):
        try:
            arch = alta_mod.desde_zip(await zip.read()) if zip is not None else alta_mod.desde_formulario(json.loads(formulario or "{}"))
            res = alta_mod.validar(arch)
        except (alta_mod.AltaError, KeyError) as e:
            raise HTTPException(422, f"no válido: {e}") from e
        req = res["business_request"]["req_id"]
        if modo != "confirmar":
            return res
        app.state.almacen.invalidar()
        if (carpeta("estado") / req / "output" / "estado.json").exists() or (carpeta("requerimientos") / req / "input").exists():
            raise HTTPException(409, f"{req} ya existe: el input es inmutable desde el alta")
        ops = [(f"piloto/{PILOT}/requerimientos/{req}/input/{n}", b) for n, b in arch.items()]
        ops.append((f"piloto/{PILOT}/requerimientos/{req}/alta.json",
                    json.dumps({"req_id": req, "sha256": res["sha256"], "registrado_por": u, "ts": calendario.ahora_lima(),
                                "contract_version": "1.1"}, ensure_ascii=False, indent=1).encode()))
        app.state.almacen.commit(ops, f"{PILOT}: alta {req}")
        registrar_acceso(request, u, "alta", req)
        return {**res, "registrado": True}

    # ------------------------------------------------------------ ejecución (D1 · Reanudar ahora, log en vivo)
    @app.post("/api/reanudar")
    async def reanudar(request: Request, u: str = Depends(exigir("reanudar"))):
        body = await request.json() if (await request.body()) else {}
        reqs = [r for r in body.get("reqs", []) if _req_ok(r)] or None
        r = _ej().reanudar(PILOT, reqs, u)
        registrar_acceso(request, u, "reanudar", ",".join(reqs or ["ALL"]))
        return r

    @app.get("/api/jobs")
    def jobs(u: str = Depends(exigir("consultar"))):
        return _ej().jobs()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str, u: str = Depends(exigir("consultar"))):
        return _ej().inspeccionar(_id_ok(job_id))

    @app.get("/api/jobs/{job_id}/logs")
    def logs(job_id: str, agente: str | None = None, tail: int = 400, u: str = Depends(exigir("consultar"))):
        lineas = _ej().logs(_id_ok(job_id), min(max(tail, 10), 2000))
        evs = ej.eventos(lineas, agente)
        texto = [ln for ln in lineas if "EVENT {" not in ln and (agente is None or agente in ln)]
        return {"lineas": texto[-300:], "eventos": evs}

    @app.post("/api/jobs/{job_id}/cancelar")
    def cancelar(job_id: str, request: Request, u: str = Depends(exigir("reanudar"))):
        _ej().cancelar(_id_ok(job_id))
        registrar_acceso(request, u, "cancelar", job_id)
        return {"cancelado": job_id}

    @app.get("/api/programacion")
    def programacion(u: str = Depends(exigir("consultar"))):
        return _ej().programacion()

    @app.post("/api/programacion")
    async def programar(request: Request, u: str = Depends(exigir("reanudar"))):
        body = await request.json()
        e = _ej()
        if "activo" in body:
            res = e.interruptor(bool(body["activo"]))
        else:
            res = e.programar(PILOT, (calendario.config(PILOT) or {}).get("cierre_ventanas", []))
        registrar_acceso(request, u, "reanudar", f"programacion:{body}")
        return res

    # ------------------------------------------------------------ D5 · despliegues y defectos
    @app.post("/api/defecto")
    async def defecto(request: Request, u: str = Depends(exigir("registrar"))):
        b = await request.json(); _req_ok(b.get("req", ""))
        if b.get("etapa_deteccion") not in ("smoke", "staging", "aceptacion") or b.get("severidad") not in ("critica", "alta", "media", "baja") \
                or not str(b.get("descripcion", "")).strip():
            raise HTTPException(422, "etapa_deteccion, severidad y descripción son obligatorias")
        reg = pc.registro_defecto(b["req"], b["etapa_deteccion"], b["severidad"], b["descripcion"], b.get("etapa_origen"), roles.nombre(u))
        app.state.almacen.agregar_linea(f"piloto/{PILOT}/registros/defectos_escapados.jsonl", json.dumps(reg, ensure_ascii=False),
                                        f"{PILOT} {b['req']} defect_detected")
        registrar_acceso(request, u, "registrar", f"defecto:{b['req']}")
        return reg

    @app.post("/api/despliegue")
    async def despliegue(request: Request, u: str = Depends(exigir("registrar"))):
        b = await request.json(); _req_ok(b.get("req", ""))
        if b.get("resultado") not in ("rollback", "correccion") or not str(b.get("motivo", "")).strip():
            raise HTTPException(422, "resultado (rollback/correccion) y motivo son obligatorios")
        reg = pc.registro_despliegue(b["req"], b["resultado"], b["motivo"], roles.nombre(u))
        app.state.almacen.agregar_linea(f"piloto/{PILOT}/registros/post_despliegue.jsonl", json.dumps(reg, ensure_ascii=False),
                                        f"{PILOT} {b['req']} deployment_outcome")
        registrar_acceso(request, u, "registrar", f"despliegue:{b['req']}")
        return reg

    @app.get("/api/registros")
    def registros(u: str = Depends(exigir("consultar"))):
        d = carpeta("registros")
        return {f.stem: list(pc_cargar(f)) for f in sorted(d.glob("*.jsonl"))} if d.exists() else {}

    # ------------------------------------------------------------ D6 · indicadores
    @app.get("/api/indicadores")
    def indicadores(request: Request, u: str = Depends(exigir("consultar"))):
        import indicadores as ind
        ev = telemetria() + [e for f in sorted(carpeta("registros").glob("*.jsonl")) if carpeta("registros").exists() for e in pc_cargar(f)]
        registrar_acceso(request, u, "consultar", "indicadores")
        cfg = calendario.config(PILOT)
        return {"agentes": ind.calcular(ev), "hipotesis": ind.hipotesis(ev, carpeta("estado"), cfg) if ev else None, "eventos": len(ev)}

    # ------------------------------------------------------------ D7 · auditoría y R4
    @app.get("/api/auditoria")
    def auditoria(request: Request, u: str = Depends(exigir("auditoria"))):
        registrar_acceso(request, u, "consultar", "auditoria")
        a = vistas.auditoria(carpeta("estado"))
        d = carpeta()
        a["accesos"] = list(pc_cargar(d / "accesos.jsonl"))[-500:] if (d / "accesos.jsonl").exists() else []
        man = vistas.REPO / "runs" / "MANIFEST.md"
        txt = man.read_text(encoding="utf-8") if man.exists() else ""
        a["desviaciones"] = txt[txt.find("## Desviaciones piloto1"):] if "## Desviaciones piloto1" in txt else ""
        return a

    @app.get("/api/evidencia.zip")
    def evidencia(request: Request, u: str = Depends(exigir("exportar"))):
        registrar_acceso(request, u, "exportar", "evidencia.zip")
        app.state.almacen.invalidar()
        datos = vistas.evidencia_zip(carpeta(), PILOT)
        return Response(datos, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="evidencia_{PILOT}.zip"'})

    @app.exception_handler(FileNotFoundError)
    def _nf(_: Request, e: FileNotFoundError):
        return JSONResponse({"detail": f"no encontrado: {Path(str(e)).name}"}, status_code=404)

    return app


def _req_ok(req: str) -> bool:
    if not alta_mod.REQ_ID.match(req or ""):
        raise HTTPException(400, "REQ-ID inválido")
    return True


def _id_ok(job_id: str) -> str:
    if not job_id.isalnum():
        raise HTTPException(400, "job_id inválido")
    return job_id


def pc_cargar(f: Path):
    for ln in f.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                yield json.loads(ln)
            except json.JSONDecodeError:
                continue


if os.environ.get("SPACE_ID") or os.environ.get("CONSOLA_SERVIR"):
    # en el Space siempre OAuth; CONSOLA_USUARIO_LOCAL solo sirve fuera del Space (modo local)
    app = crear_app(usuario_fijo=None if os.environ.get("SPACE_ID") else os.environ.get("CONSOLA_USUARIO_LOCAL"))
