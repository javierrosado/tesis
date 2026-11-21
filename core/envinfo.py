"""Registro del entorno de ejecución (hardware y versiones de software) para reproducibilidad.
Cada job lo imprime al inicio y lo guarda junto a sus resultados (entorno.json)."""
import json, platform, subprocess, sys
from importlib import metadata

PAQUETES = ["vllm", "torch", "transformers", "peft", "trl", "bitsandbytes", "accelerate", "datasets", "xgrammar",
            "huggingface_hub", "jsonschema", "openapi-spec-validator", "fastapi", "pytest", "ruff", "bandit", "scipy"]


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        cuda = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=20).stdout
        ver = next((l.split("CUDA Version:")[1].split("|")[0].strip() for l in cuda.splitlines() if "CUDA Version" in l), None)
        return {"gpu": out, "cuda_driver": ver}
    except Exception as e:  # noqa: BLE001
        return {"gpu": None, "error": str(e)[:100]}


def report(extra=None):
    vers = {}
    for p in PAQUETES:
        try:
            vers[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            pass
    info = {"python": sys.version.split()[0], "platform": platform.platform(), **gpu(), "paquetes": vers, **(extra or {})}
    print("ENTORNO", json.dumps(info, ensure_ascii=False), flush=True)
    return info
