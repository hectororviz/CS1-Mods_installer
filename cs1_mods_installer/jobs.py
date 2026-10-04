"""Tareas en segundo plano con progreso.

Descargar e instalar un mod son varios segundos (HTML de la ficha, subida al
host, descarga de hasta 100 MB, extraccion). Para que la interfaz no se
congele, cada operacion larga se lanza como un ``Job`` y el frontend va
preguntando por el progreso con polling.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str  # install | remove | index | ...
    title: str = ""
    state: str = "pending"  # pending | running | done | error
    step: str = ""
    progress: float = 0.0  # 0..1
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
            "step": self.step,
            "progress": self.progress,
            "detail": self.detail,
            "error": self.error,
            "elapsed": round((self.finished_at or time.time()) - self.created_at, 1),
        }


class JobRegistry:
    def __init__(self, keep: int = 60) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._keep = keep

    def create(self, kind: str, title: str = "") -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self._keep:
                old = self._order.pop(0)
                self._jobs.pop(old, None)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, limit: int = 20) -> list[Job]:
        with self._lock:
            ids = self._order[-limit:][::-1]
            return [self._jobs[i] for i in ids if i in self._jobs]

    def active(self) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.state in ("pending", "running")]

    def run(self, job: Job, fn: Callable[[Job], None]) -> Job:
        """Ejecuta ``fn`` en un hilo y actualiza el estado de la job."""

        def target() -> None:
            job.state = "running"
            try:
                fn(job)
                job.state = "done"
                job.progress = 1.0
            except Exception as e:  # noqa: BLE001 - la UI muestra el error
                job.state = "error"
                job.error = f"{type(e).__name__}: {e}"
                job.detail.setdefault("traceback", traceback.format_exc()[-1500:])
            finally:
                job.finished_at = time.time()

        threading.Thread(target=target, name=f"cs1mods-{job.kind}", daemon=True).start()
        return job


REGISTRY = JobRegistry()
