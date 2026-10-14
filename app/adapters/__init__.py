"""Backend registry.

Adding a backend means writing one module next to this one and registering it
in ``_REGISTRY``.
"""

from __future__ import annotations

from .base import (
    Backend,
    BackendError,
    Canceled,
    GenerationRequest,
    GenerationResult,
    ProgressReporter,
)
from .demo import DemoBackend
from .local import LocalBackend
from .minimax_api import MiniMaxAPIBackend

_REGISTRY: dict[str, Backend] = {
    "demo": DemoBackend(),
    "local": LocalBackend(),
    "api": MiniMaxAPIBackend(),
}

ORDER = ("demo", "local", "api")


def get(name: str) -> Backend:
    backend = _REGISTRY.get((name or "").lower())
    if backend is None:
        raise BackendError(
            f"Unknown backend '{name}'. Available: {', '.join(ORDER)}"
        )
    return backend


def all_backends() -> list[Backend]:
    return [_REGISTRY[name] for name in ORDER]


__all__ = [
    "Backend",
    "BackendError",
    "GenerationRequest",
    "GenerationResult",
    "get",
    "all_backends",
    "ORDER",
]
