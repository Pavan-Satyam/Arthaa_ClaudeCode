"""Idempotent schema migrations for TimescaleDB.

Why this exists
---------------
``schema.sql`` is mounted into the TimescaleDB container at
``docker-entrypoint-initdb.d``, which Postgres executes **only on first init of
an empty data volume**. Any schema change made after that volume exists never
runs, so a long-lived dev/prod database silently drifts from ``schema.sql`` —
which is exactly how the ``signal_promotion`` table and the provider-tracking
columns were lost (the volume predated them).

Every statement in ``schema.sql`` is written to be idempotent (``IF NOT
EXISTS`` / ``ON CONFLICT DO NOTHING`` / ``ADD COLUMN IF NOT EXISTS``), so the
migration mechanism is simply "re-apply the whole file". ``arthaai migrate``
does that. It is safe to run repeatedly and safe to run against a fresh volume.
"""

from __future__ import annotations

from pathlib import Path

from arthaai.db import timescale

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    A semicolon only terminates a statement when it is real SQL — not when it
    sits inside a single-quoted string, a ``--`` line comment, a ``/* ... */``
    block comment, or a ``$tag$ ... $tag$`` dollar-quoted body. Comments are
    stripped from the returned statements, which are otherwise left verbatim.
    """
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_single = False
    dollar_tag: str | None = None

    while i < n:
        ch = sql[i]

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                buf.append(ch)
                i += 1
            continue

        if in_single:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":  # doubled quote = escaped '
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue

        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
        elif ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":  # line comment
                i += 1
        elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
        elif ch == "$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                dollar_tag = sql[i : j + 1]
                buf.append(dollar_tag)
                i = j + 1
            else:
                buf.append(ch)
                i += 1
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def schema_statements() -> list[str]:
    """Return the ordered, idempotent statements defined in ``schema.sql``."""
    return split_statements(_SCHEMA_PATH.read_text(encoding="utf-8"))


def apply_schema() -> int:
    """Apply ``schema.sql`` to the configured TimescaleDB.

    Returns the number of statements executed. Raises on any SQL error so the
    caller can surface it; because every statement is idempotent, re-running
    after a partial failure is safe.
    """
    statements = schema_statements()
    with timescale.connection() as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
    return len(statements)
