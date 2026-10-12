"""Frozen evaluation-universe manifest loader (see E3_EVALUATION_PROTOCOL.md)."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MANIFEST = Path("evaluation/frozen_universe.json")


def load_frozen_universe(path: str | Path = DEFAULT_MANIFEST) -> list[str]:
    """Return the frozen evaluation symbols from a manifest written by ``freeze-universe``.

    Raises ``ValueError`` when the manifest is missing symbols, so callers can
    distinguish "no frozen sample" from "empty sample" and fall back explicitly.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    symbols = data.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError(f"manifest {path} does not contain a non-empty 'symbols' list")
    return [str(symbol).upper() for symbol in symbols]
