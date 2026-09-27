"""Append-only audit log for the Tier 4 paper execution path.

The engine's in-memory ``orders`` list disappears when the process exits, which
means there is no record of what was ordered, when, at what price, or why a
breaker tripped. This writes one JSON object per line (JSONL) so the trail
survives a restart and can be reconstructed or diffed.

Design notes:
- Append-only; never rewritten or truncated by the library.
- Opt-in: the engine only writes when given an ``AuditLog``, so tests and
  library use never touch the filesystem by accident.
- Values are serialised with ``default=str`` so ``Timestamp``/``Decimal`` and
  similar types are recorded rather than raising.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    """Append execution events as JSONL to ``path``."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        """Append one event. Never raises on serialisation or write failure."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass  # auditing must never break execution


def read_audit(path: str | Path) -> list[dict[str, Any]]:
    """Read back all audit records. Malformed lines are skipped, not raised."""
    p = Path(path)
    if not p.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
