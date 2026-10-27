"""Telemetría JSONL. Mismo esquema de eventos que el piloto simulado (eventos_G2.jsonl) para que el
análisis estadístico (H1–H6) se ejecute sin cambios sobre corridas reales. Cada evento lleva provider y
model_id: así se filtra y demuestra qué proveedor produjo cada dato."""
import json, time, uuid
from datetime import datetime, timezone
from pathlib import Path


class Telemetry:
    def __init__(self, path: Path, run_id: str | None = None):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._t0 = time.time()

    def emit(self, **ev):
        ev.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        ev.setdefault("run_id", self.run_id)
        ev.setdefault("elapsed_s", round(time.time() - self._t0, 3))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def read(self):
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
