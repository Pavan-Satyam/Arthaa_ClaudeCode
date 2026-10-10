"""Persistent open-position ledger for the live paper path (ARTHA-4xx).

`arthaai execute` places a single paper order with an attached stop-loss, but
there is no long-running loop and no broker, so the stop was never evaluated —
stops only fired in the backtest / `paper-sim` loop. This ledger persists opened
positions across CLI invocations, and `arthaai mark` steps each open position
against the latest bar so the stop/target actually fires in the live path.

Stop/target evaluation reuses the canonical `Position.step` state machine, so the
live path and the simulation cannot diverge.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from arthaai.execution.audit import AuditLog, read_audit
from arthaai.execution.state import Fill, Position


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OpenPosition:
    id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    stop_price: float | None = None
    target_price: float | None = None
    opened_at: str = ""
    status: str = "open"            # open | closed
    closed_at: str | None = None
    exit_price: float | None = None
    reason: str = ""


class PositionLedger:
    """Append-only, restart-safe ledger of open/closed paper positions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._log = AuditLog(self.path)
        self._cache: dict[str, OpenPosition] | None = None

    def open(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        stop_price: float | None = None,
        target_price: float | None = None,
        ts: str | None = None,
    ) -> OpenPosition:
        position = OpenPosition(
            id=uuid.uuid4().hex[:12],
            symbol=symbol.upper(),
            side=side,
            quantity=float(quantity),
            entry_price=float(entry_price),
            stop_price=None if stop_price is None else float(stop_price),
            target_price=None if target_price is None else float(target_price),
            opened_at=ts or _now(),
        )
        self._log.write("open", **asdict(position))
        self._cache = None
        return position

    def load(self) -> dict[str, OpenPosition]:
        """Replay the log into the current position set (cached per instance)."""
        if self._cache is not None:
            return self._cache
        positions: dict[str, OpenPosition] = {}
        for rec in read_audit(self.path):
            event = rec.get("event")
            if event == "open":
                p = OpenPosition(
                    id=str(rec.get("id", "")),
                    symbol=str(rec.get("symbol", "")),
                    side=str(rec.get("side", "")),
                    quantity=float(rec.get("quantity", 0.0)),
                    entry_price=float(rec.get("entry_price", 0.0)),
                    stop_price=rec.get("stop_price"),
                    target_price=rec.get("target_price"),
                    opened_at=str(rec.get("opened_at", "")),
                )
                positions[p.id] = p
            elif event == "close":
                p = positions.get(str(rec.get("id", "")))
                if p is not None:
                    p.status = "closed"
                    p.closed_at = rec.get("closed_at")
                    p.exit_price = rec.get("exit_price")
                    p.reason = str(rec.get("reason", ""))
        self._cache = positions
        return positions

    def open_positions(self) -> list[OpenPosition]:
        return [p for p in self.load().values() if p.status == "open"]

    def get(self, position_id: str) -> OpenPosition | None:
        return self.load().get(position_id)

    def close(
        self, position_id: str, *, exit_price: float, reason: str, ts: str | None = None
    ) -> OpenPosition:
        positions = self.load()
        p = positions.get(position_id)
        if p is None:
            raise KeyError(position_id)
        if p.status != "open":
            raise ValueError(f"position {position_id} already {p.status}")
        p.status = "closed"
        p.exit_price = float(exit_price)
        p.reason = reason
        p.closed_at = ts or _now()
        self._log.write(
            "close", id=position_id, exit_price=p.exit_price, reason=reason, closed_at=p.closed_at
        )
        self._cache = None
        return p


def evaluate_exit(position: OpenPosition, bar) -> Fill | None:
    """Run one bar through the canonical state machine; return an exit Fill or None.

    Reuses `Position.step` so live stop/target logic matches the simulation.
    """
    pos = Position(symbol=position.symbol)
    pos.open(
        Fill(
            ts=bar["ts"],
            symbol=position.symbol,
            side=position.side,
            quantity=position.quantity,
            price=position.entry_price,
        ),
        stop_price=position.stop_price,
        target_price=position.target_price,
    )
    return pos.step(bar)


def unrealized_pnl(position: OpenPosition, price: float) -> float:
    sign = 1.0 if position.side == "buy" else -1.0
    return sign * (price - position.entry_price) * position.quantity