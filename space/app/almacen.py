"""Acceso al dataset del piloto (privado) desde la consola.

Dos implementaciones con la misma interfaz:
- AlmacenHub: dataset de HF (jrosado1974/tesis-piloto). Lectura por snapshot con caché corta; escritura en un solo commit.
- AlmacenLocal: carpeta con la misma estructura que el dataset. La usan las pruebas y el modo CONSOLA_LOCAL.

Rutas, iguales a las que usa el job (jobs/run_pipeline_job.py):
  piloto/<p>/requerimientos/<REQ>/input/*         entrada (inmutable desde entrada_pipeline)
  piloto/<p>/estado/<REQ>/output/*                artefactos, pendientes, aprobaciones, rechazos, *.input.r<n>.json
  piloto/<p>/registros/*.jsonl                    defectos escapados y post-despliegue
  piloto/<p>/ventanas/*.json                      actas de cada ventana de decisiones
  piloto/<p>/accesos.jsonl                        R1: registro de accesos (solo se agregan líneas)
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path


class AlmacenLocal:
    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self._lock = threading.Lock()

    def carpeta(self, prefijo: str) -> Path:
        return self.raiz / prefijo

    def leer(self, ruta: str) -> str | None:
        f = self.raiz / ruta
        return f.read_text(encoding="utf-8") if f.exists() else None

    def commit(self, ops: list[tuple[str, bytes]], mensaje: str) -> None:
        with self._lock:
            for ruta, contenido in ops:
                f = self.raiz / ruta
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(contenido)

    def agregar_linea(self, ruta: str, linea: str, mensaje: str) -> None:
        with self._lock:
            f = self.raiz / ruta
            f.parent.mkdir(parents=True, exist_ok=True)
            with f.open("a", encoding="utf-8") as fh:
                fh.write(linea.rstrip("\n") + "\n")

    def invalidar(self) -> None:
        pass


class AlmacenHub:
    """Dataset de HF. `carpeta()` devuelve una copia local reciente (TTL) del prefijo pedido."""

    def __init__(self, repo: str, ttl: float = 20.0):
        from huggingface_hub import HfApi
        self.repo, self.ttl, self.api = repo, ttl, HfApi()
        self._cache: dict[str, tuple[float, Path]] = {}
        self._lock = threading.Lock()

    def carpeta(self, prefijo: str) -> Path:
        from huggingface_hub import snapshot_download
        t, p = self._cache.get(prefijo, (0.0, None))
        if p is None or time.time() - t > self.ttl:
            raiz = Path(snapshot_download(self.repo, repo_type="dataset", allow_patterns=[f"{prefijo}/**"]))
            p = raiz / prefijo
            self._cache[prefijo] = (time.time(), p)
        return p

    def leer(self, ruta: str) -> str | None:
        from huggingface_hub import hf_hub_download
        try:
            return Path(hf_hub_download(self.repo, ruta, repo_type="dataset", force_download=True)).read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001 — archivo aún no creado
            return None

    def commit(self, ops: list[tuple[str, bytes]], mensaje: str) -> None:
        from huggingface_hub import CommitOperationAdd
        with self._lock:
            self.api.create_commit(self.repo, repo_type="dataset", commit_message=mensaje,
                                   operations=[CommitOperationAdd(r, b) for r, b in ops])
        self.invalidar()

    def agregar_linea(self, ruta: str, linea: str, mensaje: str) -> None:
        with self._lock:                     # leer + volver a subir en serie: el Hub no tiene append
            previo = self.leer(ruta) or ""
            self.api.upload_file(path_or_fileobj=(previo + linea.rstrip("\n") + "\n").encode(), repo_id=self.repo,
                                 repo_type="dataset", path_in_repo=ruta, commit_message=mensaje)

    def invalidar(self) -> None:
        self._cache.clear()


def desde_entorno() -> AlmacenLocal | AlmacenHub:
    if os.environ.get("CONSOLA_LOCAL"):
        return AlmacenLocal(Path(os.environ["CONSOLA_LOCAL"]))
    return AlmacenHub(os.environ.get("RUNS_REPO", "jrosado1974/tesis-piloto"))


def copiar_arbol(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
