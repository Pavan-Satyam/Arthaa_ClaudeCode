"""Tiny on-disk cache helpers shared by exogenous data adapters.

Adapters cache downloaded snapshots under a repo-relative ``.cache/<source>``
directory (the existing convention in ``macro_series`` and ``fundamentals_pit``).
These helpers keep the read-only-CWD and staleness handling in one place so the
cache paths do not drift.
"""

from __future__ import annotations

import time
from pathlib import Path


def ensure_dir(path: Path) -> bool:
    """Create ``path`` if needed; return False (never raise) if it is not writable."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def is_fresh(path: Path, *, max_age_days: float) -> bool:
    """True when ``path`` exists and its mtime is within ``max_age_days``."""
    try:
        return (time.time() - path.stat().st_mtime) / 86400.0 <= max_age_days
    except OSError:
        return False
