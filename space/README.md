---
title: Consola del Piloto HAI-SSDLC
emoji: 🧭
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
hf_oauth: true
hf_oauth_expiration_minutes: 480
pinned: false
---

# Consola del Piloto (Fase C)

App de operación de piloto1 **sin Claude en el circuito** (especificación v1.1, `claude/Consola_Piloto_Especificacion_v1.md`).
Backend FastAPI + front web responsive y PWA. Lee y escribe el dataset privado `jrosado1974/tesis-piloto` y lanza el job de
pesos abiertos `jobs/run_pipeline_job.py`.

| Pantalla | Ruta | Permiso |
|---|---|---|
| D1 Tablero | `#tablero` | consultar |
| D2 Alta (formulario o ZIP, intake v1.1 + schema, SHA-256) | `#alta` | alta (solo desktop) |
| D3 DAG y panel por paso (Input, Output, Rondas, Decisión y dictamen, Devoluciones, Eventos) | `#req/<REQ>[/<artefacto>]` | consultar |
| D4 Gates (aviso de discrepancia governance/IA, motivo obligatorio al devolver) | `#gates` | decidir |
| Ejecución (Reanudar ahora, Scheduled Jobs 10:00/18:00 Lima, log en vivo con `EVENT`, cancelar) | `#ejecucion[/<job>]` | reanudar |
| D5 Despliegues y defectos | `#despliegues` | registrar (solo desktop) |
| D6 Indicadores (`scripts/indicadores.py`) | `#indicadores` | consultar |
| D7 Auditoría (matriz 2×2 y κ, decision_log, desviaciones, accesos) + paquete de evidencia R4 | `#auditoria` | auditoria / exportar |

**Roles (D-P2):** `CONSOLA_USUARIOS={"jrosado1974": ["operador", "registrador", "aprobador"]}`. El asesor recibe el ZIP de evidencia.

**Variables del Space:** `PILOT=piloto1`, `RUNS_REPO=jrosado1974/tesis-piloto`, `CONSOLA_BRANCH` (tag congelado), `CONSOLA_JOB_ENV`
(JSON con `ADAPTERS`, `NIVELES`, `WORKERS`). **Secrets:** `HF_TOKEN` (permisos finos: Jobs + `tesis-piloto`), `GITHUB_TOKEN`.

**R1:** cada acción (login, alta, aprobar, devolver, reanudar, cancelar, registrar, consultar, exportar, denegado) se agrega a
`piloto/piloto1/accesos.jsonl`; la app no tiene ninguna ruta que lo edite.

Local: `CONSOLA_SERVIR=1 CONSOLA_LOCAL=/ruta/copia_dataset CONSOLA_USUARIO_LOCAL=jrosado1974 uvicorn space.app.main:app` desde la raíz del repo.
