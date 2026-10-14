"""Thread safe job store.

Jobs are kept in memory and mirrored to ``data/jobs.json`` so the gallery
survives a restart. Writes are atomic (temp file + rename) and serialised by a
single lock; the app has one process, so that is sufficient.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import config

TERMINAL_STATES = ("completed", "failed", "canceled")


@dataclass
class Job:
    id: str
    mode: str
    backend: str
    task: str
    prompt: str
    raw_prompt: str = ""
    negative_prompt: str = ""
    duration: float = 8.0
    aspect_ratio: str = "16:9"
    short_edge: int = 768
    seed: int = 0
    resolution: str = "768p"
    steps: int = 0
    status: str = "queued"
    progress: float = 0.0
    stage: str = "queued"
    error: str = ""
    remote_id: str = ""
    video_url: str = ""
    video_path: str = ""
    audio_url: str = ""
    audio_path: str = ""
    poster_url: str = ""
    conditions: list[dict] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or config.JOBS_FILE)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text() or "{}")
        except Exception:
            return
        for raw in payload.get("jobs", []):
            try:
                job = Job(**{k: v for k, v in raw.items() if k in Job.__dataclass_fields__})
            except Exception:
                continue
            if job.status not in TERMINAL_STATES:
                # a restart cannot resume an in-flight backend call
                job.status = "failed"
                job.error = job.error or "Interrupted by a server restart."
                job.stage = "failed"
            self._jobs[job.id] = job

    def _save_locked(self) -> None:
        config.ensure_dirs()
        payload = {"jobs": [j.to_dict() for j in self._jobs.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        os.replace(tmp, self.path)

    # -- api --------------------------------------------------------------
    def create(self, **kwargs: Any) -> Job:
        job = Job(id=uuid.uuid4().hex[:16], **kwargs)
        with self._lock:
            self._jobs[job.id] = job
            self._save_locked()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def update(self, job_id: str, **fields: Any) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                if key in Job.__dataclass_fields__:
                    setattr(job, key, value)
            job.updated_at = time.time()
            self._save_locked()
            return job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return False
            self._save_locked()
        for path in (job.video_path, job.audio_path, job.poster_url):
            if path and str(path).startswith(str(config.DATA_DIR)):
                Path(path).unlink(missing_ok=True)
        return True


store = JobStore()
