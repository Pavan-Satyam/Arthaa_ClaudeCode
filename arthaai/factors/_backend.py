"""Graceful bottleneck import with env-var override.

Bottleneck provides C-compiled moving-window operators (move_argmax,
move_argmin) that are 100-350x faster than pandas rolling().apply().

When bottleneck is unavailable or disabled via env var, the operators
fall back to the pandas path — identical results, slower speed.
"""

from __future__ import annotations

from typing import Any

from numpy.lib.stride_tricks import sliding_window_view

__all__ = ["HAS_BOTTLENECK", "bn", "sliding_window_view"]

_bn_initialised: bool = False
_has_bottleneck: bool = False
_bn_module: Any = None


def _ensure_bottleneck() -> None:
    global _bn_initialised, _has_bottleneck, _bn_module
    if _bn_initialised:
        return
    _bn_initialised = True
    import os

    if os.environ.get("ARTHAAI_DISABLE_BOTTLENECK"):
        return
    try:
        import bottleneck as _bn

        _bn_module = _bn
        _has_bottleneck = True
    except ImportError:
        pass


def __getattr__(name: str) -> Any:
    if name == "HAS_BOTTLENECK":
        _ensure_bottleneck()
        return _has_bottleneck
    if name == "bn":
        _ensure_bottleneck()
        return _bn_module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
