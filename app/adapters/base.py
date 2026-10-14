"""Backend adapter interface.

Every backend turns a :class:`GenerationRequest` into an mp4 on disk. The
contract is deliberately small so a new backend (vLLM, ComfyUI, a remote
cluster) is a single file plus one entry in ``app/adapters/__init__.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

ProgressFn = Callable[[float, str], None]


class Canceled(RuntimeError):
    """Raised inside a backend when its job has been canceled."""


class ProgressReporter:
    """Wraps a progress callback and carries a cooperative cancel flag.

    Backends call :meth:`report` from their render loop; the loop raises
    :class:`Canceled` as soon as :meth:`cancel` has been called. This is what
    lets the UI's Delete button stop a render that is already in flight, since
    a thread cannot be interrupted from the outside.
    """

    def __init__(self, callback: ProgressFn | None = None) -> None:
        self._callback = callback
        self._canceled = False

    def cancel(self) -> None:
        self._canceled = True

    @property
    def canceled(self) -> bool:
        return self._canceled

    def report(self, value: float, stage: str) -> None:
        self.check()
        if self._callback is not None:
            self._callback(value, stage)

    def check(self) -> None:
        """Raise :class:`Canceled` if the job has been canceled."""
        if self._canceled:
            raise Canceled("canceled")

    __call__ = report


def check_canceled(progress: ProgressFn) -> None:
    """Raise :class:`Canceled` if ``progress`` is a canceled reporter.

    ``ProgressFn`` stays a plain callable, so backends accept a bare function
    in tests and a :class:`ProgressReporter` in production.
    """
    check = getattr(progress, "check", None)
    if check is not None:
        check()


@dataclass
class GenerationRequest:
    mode: str
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
    language: str = "English"
    conditions: list[dict] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    shots: list[dict] = field(default_factory=list)

    def target(self) -> dict:
        return {
            "short_edge": self.short_edge,
            "aspect_ratio": self.aspect_ratio,
            "duration_seconds": self.duration,
        }


@dataclass
class GenerationResult:
    video_path: str = ""
    audio_path: str = ""
    poster_path: str = ""
    remote_id: str = ""
    video_url: str = ""
    audio_url: str = ""
    poster_url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class BackendError(RuntimeError):
    """Raised when a backend cannot complete a request."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class Backend(Protocol):
    name: str
    label: str
    description: str

    def available(self) -> tuple[bool, str]:
        """Return ``(usable, reason)``. ``reason`` is shown in the UI."""

    def info(self) -> dict:
        """Serialisable description used by ``GET /api/backends``."""

    def generate(
        self, job_id: str, request: GenerationRequest, progress: ProgressFn
    ) -> GenerationResult:
        ...
