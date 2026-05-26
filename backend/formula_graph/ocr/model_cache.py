from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any, Hashable

_MODEL_CACHE: dict[tuple[Hashable, ...], Any] = {}
_MODEL_CACHE_LOCK = RLock()


def get_cached_model(key: tuple[Hashable, ...], factory: Callable[[], Any]) -> Any:
    """Return a process-local OCR/model engine shared by short-lived adapters."""
    with _MODEL_CACHE_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            model = factory()
            _MODEL_CACHE[key] = model
        return model


def clear_model_cache() -> None:
    """Clear cached engines; intended for tests and explicit maintenance hooks."""
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()
