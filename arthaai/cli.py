"""ArthaAI CLI — drive the pipeline end-to-end.

    arthaai health                 # check datastores
    arthaai seed-news              # load illustrative news into Qdrant
    arthaai ingest GLD             # pull OHLCV into TimescaleDB
    arthaai analyze GLD            # run the full multi-agent pipeline
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arthaai.config import get_settings

app = typer.Typer(add_completion=False, help="ArthaAI multi-agent market analysis.")
console = Console()

# Signals accepted by the diagnostic backtest/promotion commands. "composite" is
# the fixed-factor per-bar aggregate, "ic_composite" the walk-forward IC-weighted
# cross-sectional composite, and "tsmom"/"xsmom" the classic momentum family
# (ARTHA-219 / E3). All are analysis tooling and never become the live sizing
# signal without a human decision.
VALID_SIGNALS = (
    "trend", "breakout", "composite", "ic_composite", "tsmom", "xsmom",
    "regime", "regime_tsmom", "value", "macro", "macro_tsmom",
)


def _validate_signal(signal: str) -> str:
    """Normalize and reject unknown signals instead of silently defaulting to trend."""
    normalized = signal.strip().lower()
    if normalized not in VALID_SIGNALS:
        console.print(f"[red]--signal must be one of: {', '.join(VALID_SIGNALS)}[/]")
        raise typer.Exit(2)
    return normalized


def _expand_universe(symbols: list[str]) -> list[str]:
    """Requested symbols plus the frozen evaluation universe (deduped, upper-cased)."""
    from arthaai.eval.universe import load_frozen_universe

    universe = list(dict.fromkeys(s.upper() for s in symbols))
    try:
        frozen = load_frozen_universe()
    except (OSError, ValueError):
        frozen = []
    for sym in frozen:
        if sym not in universe:
            universe.append(sym)
    return universe


def _signal_map_for(
    signal: str,
    symbols: list[str],
    *,
    limit: int,
    lookback: int = 126,
    top_quantile: float = 0.30,
) -> dict | None:
    """Build per-symbol causal series for cross-sectional/panel signals, else None.

    Cross-sectional signals (``ic_composite``, ``xsmom``) see the frozen universe
    so a single-symbol run still has a real cross-section; ``tsmom`` is per-symbol.
    """
    if signal == "ic_composite":
        from arthaai.factors.composite import cross_sectional_signal_map

        return cross_sectional_signal_map(_expand_universe(symbols), limit=limit)
    if signal == "tsmom":
        from arthaai.factors.momentum import momentum_signal_map

        return momentum_signal_map(symbols, kind="tsmom", lookback=lookback, limit=limit)
    if signal == "xsmom":
        from arthaai.factors.momentum import momentum_signal_map

        return momentum_signal_map(
            _expand_universe(symbols),
            kind="xsmom",
            lookback=lookback,
            top_quantile=top_quantile,
            limit=limit,
        )
    if signal in ("regime", "regime_tsmom"):
        from arthaai.factors.regime import regime_signal_map

        return regime_signal_map(
            _expand_universe(symbols), kind=signal, lookback=lookback, limit=limit
        )
    if signal == "value":
        from arthaai.data.fundamentals_pit import value_signal_map

        return value_signal_map(
            _expand_universe(symbols), top_quantile=top_quantile, limit=limit
        )
    if signal in ("macro", "macro_tsmom"):
        from arthaai.factors.macro_regime import macro_signal_map

        return macro_signal_map(
            _expand_universe(symbols), kind=signal, lookback=lookback, limit=limit
        )
    return None


@app.command()
def health() -> None:
    """Verify TimescaleDB and Qdrant are reachable."""
    ok = True
    try:
        from arthaai.db import timescale

        console.print(f"  timescaledb  [green]OK[/]  (extension {timescale.ping()})")
    except Exception as exc:  # noqa: BLE001
        ok = False
        console.print(f"  timescaledb  [red]FAIL[/]  ({exc})")
    try:
        from qdrant_client import QdrantClient

        s = get_settings()
        QdrantClient(host=s.qdrant_host, port=s.qdrant_port).get_collections()
        console.print("  qdrant       [green]OK[/]")
    except Exception as exc:  # noqa: BLE001
        ok = False
        console.print(f"  qdrant       [red]FAIL[/]  ({exc})")
    raise typer.Exit(0 if ok else 1)


@app.command()
def migrate() -> None:
    """Apply the idempotent TimescaleDB schema (creates missing tables/columns).

    Needed for databases whose Docker volume predates a schema change — the
    container's init hook only runs on a fresh volume. Safe to run repeatedly.
    """
    from arthaai.db import migrate as migrate_mod
    from arthaai.db import timescale

    try:
        n = migrate_mod.apply_schema()
        deleted = timescale.repair_daily_duplicates()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Migration failed:[/] {exc}")
        console.print("[dim]Is the stack up? `docker compose up -d`[/]")
        raise typer.Exit(1)
    console.print(f"applied [bold]{n}[/] idempotent schema statements.")
    if deleted:
        console.print(f"repaired [bold]{deleted}[/] duplicate daily bar(s) (legacy dual-provider ingest).")


@app.command("seed-news")
def seed_news() -> None:
    """Load illustrative, source-attributed news into Qdrant."""
    from arthaai.data.seed_news import seed

    n = seed()
    console.print(f"seeded [bold]{n}[/] news documents into Qdrant.")


@app.command("ingest-news")
def ingest_news(
    symbol: str,
    feeds: str = typer.Option(
        "", help="Comma-separated RSS/Atom feed URLs (defaults to ARTHAAI_NEWS_FEEDS)."
    ),
    limit: int = typer.Option(10, help="Max items per feed."),
) -> None:
    """Pull live RSS/Atom headlines into Qdrant for a symbol (ARTHA-216)."""
    from arthaai.config import get_settings
    from arthaai.data.news_feed import ingest_news as run_ingest

    urls = [u.strip() for u in feeds.split(",") if u.strip()]
    if not urls:
        urls = [u.strip() for u in get_settings().news_feeds.split(",") if u.strip()]
    if not urls:
        console.print(
            "[red]No feed URLs supplied.[/] Pass --feeds or set ARTHAAI_NEWS_FEEDS."
        )
        raise typer.Exit(1)
    with console.status(f"[bold]ingesting {len(urls)} feed(s) for {symbol.upper()}…"):
        n = run_ingest(symbol, urls, limit_per_feed=limit)
    console.print(f"ingested [bold]{n}[/] news documents for {symbol.upper()} into Qdrant.")


@app.command()
def universe(
    action: str = typer.Argument("sync", help="sync | count | search"),
    query: str = typer.Argument("", help="text for search"),
) -> None:
    """Register every US-listed symbol (catalog only; prices load on demand)."""
    from arthaai.data import universe as uni

    if action == "sync":
        with console.status("[bold]fetching NASDAQ symbol directory…"):
            n = uni.sync()
        console.print(f"processed [bold]{n}[/] listed symbols · catalog now holds [bold]{uni.count()}[/] assets.")
    elif action == "count":
        console.print(f"catalog holds [bold]{uni.count()}[/] assets.")
    elif action == "search":
        rows = uni.search(query)
        t = Table(show_header=True, header_style="bold")
        t.add_column("Symbol"); t.add_column("Name"); t.add_column("Type")
        for r in rows:
            t.add_row(r["symbol"], r["name"], r["asset_class"])
        console.print(t)
    else:
        console.print("[red]action must be: sync | count | search[/]")
        raise typer.Exit(1)


@app.command()
def ingest(
    symbol: str,
    days: int = typer.Option(730, help="Lookback days (ignored if data already exists)."),
    timeframe: str = typer.Option("1d", help="Candle timeframe: 1d, 1h, 5m, 1m."),
    provider: str = typer.Option(
        "auto", help="Provider override; auto uses ARTHAAI_MARKET_DATA_PROVIDER (default: auto)."
    ),
) -> None:
    """Pull OHLCV for SYMBOL into TimescaleDB via the provider chain.

    With the default auto override, uses ARTHAAI_MARKET_DATA_PROVIDER. When
    that setting is auto, tries LSE first if configured, then yfinance. Use
    --provider to force a registered provider for this invocation.
    """
    from arthaai.data.provider import ingest_resilient

    with console.status(f"[bold]fetching {symbol.upper()} via {provider}…"):
        result = ingest_resilient(symbol, lookback_days=days, timeframe=timeframe, provider=provider)

    if result.rows == 0 and result.incremental:
        console.print(f"[dim]{symbol.upper()} is already up to date.[/]")
    elif result.rows == 0:
        console.print(f"[red]No data found for {symbol.upper()} via {result.provider}.[/]")
    else:
        color = "cyan" if result.provider == "lse" else "yellow"
        console.print(
            f"ingested [bold]{result.rows}[/] bars for [bold]{symbol.upper()}[/] "
            f"([{color}]{result.provider}[/]{' · incremental' if result.incremental else ''})."
        )


@app.command(name="ingest-lse")
def ingest_lse(
    symbol: str,
    days: int = typer.Option(730, help="Lookback days (ignored if data already exists)."),
    timeframe: str = typer.Option("1d", help="Candle timeframe: 1m, 5m, 1h, 1d."),
) -> None:
    """Pull OHLCV for SYMBOL via LSE only (alias for: ingest --provider lse)."""
    from arthaai.data.provider import ingest_resilient

    with console.status(f"[bold]fetching {symbol.upper()} from LSE…"):
        result = ingest_resilient(symbol, lookback_days=days, timeframe=timeframe, provider="lse")
    if result.rows == 0:
        console.print(f"[red]No data found for {symbol.upper()} on LSE.[/]")
    else:
        console.print(f"ingested [bold]{result.rows}[/] bars for [bold]{symbol.upper()}[/] ([cyan]lse[/]).")


@app.command("provider-status")
def provider_status(
    symbol: str,
    prefer: str = typer.Option(
        "", help="Pin a registered provider for this symbol, or use auto to clear the pin."
    ),
) -> None:
    """Show (or set) the stored data provider for SYMBOL."""
    from arthaai.data.provider import default_provider_registry
    from arthaai.db import timescale

    symbol = symbol.upper()
    prefer = prefer.strip().lower()

    if prefer:
        if prefer != "auto" and not default_provider_registry().has_provider(prefer):
            console.print(
                "[red]--prefer must be a registered provider name or 'auto'.[/]"
            )
            raise typer.Exit(1)
        try:
            timescale.set_preferred_provider(symbol, "" if prefer == "auto" else prefer)
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[red]Could not update preference:[/] {exc}\n[dim]Run `arthaai migrate` first.[/]"
            )
            raise typer.Exit(1)
        console.print(f"preferred provider for [bold]{symbol}[/] set to [cyan]{prefer}[/].")
        return

    try:
        status = timescale.get_provider_status(symbol)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]DB unreachable:[/] {exc}\n[dim]`docker compose up -d` then `arthaai migrate`.[/]")
        raise typer.Exit(1)

    if not status:
        console.print(f"[yellow]{symbol} is not in the asset catalog.[/]")
        raise typer.Exit(1)

    t = Table(title=f"Provider status · {symbol}", show_header=False)
    t.add_column("k"); t.add_column("v")
    t.add_row("configured default", get_settings().market_data_provider)
    t.add_row("preferred", status["preferred_provider"] or "[dim]auto (none pinned)[/]")
    t.add_row("last used", status["last_provider"] or "[dim]—[/]")
    t.add_row("last ingest", str(status["last_ingest_at"] or "—"))
    console.print(t)


@app.command()
def analyze(symbol: str, skip_ingest: bool = typer.Option(False, help="Use existing OHLCV.")) -> None:
    """Run the full multi-agent analysis pipeline for SYMBOL."""
    from arthaai.orchestration import analyze as run_analyze

    symbol = symbol.strip().strip(".").upper()  # tolerate stray dots/spaces
    with console.status(f"[bold]running multi-agent pipeline for {symbol}…"):
        state = run_analyze(symbol, skip_ingest=skip_ingest)

    db, quant = state.get("db", {}), state.get("quant", {})
    if not db.get("available"):
        console.print(
            f"[yellow]No market data for '{symbol}'.[/] "
            "Check the ticker (e.g. RDW not .RDW), or it may have no history on the data source."
        )
        raise typer.Exit(1)

    news, alt = state.get("news", {}), state.get("alt", {})
    verdict, alloc = state.get("verdict", {}), state.get("allocation", {})

    ev = Table(title=f"Agent evidence · {symbol}", show_header=True, header_style="bold")
    ev.add_column("Agent"); ev.add_column("Signal"); ev.add_column("Detail")
    if db.get("available"):
        sig = db.get("signal_class", "trend")
        ev.add_row("DB_Agent", db["trend"], f"close {db['last_close']} · RSI {db['rsi14'] and round(db['rsi14'],1)} · ADX {db.get('adx14','—')} ({db.get('regime','')}) · [{sig}] · {db['bars']} bars")
    if quant.get("available"):
        sig = quant.get("signal_class", "trend")
        ev.add_row("Quant", f"μ {quant['mu']:+.2%}", f"σ {quant['sigma']:.2%} · W {quant['win_prob']:.2f} · R {quant['win_loss_ratio']:.2f} · [{sig}]")
    if news.get("available"):
        ev.add_row("News_Agent", news["label"], f"{news['count']} items · sentiment {news['avg_sentiment']:+.2f}")
    if alt.get("available"):
        ev.add_row("Alt_Agent", f"{alt['physical_score']:+.2f}", f"[dim]{alt.get('note','')}[/]")
    console.print(ev)

    dirn = verdict.get("direction", "n/a")
    color = {"bullish": "green", "bearish": "red"}.get(dirn, "yellow")
    console.print(Panel(
        f"[{color} bold]{dirn.upper()}[/]  ·  confidence {verdict.get('confidence', 0):.0%}  "
        f"·  [dim]{verdict.get('source')}[/]\n\n{verdict.get('rationale','')}",
        title="Master Reasoning LLM", border_style=color,
    ))

    if alloc:
        cap = "  [yellow](capped by policy)[/]" if alloc.get("capped_by_policy") else ""
        console.print(Panel(
            f"discrete Kelly {alloc['discrete_kelly']:+.3f}  ·  continuous Kelly {alloc['continuous_kelly']:+.3f}\n"
            f"fractional (¼-Kelly) {alloc['fractional']:.3f}  →  "
            f"[bold]final allocation {alloc['final_fraction']:.2%}[/]{cap}\n\n[dim]{alloc['rationale']}[/]",
            title="Asset Manager · Kelly sizing", border_style="cyan",
        ))
    console.print("[dim]Decision-support only · paper context · not investment advice.[/]")


@app.command()
def execute(
    symbol: str,
    equity: float = typer.Option(100_000, help="Paper account equity."),
    skip_ingest: bool = typer.Option(False),
    audit: str = typer.Option("", help="Append the paper order to this JSONL audit log."),
    approval: str = typer.Option(
        "", help="Enable the human decision gate, persisting proposals to this JSONL path."
    ),
    proposal_id: str = typer.Option(
        "", help="Approved proposal id to execute (requires --approval)."
    ),
    ledger: str = typer.Option(
        "", help="Record the opened position to this ledger (enables `arthaai mark`)."
    ),
    force: bool = typer.Option(False, help="Override the portfolio exposure cap."),
) -> None:
    """Run the pipeline, then place a PAPER order through Tier 4 guardrails."""
    from arthaai.execution import ApprovalGate, ExecutionEngine, TradingHalted
    from arthaai.orchestration import analyze as run_analyze

    symbol = symbol.upper()
    with console.status(f"[bold]analysing {symbol}…"):
        state = run_analyze(symbol, skip_ingest=skip_ingest)
    verdict, alloc, db = state.get("verdict", {}), state.get("allocation", {}), state.get("db", {})
    direction = verdict.get("direction", "neutral")
    last_price = db.get("last_close", 0.0)

    if direction == "neutral" or alloc.get("final_fraction", 0) <= 0:
        console.print(f"[yellow]No paper order — verdict {direction}, allocation 0.[/]")
        raise typer.Exit(0)

    engine = ExecutionEngine(equity=equity, audit=audit or None)

    # --- Human decision gate (ARTHA-308) ------------------------------------
    # With --approval the order cannot be placed until a person approves the
    # proposal in a separate step; without a proposal id this run only records
    # the proposal and stops.
    if approval:
        gate = ApprovalGate(approval)
        if not proposal_id:
            side = "buy" if direction == "bullish" else "sell"
            fraction = float(alloc.get("final_fraction", 0.0))
            notional = round(engine.equity * fraction, 2)
            stop = round(
                last_price * (1 - engine.stop_loss_pct)
                if side == "buy"
                else last_price * (1 + engine.stop_loss_pct),
                4,
            )
            proposal = gate.propose(
                symbol=symbol, side=side, notional=notional, stop_loss=stop,
                final_fraction=fraction, rationale=alloc.get("rationale", ""),
            )
            console.print(Panel(
                f"[bold]pending approval[/] · proposal {proposal.id}\n"
                f"{side.upper()} {symbol} · ${notional:,.2f} · stop @ {stop}\n\n"
                f"[dim]approve: arthaai approve {approval} {proposal.id} --by <name>\n"
                f"reject:  arthaai reject {approval} {proposal.id} --by <name>[/]",
                title="Tier 3 · human decision gate", border_style="yellow",
            ))
            raise typer.Exit(0)

        # Bind execution to the approved proposal: same symbol, same side, and
        # the approved fraction — and the proposal is consumed exactly once.
        proposal = gate.get(proposal_id)
        if proposal is None:
            console.print(f"[red]No proposal {proposal_id} in {approval}.[/]")
            raise typer.Exit(1)
        if proposal.status != "approved":
            console.print(
                f"[red]Proposal {proposal_id} is {proposal.status}, not approved — "
                "no order placed.[/]"
            )
            raise typer.Exit(1)
        actual_side = "buy" if direction == "bullish" else "sell"
        if proposal.symbol != symbol or proposal.side != actual_side:
            console.print(
                f"[red]Proposal {proposal_id} is for {proposal.symbol} {proposal.side}, "
                f"not {symbol} {actual_side} — refusing; re-propose.[/]"
            )
            raise typer.Exit(1)
        alloc = dict(alloc)
        alloc["final_fraction"] = proposal.final_fraction

    # Portfolio-level exposure guard (ARTHA-309): cap total live exposure across
    # the ledger's open positions plus this new order.
    from arthaai.config import get_settings

    existing_notional = 0.0
    if ledger:
        from arthaai.execution import PositionLedger

        existing_notional = sum(
            p.quantity * p.entry_price for p in PositionLedger(ledger).open_positions()
        )
    new_notional = round(equity * float(alloc.get("final_fraction", 0.0)), 2)
    cap = get_settings().max_portfolio_exposure
    projected = (existing_notional + new_notional) / equity if equity else 0.0
    if projected > cap + 1e-9 and not force:
        console.print(Panel(
            f"projected portfolio exposure {projected:.1%} would exceed the cap of "
            f"{cap:.0%} (open ${existing_notional:,.0f} + new ${new_notional:,.0f} "
            f"on ${equity:,.0f}).\nRe-run with --force to override.",
            title="Tier 3 · portfolio exposure cap", border_style="red",
        ))
        raise typer.Exit(1)

    try:
        order = engine.submit(symbol, alloc, last_price, direction)
    except TradingHalted as exc:
        console.print(Panel(str(exc), title="Tier 4 · trading halted", border_style="red"))
        raise typer.Exit(1)

    if approval:
        gate.mark_executed(proposal_id)

    if ledger:
        from arthaai.execution import PositionLedger, PositionState

        pos = engine.portfolio.positions.get(symbol)
        if pos is not None and pos.state == PositionState.OPEN:
            PositionLedger(ledger).open(
                symbol=symbol, side=order.side, quantity=pos.quantity,
                entry_price=pos.entry_price, stop_price=pos.stop_price,
                target_price=pos.target_price,
            )
            console.print(f"[dim]position recorded to ledger {ledger} — monitor with "
                          f"`arthaai mark {ledger}`.[/]")

    risk_line = ""
    if alloc.get("var_95") is not None:
        risk_line = (
            f"\nrisk: 95% VaR {alloc['var_95'] * float(alloc.get('final_fraction', 0)):.2%} · "
            f"ES {alloc.get('expected_shortfall_95', 0) * float(alloc.get('final_fraction', 0)):.2%} "
            f"on exposure"
        )
    console.print(Panel(
        f"[bold]{order.side.upper()}[/] {order.symbol}  ·  notional ${order.notional:,.2f}  "
        f"({alloc['final_fraction']:.2%} of ${equity:,.0f})\n"
        f"stop-loss @ {order.stop_loss}  ·  drawdown breaker [{engine.breaker_state}]  ·  "
        f"[bold]PAPER[/]"
        + risk_line,
        title="Tier 4 · paper execution", border_style="magenta",
    ))
    if audit:
        console.print(f"[dim]audit log appended to {audit}[/]")
    console.print("[dim]Simulated order only — no broker contacted.[/]")


@app.command()
def approve(
    path: str,
    proposal_id: str,
    by: str = typer.Option(..., "--by", help="Approver identity."),
) -> None:
    """Approve a pending human decision gate proposal."""
    from arthaai.execution import ApprovalGate

    gate = ApprovalGate(path)
    try:
        proposal = gate.decide(proposal_id, approved=True, by=by)
    except KeyError:
        pending = ", ".join(p.id for p in gate.pending()) or "none"
        console.print(f"[red]No proposal {proposal_id} in {path}.[/] Pending: {pending}")
        raise typer.Exit(1)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(
        f"[green]approved[/] {proposal.id} · {proposal.symbol} {proposal.side} "
        f"${proposal.notional:,.2f} by {by}"
    )


@app.command()
def reject(
    path: str,
    proposal_id: str,
    by: str = typer.Option(..., "--by", help="Approver identity."),
    reason: str = typer.Option("", help="Rejection reason (recorded in the audit trail)."),
) -> None:
    """Reject a pending human decision gate proposal."""
    from arthaai.execution import ApprovalGate

    gate = ApprovalGate(path)
    try:
        proposal = gate.decide(proposal_id, approved=False, by=by, reason=reason)
    except KeyError:
        pending = ", ".join(p.id for p in gate.pending()) or "none"
        console.print(f"[red]No proposal {proposal_id} in {path}.[/] Pending: {pending}")
        raise typer.Exit(1)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    console.print(
        f"[yellow]rejected[/] {proposal.id} · {proposal.symbol} {proposal.side} by {by}"
        + (f" · {reason}" if reason else "")
    )


@app.command()
def mark(
    ledger: str = typer.Argument(..., help="Position ledger written by `execute --ledger`."),
    price: str = typer.Option(
        "", help="Optional SYMBOL=PRICE[,SYMBOL=PRICE] overrides (else the latest DB bar)."
    ),
    limit: int = typer.Option(1, help="Bars per symbol for the stop check."),
) -> None:
    """Step open ledger positions against the latest bar and fire stop/target.

    This is where stop-losses are enforced in the live paper path: `execute`
    records the position, `mark` evaluates it and closes it when the stop or
    target is breached (ARTHA-4xx).
    """
    import pandas as pd

    from arthaai.db import timescale
    from arthaai.execution.ledger import PositionLedger, evaluate_exit, unrealized_pnl

    overrides: dict[str, float] = {}
    for part in price.split(","):
        if "=" in part:
            sym, val = part.split("=", 1)
            overrides[sym.strip().upper()] = float(val)

    led = PositionLedger(ledger)
    positions = led.open_positions()
    if not positions:
        console.print("[dim]No open positions in the ledger.[/]")
        return

    t = Table(title="Position mark")
    for col in ("Symbol", "Entry", "Stop", "Last", "uPnL", "Action"):
        t.add_column(col, justify="right" if col not in ("Symbol", "Action") else "left")
    for p in positions:
        if p.symbol in overrides:
            px = overrides[p.symbol]
            bar = pd.Series({"ts": pd.Timestamp.now(tz="UTC"), "open": px,
                             "high": px, "low": px, "close": px})
            last = px
        else:
            df = timescale.load_ohlcv(p.symbol, limit=limit)
            if df.empty:
                t.add_row(p.symbol, f"{p.entry_price:.2f}", f"{p.stop_price or 0:.2f}",
                          "—", "—", "[yellow]no data[/]")
                continue
            bar = df.iloc[-1]
            last = float(bar["close"])

        fill = evaluate_exit(p, bar)
        pnl = f"{unrealized_pnl(p, last):+,.2f}"
        if fill is not None:
            led.close(p.id, exit_price=fill.price, reason=fill.reason)
            action = f"[red]{fill.reason.upper()}[/]"
        else:
            action = "[green]held[/]"
        t.add_row(p.symbol, f"{p.entry_price:.2f}", f"{p.stop_price or 0:.2f}",
                  f"{last:.2f}", pnl, action)
    console.print(t)


@app.command("paper-sim")
def paper_sim(
    symbol: str,
    warmup: int = 60,
    limit: int = 500,
    signal: str = typer.Option("trend", help="trend | breakout"),
    adx: float = typer.Option(0.0, help="ADX gate for breakout (e.g. 25)."),
    equity: float = typer.Option(100_000, help="Starting paper equity."),
    fraction: float = typer.Option(0.05, help="Allocation fraction per entry (policy cap)."),
    stop_loss: float = typer.Option(0.08, help="Mandatory stop-loss fraction."),
    slippage_bps: float = typer.Option(0.0, help="Adverse fill slippage in basis points."),
    participation: float = typer.Option(
        0.0, help="Max fill as a fraction of bar volume (0 = unlimited)."
    ),
    reject_probability: float = typer.Option(
        0.0, help="Per-order rejection probability in [0, 1]."
    ),
    fill_seed: int = typer.Option(0, help="RNG seed for reproducible rejections (0 = unseeded)."),
    audit: str = typer.Option("", help="Append execution events to this JSONL audit log."),
) -> None:
    """Bar-by-bar paper simulation that actually fires stop-loss/targets (Tier 4)."""
    from arthaai.db import timescale
    from arthaai.execution import ExecutionEngine, FillModel
    from arthaai.execution.simulate import simulate_symbol

    symbol = symbol.upper()
    df = timescale.load_ohlcv(symbol, limit=limit)
    if len(df) < warmup + 5:
        console.print(f"[red]Not enough data for {symbol}: {len(df)} bars (need > {warmup + 5}).[/]")
        raise typer.Exit(1)

    fill_model = FillModel(
        slippage_bps=slippage_bps,
        participation_rate=participation or None,
        reject_probability=reject_probability,
        seed=fill_seed or None,
    )
    engine = ExecutionEngine(
        initial_equity=equity, stop_loss_pct=stop_loss, audit=audit or None, fill_model=fill_model
    )
    with console.status(f"[bold]simulating {symbol} ({signal}) bar-by-bar…"):
        res = simulate_symbol(
            symbol, df, warmup=warmup, signal=signal, adx_threshold=adx,
            allocation_fraction=fraction, equity=equity, stop_loss_pct=stop_loss, engine=engine,
        )

    t = Table(title=f"Paper simulation · {symbol} · {signal}", show_header=False)
    t.add_column("k"); t.add_column("v", justify="right")
    t.add_row("bars", str(res.bars))
    t.add_row("entries", str(res.entries))
    t.add_row("partial fills", str(res.partial_fills))
    t.add_row("rejected orders", str(res.rejected_orders))
    t.add_row("stop-loss hits", str(res.stops_hit))
    t.add_row("target hits", str(res.targets_hit))
    t.add_row("other exits", str(res.exits))
    t.add_row("realised P&L", f"${res.realised_pnl:,.2f}")
    t.add_row("final equity", f"${res.final_equity:,.2f}")
    t.add_row("max drawdown", f"{res.max_drawdown:.2%}")
    console.print(t)
    if audit:
        console.print(f"[dim]audit log appended to {audit}[/]")
    console.print("[dim]Simulated orders only — no broker contacted.[/]")


def _promote_windows(
    symbol: str, *, signal: str, warmup: int, limit: int,
    adx_threshold: float, cost_bps: float, vol_target: float, windows: int,
    signal_map: dict | None = None,
):
    """Evaluate the promotion gate across non-overlapping OOS windows.

    ``signal_map`` supplies precomputed per-symbol causal signal series for
    cross-sectional signals (``ic_composite``); when set, it overrides the
    per-symbol ``signal``/``adx_threshold``. Returns ``(qualified, note, rows,
    evals)`` or ``None`` when there is not enough history. Shared by `promote`
    and `promote-sweep`.
    """
    from arthaai.backtest import oos_windows, run_backtest
    from arthaai.backtest.promotion import combine_windows, evaluate_promotion
    from arthaai.db import timescale
    from arthaai.factors.panel import align_signal_to_ohlcv

    df = timescale.load_ohlcv(symbol, limit=limit)
    if len(df) < warmup + 10:
        return None
    series = None
    if signal_map is not None:
        column = signal_map.get(symbol)
        if column is None:
            return None
        series = align_signal_to_ohlcv(column, symbol, limit=limit)
    wins = oos_windows(len(df), oos_pct=0.30, count=windows, min_bars=warmup + 10)
    if not wins:
        return None
    rows, evals = [], []
    for lo, hi in wins:
        res = run_backtest(
            symbol, warmup=warmup, limit=limit, signal=signal,
            adx_threshold=adx_threshold, data_slice=slice(lo, hi),
            cost_bps=cost_bps, vol_target=vol_target, signal_series=series,
        )
        ev = evaluate_promotion(
            oos_sharpe=res.sharpe, oos_max_drawdown=res.max_drawdown,
            oos_total_return=res.total_return, buy_hold_return=res.buy_hold_return,
            oos_long_only_return=res.long_only_return,
        )
        rows.append((lo, hi, res, ev))
        evals.append(ev)
    qualified, note = combine_windows(evals)
    return qualified, note, rows, evals


@app.command()
def promote(
    symbol: str,
    signal: str = typer.Option("trend", help="trend | breakout | composite | ic_composite | tsmom | xsmom"),
    warmup: int = 60,
    limit: int = 500,
    adx: float = typer.Option(0.0, help="ADX gate for breakout (e.g. 25)."),
    cost_bps: float = typer.Option(0.0, help="Round-trip friction (bps) charged on turnover."),
    vol_target: float = typer.Option(0.0, help="Annualised volatility target (0 = off)."),
    windows: int = typer.Option(2, help="Non-overlapping OOS windows; ALL must pass."),
    lookback: int = typer.Option(126, help="Trailing-return lookback (bars) for tsmom/xsmom."),
    top_quantile: float = typer.Option(0.30, help="Long top fraction of the universe for xsmom."),
    dry_run: bool = typer.Option(False, help="Show results without saving to DB."),
    save: bool = typer.Option(True, help="Save promotion result to DB."),
) -> None:
    """Run an OOS promotion evaluation for SYMBOL across independent windows.

    Promotion requires EVERY window to pass ALL criteria:
    1. Sharpe (annualised) >= 1.0
    2. Max drawdown <= 20%
    3. Beats buy-and-hold, exposure-matched (100% long/flat return > B&H)

    The B&H test is exposure-matched: comparing the Kelly-sized return (~1-5%
    exposure) to a 100%-invested benchmark is unwinnable by construction.
    """
    from arthaai.backtest.promotion import MAX_DD, MIN_SHARPE
    from arthaai.db import timescale

    symbol = symbol.upper()
    signal = _validate_signal(signal)
    adx_threshold = adx if signal == "breakout" else 0.0

    signal_map = _signal_map_for(
        signal, [symbol], limit=limit, lookback=lookback, top_quantile=top_quantile
    )

    with console.status(f"[bold]promoting {symbol} · {signal}…"):
        try:
            result = _promote_windows(
                symbol, signal=signal, warmup=warmup, limit=limit,
                adx_threshold=adx_threshold, cost_bps=cost_bps,
                vol_target=vol_target, windows=windows, signal_map=signal_map,
            )
        except ValueError as exc:
            console.print(f"[red]Promotion failed:[/] {exc}")
            raise typer.Exit(1) from exc
    if result is None:
        console.print(
            f"[red]Not enough data / OOS windows for {symbol} "
            f"(need > {warmup + 10} bars).[/]"
        )
        raise typer.Exit(1)
    qualified, note, rows, evals = result

    t = Table(title=f"Promotion · {symbol} · {signal}", show_header=True, header_style="bold")
    t.add_column("Window", justify="right"); t.add_column("Sharpe", justify="right")
    t.add_column("MaxDD", justify="right"); t.add_column("Long-only", justify="right")
    t.add_column("B&H", justify="right"); t.add_column("Pass", justify="center")
    for lo, hi, res, ev in rows:
        t.add_row(
            f"{lo}–{hi}", f"{res.sharpe:.2f}", f"{res.max_drawdown:.1%}",
            f"{res.long_only_return:+.2%}", f"{res.buy_hold_return:+.2%}",
            "✅" if ev.qualified else "❌",
        )
    console.print(t)

    lo, hi, res, ev = rows[-1]  # most recent window (persisted metrics)
    border = "green" if qualified else "red"
    verdict_str = "[bold green]QUALIFIED[/] — promoted" if qualified else "[bold red]REJECTED[/]"
    failures = "; ".join(f"window {l}–{h}: {e.reason}" for l, h, _, e in rows if not e.qualified)
    console.print(Panel(
        f"{verdict_str}  ({note})\n"
        f"thresholds: Sharpe ≥ {MIN_SHARPE:.1f} · MaxDD ≤ {MAX_DD:.0%} · long-only > B&H\n"
        f"most recent window {lo}–{hi}: long-only {res.long_only_return:+.2%} vs "
        f"B&H {res.buy_hold_return:+.2%} · Sharpe {res.sharpe:.2f} · "
        f"MaxDD {res.max_drawdown:.1%} · trades {res.trades} · hit {res.hit_rate:.0%}\n"
        f"costs: {cost_bps:g} bps · vol target: {vol_target or 'off'}\n\n"
        f"[dim]{failures or 'all windows passed'}[/]",
        title="Promotion result", border_style=border,
    ))

    if save and not dry_run:
        try:
            timescale.upsert_signal_promotion(
                symbol=symbol,
                signal=signal,
                qualified=qualified,
                sharpe=res.sharpe,
                max_drawdown=res.max_drawdown,
                oos_return=res.total_return,
                buy_hold_return=res.buy_hold_return,
            )
            console.print(
                f"[dim]Saved promotion record to DB (symbol={symbol}, signal={signal}, "
                f"qualified={qualified}).[/]"
            )
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[yellow]Could not save to DB: {exc}[/]\n"
                "[dim]Run `arthaai migrate` to apply the schema "
                "(and `docker compose up -d` if the stack is down).[/]"
            )


@app.command("promote-sweep")
def promote_sweep(
    symbols: str = typer.Option(
        "GLD,SLV,USO,XOM,AAPL,DBC,TSLA", help="Comma-separated universe to sweep."
    ),
    signal: str = typer.Option("trend", help="trend | breakout | composite | ic_composite | tsmom | xsmom"),
    warmup: int = 60,
    limit: int = 520,
    adx: float = typer.Option(25.0, help="ADX gate for breakout."),
    cost_bps: float = typer.Option(10.0, help="Round-trip friction (bps) charged on turnover."),
    vol_target: float = typer.Option(0.0, help="Annualised volatility target (0 = off)."),
    windows: int = typer.Option(2, help="Non-overlapping OOS windows; ALL must pass."),
    lookback: int = typer.Option(126, help="Trailing-return lookback (bars) for tsmom/xsmom."),
    top_quantile: float = typer.Option(0.30, help="Long top fraction of the universe for xsmom."),
    save: bool = typer.Option(True, help="Persist each result to the DB."),
) -> None:
    """Sweep the promotion gate across a universe and list every qualified symbol."""
    from arthaai.db import timescale

    signal = _validate_signal(signal)
    adx_threshold = adx if signal == "breakout" else 0.0
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    signal_map = None
    if signal in ("ic_composite", "tsmom", "xsmom"):
        with console.status(f"[bold]computing {signal} signal over {len(syms)} symbols…"):
            signal_map = _signal_map_for(
                signal, syms, limit=limit, lookback=lookback, top_quantile=top_quantile
            )

    t = Table(title=f"Promotion sweep · {signal} · {len(syms)} symbols")
    for col in ("Symbol", "Windows", "Sharpe", "Long-only", "B&H", "Verdict"):
        t.add_column(col, justify="right" if col not in ("Symbol", "Verdict") else "left")

    qualified_symbols: list[str] = []
    for sym in syms:
        try:
            with console.status(f"[bold]promoting {sym}…"):
                result = _promote_windows(
                    sym, signal=signal, warmup=warmup, limit=limit,
                    adx_threshold=adx_threshold, cost_bps=cost_bps,
                    vol_target=vol_target, windows=windows, signal_map=signal_map,
                )
        except ValueError as exc:
            t.add_row(sym, "—", "—", "—", "—", f"[yellow]{str(exc)[:48]}[/]")
            continue
        if result is None:
            t.add_row(sym, "—", "—", "—", "—", "[yellow]no data[/]")
            continue
        qualified, _note, rows, evals = result
        passes = sum(1 for e in evals if e.qualified)
        res = rows[-1][2]
        if qualified:
            qualified_symbols.append(sym)
        t.add_row(
            sym, f"{passes}/{len(evals)}", f"{res.sharpe:.2f}",
            f"{res.long_only_return:+.2%}", f"{res.buy_hold_return:+.2%}",
            "[green]QUALIFIED[/]" if qualified else "[red]REJECTED[/]",
        )
        if save:
            try:
                timescale.upsert_signal_promotion(
                    symbol=sym, signal=signal, qualified=qualified, sharpe=res.sharpe,
                    max_drawdown=res.max_drawdown, oos_return=res.total_return,
                    buy_hold_return=res.buy_hold_return,
                )
            except Exception:  # noqa: BLE001 - DB may be down; the sweep still reports
                pass

    console.print(t)
    console.print(
        f"[bold]{len(qualified_symbols)}[/] qualified: {qualified_symbols or 'none'}"
    )


@app.command()
def backtest(
    symbol: str,
    warmup: int = 60,
    limit: int = 500,
    signal: str = typer.Option(
        "trend",
        help="trend (SMA-cross) | breakout (Donchian 55/20) | composite (fixed-factor mean) "
        "| ic_composite (IC-weighted cross-sectional) | tsmom | xsmom (classic momentum)",
    ),
    adx: float = typer.Option(0.0, help="ADX regime gate for breakout (e.g. 25 = only enter when trending)"),
    cost_bps: float = typer.Option(0.0, help="Round-trip friction (bps) charged on turnover."),
    vol_target: float = typer.Option(0.0, help="Annualised volatility target for sizing (0 = off)."),
    lookback: int = typer.Option(126, help="Trailing-return lookback (bars) for tsmom/xsmom."),
    top_quantile: float = typer.Option(0.30, help="Long top fraction of the universe for xsmom."),
) -> None:
    """Walk-forward backtest with look-ahead guards (offline evaluation)."""
    from arthaai.backtest import run_backtest

    signal = _validate_signal(signal)
    signal_series = None
    if signal in ("ic_composite", "tsmom", "xsmom"):
        from arthaai.factors.panel import align_signal_to_ohlcv

        with console.status(f"[bold]computing {signal} signal…"):
            signal_map = _signal_map_for(
                signal, [symbol], limit=limit, lookback=lookback, top_quantile=top_quantile
            )
        column = signal_map.get(symbol.upper())
        if column is None:
            console.print(f"[red]{signal} unavailable for {symbol.upper()}[/]")
            raise typer.Exit(1)
        signal_series = align_signal_to_ohlcv(column, symbol.upper(), limit=limit)
    try:
        with console.status(f"[bold]backtesting {symbol.upper()}…"):
            res = run_backtest(
                symbol, warmup=warmup, limit=limit, signal=signal,
                adx_threshold=adx, cost_bps=cost_bps, vol_target=vol_target,
                signal_series=signal_series,
            )
    except ValueError as exc:
        console.print(f"[red]Backtest failed:[/] {exc}")
        raise typer.Exit(1) from exc
    t = Table(title=f"Backtest · {res.symbol} · {signal}" + (f" · ADX≥{adx:g}" if adx else ""), show_header=False)
    t.add_column("k"); t.add_column("v", justify="right")
    t.add_row("bars / trades", f"{res.bars} / {res.trades}")
    t.add_row("strategy return (Kelly)", f"{res.total_return:+.2%}")
    t.add_row("long/short (100%)", f"{res.long_short_return:+.2%}")
    t.add_row("long-only (100%)", f"{res.long_only_return:+.2%}")
    t.add_row("buy & hold", f"{res.buy_hold_return:+.2%}")
    edge = res.long_short_return - res.buy_hold_return
    col = "green" if edge > 0 else "red"
    t.add_row("edge vs B&H", f"[{col}]{edge:+.2%}[/]")
    t.add_row("Sharpe (ann.)", f"{res.sharpe:.2f}")
    t.add_row("max drawdown", f"{res.max_drawdown:.2%}")
    t.add_row("hit rate", f"{res.hit_rate:.1%}")
    if cost_bps:
        t.add_row("cost model", f"{cost_bps:g} bps on turnover")
    console.print(t)
    console.print("[dim]Look-ahead-bias guarded: signal at day t only sees bars ≤ t.[/]")


@app.command()
def consume(max_messages: int = 10) -> None:
    """Consume ingestion events from the Kafka/Redpanda bus (needs `kafka` extra)."""
    from arthaai.data.consumer import consume as run_consume

    n = run_consume(max_messages=max_messages)
    console.print(f"consumed [bold]{n}[/] ingest events.")


@app.command()
def compare(
    symbols: str = typer.Option("GLD,SLV,USO,XOM,AAPL", help="Comma-separated symbols to compare."),
    limit: int = 500,
    adx: float = typer.Option(25.0, help="ADX gate for breakout (0 = no gate)."),
) -> None:
    """Compare trend vs breakout signals across multiple assets."""
    from arthaai.backtest import run_backtest

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    t = Table(title="Signal comparison · trend vs breakout", show_header=True, header_style="bold")
    t.add_column("Symbol")
    t.add_column("Signal")
    t.add_column("Strat Ret", justify="right")
    t.add_column("L/S (100%)", justify="right")
    t.add_column("L/O (100%)", justify="right")
    t.add_column("B&H", justify="right")
    t.add_column("Sharpe", justify="right")
    t.add_column("MaxDD", justify="right")
    t.add_column("Hit%", justify="right")

    for sym in sym_list:
        for sig in ("trend", "breakout"):
            try:
                res = run_backtest(sym, limit=limit, signal=sig, adx_threshold=adx if sig == "breakout" else 0.0)
            except Exception as exc:  # noqa: BLE001
                t.add_row(sym, sig, "[red]error[/]", str(exc)[:40], "", "", "", "", "")
                continue
            edge = res.long_short_return - res.buy_hold_return
            edge_col = "green" if edge > 0 else "red"
            t.add_row(
                sym if sig == "trend" else "",
                sig,
                f"{res.total_return:+.2%}",
                f"[{edge_col}]{res.long_short_return:+.2%}[/]",
                f"{res.long_only_return:+.2%}",
                f"{res.buy_hold_return:+.2%}",
                f"{res.sharpe:.2f}",
                f"{res.max_drawdown:.2%}",
                f"{res.hit_rate:.0%}",
            )
    console.print(t)
    console.print("[dim]L/S = long/short 100% exposure · L/O = long-only 100% · Strat = Kelly-sized · ADX gate for breakout only.[/]")


@app.command("research-global")
def research_global(
    symbols: str = typer.Option(..., help="Comma-separated ingested stocks, ETFs, and index proxies."),
    limit: int = typer.Option(1000, help="Maximum stored bars per symbol."),
    factor_ids: str = typer.Option("", help="Optional comma-separated factor IDs; default is the fixed research set."),
    horizon: int = typer.Option(1, min=1, help="Forward-return horizon in bars for historical IC."),
    min_ic_obs: int = typer.Option(20, min=2, help="Prior IC observations before weights are used."),
    embargo: int = typer.Option(1, min=1, help="Bars embargoed between IC observations and use."),
    top_quantile: float = typer.Option(0.20, min=0.01, max=1.0, help="Portfolio fraction selected by score."),
    cost_bps: float = typer.Option(10.0, min=0.0, help="Turnover friction in basis points."),
    windows: int = typer.Option(2, min=1, help="Number of sequential held-out windows."),
    oos_pct: float = typer.Option(0.20, min=0.01, max=0.5, help="Fraction of history in each OOS window."),
) -> None:
    """Run a diagnostic cross-sectional factor study; never promotes a signal."""
    from arthaai.factors.panel import build_panel_from_symbols
    from arthaai.research.cross_sectional import run_factor_research

    symbol_list = [value.strip().upper() for value in symbols.split(",") if value.strip()]
    if len(set(symbol_list)) < 3:
        console.print("[red]Provide at least three distinct symbols.[/]")
        raise typer.Exit(2)
    panel = build_panel_from_symbols(list(dict.fromkeys(symbol_list)), limit=limit)
    if not panel or "close" not in panel:
        console.print("[red]No OHLCV data found; ingest the requested symbols first.[/]")
        raise typer.Exit(1)

    selected_factors = [value.strip() for value in factor_ids.split(",") if value.strip()] or None
    try:
        report = run_factor_research(
            panel,
            factor_ids=selected_factors,
            horizon=horizon,
            min_ic_obs=min_ic_obs,
            embargo=embargo,
            top_quantile=top_quantile,
            cost_bps=cost_bps,
            windows=windows,
            oos_pct=oos_pct,
        )
    except ValueError as exc:
        console.print(f"[red]Research evaluation unavailable:[/] {exc}")
        raise typer.Exit(1) from exc

    table = Table(title="Global factor research · diagnostic only", show_header=True)
    for column in (
        "Window", "Assets", "Active", "Strategy", "Benchmark", "Excess",
        "Sharpe", "MaxDD", "Strategy TO", "Benchmark TO",
    ):
        table.add_column(column, justify="right" if column != "Window" else "left")
    for result in report.windows:
        table.add_row(
            f"{result.start[:10]}–{result.end[:10]}",
            str(result.complete_assets),
            f"{result.active_fraction:.0%}",
            f"{result.total_return:+.2%}",
            f"{result.benchmark_return:+.2%}",
            f"{result.excess_return:+.2%}",
            f"{result.sharpe:.2f}",
            f"{result.max_drawdown:.2%}",
            f"{result.average_turnover:.2f}",
            f"{result.benchmark_average_turnover:.2f}",
        )
    console.print(table)
    if report.skipped_windows:
        console.print("[yellow]Skipped:[/] " + "; ".join(report.skipped_windows))
    console.print(
        f"[dim]Universe: {len(symbol_list)} requested · factors: "
        f"{', '.join(report.factor_ids) or 'default set'} · costs: {cost_bps:g} bps. "
        "One-session gaps carry the last close; longer gaps exclude an asset. "
        "Scores at t earn returns at t+1. "
        "This report does not qualify or promote signals and does not change E3.[/]"
    )


@app.command("refresh-history")
def refresh_history_command(
    symbol: str,
    lookback_days: int = typer.Option(180, min=1, help="Bounded overlapping history window to repair."),
    timeframe: str = typer.Option("1d", help="Bar interval (1d, 1h, 5m, or 1m)."),
    provider: str = typer.Option(
        "auto", help="Provider override; auto uses ARTHAAI_MARKET_DATA_PROVIDER."
    ),
) -> None:
    """Explicitly re-fetch and upsert recent bars to repair stored gaps."""
    from arthaai.data.provider import refresh_history

    try:
        result = refresh_history(
            symbol, lookback_days=lookback_days, timeframe=timeframe, provider=provider
        )
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]History refresh failed:[/] {exc}")
        raise typer.Exit(2) from exc
    console.print(
        f"refreshed [bold]{result.rows}[/] bars for {result.symbol} via "
        f"{result.provider} (overlap={lookback_days} days, interval={timeframe})."
    )
    console.print("[dim]Existing bars are upserted; ordinary incremental ingest is unchanged.[/]")


@app.command("refresh-universe")
def refresh_universe_command(
    symbols: str = typer.Option(..., help="Comma-separated symbols to refresh sequentially."),
    lookback_days: int = typer.Option(180, min=1, help="Bounded overlapping history window."),
    timeframe: str = typer.Option("1d", help="Bar interval (1d, 1h, 5m, or 1m)."),
    provider: str = typer.Option(
        "auto", help="Provider override; auto uses ARTHAAI_MARKET_DATA_PROVIDER."
    ),
) -> None:
    """Explicitly repair recent history for each symbol in a supplied universe."""
    from arthaai.data.provider import refresh_history_batch

    symbol_list = [value.strip() for value in symbols.split(",")]
    try:
        results = refresh_history_batch(
            symbol_list,
            lookback_days=lookback_days,
            timeframe=timeframe,
            provider=provider,
        )
    except ValueError as exc:
        console.print(f"[red]Universe refresh rejected:[/] {exc}")
        raise typer.Exit(2) from exc

    table = Table(title=f"History refresh · {len(results)} symbols", show_header=True)
    for column in ("Symbol", "Provider", "Bars upserted", "Status"):
        table.add_column(column, justify="right" if column == "Bars upserted" else "left")
    for result in results:
        success = result.provider != "error"
        table.add_row(
            result.symbol,
            result.provider,
            str(result.rows),
            "[green]ok[/]" if success else "[red]failed[/]",
        )
    console.print(table)
    console.print(
        f"[dim]Overlap: {lookback_days} days · interval: {timeframe} · provider: {provider}. "
        "Bars are upserted; no rows are deleted.[/]"
    )
    if any(result.provider == "error" for result in results):
        raise typer.Exit(1)


@app.command("audit-history")
def audit_history_command(
    symbols: str = typer.Option(..., help="Comma-separated symbols with stored daily bars."),
    calendar: str = typer.Option("XNYS", help="Default exchange_calendars name, e.g. XNYS or XLON."),
    calendar_map: str = typer.Option(
        "", help="Optional per-symbol overrides, e.g. VOD.L=XLON,7203.T=XTKS."
    ),
    limit: int = typer.Option(1000, min=1, help="Maximum bars loaded per symbol."),
    max_stale_sessions: int = typer.Option(1, min=0, help="Staleness sessions allowed before status is stale."),
) -> None:
    """Audit OHLCV completeness against exchange sessions; this command is read-only."""
    from arthaai.db import timescale
    from arthaai.research.data_quality import audit_history

    symbol_list = list(dict.fromkeys(
        value.strip().upper() for value in symbols.split(",") if value.strip()
    ))
    if not symbol_list:
        console.print("[red]Provide at least one symbol.[/]")
        raise typer.Exit(2)
    calendars = {}
    try:
        for entry in calendar_map.split(","):
            if not entry.strip():
                continue
            symbol, separator, calendar_name = entry.partition("=")
            if not separator or not symbol.strip() or not calendar_name.strip():
                raise ValueError(f"invalid calendar mapping: {entry}")
            calendars[symbol.strip().upper()] = calendar_name.strip().upper()
        data_map = {
            symbol: timescale.load_ohlcv(symbol, interval="1d", limit=limit)
            for symbol in symbol_list
        }
        reports = audit_history(
            data_map,
            calendar_by_symbol=calendars,
            default_calendar=calendar.upper(),
            max_stale_sessions=max_stale_sessions,
        )
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]History audit failed:[/] {exc}")
        raise typer.Exit(2) from exc

    table = Table(title="Stored OHLCV data quality", show_header=True)
    for column in ("Symbol", "Calendar", "Bars", "Coverage", "Missing", "Stale", "Duplicates", "Invalid", "Status"):
        table.add_column(column, justify="right" if column not in ("Symbol", "Calendar", "Status") else "left")
    for report in reports:
        table.add_row(
            report.symbol,
            report.calendar,
            str(report.bars),
            f"{report.coverage_ratio:.1%}",
            str(len(report.missing_sessions)),
            str(report.stale_sessions),
            str(len(report.duplicate_sessions)),
            str(report.invalid_rows),
            report.status,
        )
    console.print(table)
    for report in reports:
        if report.missing_sessions:
            console.print(
                f"[dim]{report.symbol} missing sessions: "
                f"{', '.join(report.missing_sessions[:10])}"
                f"{'…' if len(report.missing_sessions) > 10 else ''}[/]"
            )
    if any(report.status != "ready" for report in reports):
        raise typer.Exit(1)


@app.command("backfill-metadata")
def backfill_metadata(
    symbols: str = typer.Option(
        "", help="Comma-separated symbols; default = every asset missing exchange."
    ),
    all_assets: bool = typer.Option(
        False, "--all", help="Refresh metadata for every registered asset."
    ),
) -> None:
    """Populate exchange/asset-class metadata for registered assets via yfinance."""
    from arthaai.data.metadata import fetch_asset_metadata
    from arthaai.db import timescale

    requested = [value.strip().upper() for value in symbols.split(",") if value.strip()]
    if requested:
        targets = list(dict.fromkeys(requested))
    elif all_assets:
        targets = timescale.list_asset_symbols()
    else:
        targets = timescale.assets_missing_exchange()

    if not targets:
        console.print("[green]No assets need metadata backfill.[/]")
        return

    table = Table(title=f"Metadata backfill · {len(targets)} assets", show_header=True)
    for column in ("Symbol", "Exchange", "Class", "Name"):
        table.add_column(column, justify="left")
    updated = 0
    for sym in targets:
        try:
            meta = fetch_asset_metadata(sym)
            timescale.update_asset_metadata(
                sym,
                name=meta["name"],
                asset_class=meta["asset_class"],
                exchange=meta["exchange"],
                currency=meta["currency"],
            )
            updated += 1
            table.add_row(
                sym, meta["exchange"] or "—", meta["asset_class"], str(meta["name"])[:32]
            )
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the batch
            table.add_row(sym, "[red]error[/]", "—", str(exc)[:32])
    console.print(table)
    console.print(f"[dim]Updated {updated}/{len(targets)} assets from yfinance metadata.[/]")


@app.command("freeze-universe")
def freeze_universe(
    min_bars: int = typer.Option(480, help="Minimum daily bars to include a symbol."),
    out: str = typer.Option(
        "evaluation/frozen_universe.json", help="Manifest output path."
    ),
) -> None:
    """Freeze the evaluation universe to a reproducible manifest under a declared rule.

    Selection rule (declared up front, applied uniformly): a registered symbol is
    included when it has at least ``min_bars`` daily bars and a known exchange.
    The content hash covers only the sorted symbol list, so re-running on unchanged
    data reproduces the same hash.
    """
    import hashlib
    import json
    from collections import Counter
    from datetime import UTC, datetime
    from pathlib import Path

    from arthaai.db import timescale

    coverage = timescale.asset_coverage("1d")
    selected = [row for row in coverage if row["bars"] >= min_bars and row["exchange"]]
    selected.sort(key=lambda row: row["symbol"])
    symbols = [row["symbol"] for row in selected]
    bar_counts = {row["symbol"]: int(row["bars"]) for row in selected}
    # The hash covers the symbol list AND each symbol's bar count, so extending
    # history (a different sample) produces a new hash and voids prior verdicts.
    fingerprint = "\n".join(f"{sym}:{bar_counts[sym]}" for sym in symbols)
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]

    manifest = {
        "rule": {
            "min_daily_bars": min_bars,
            "require_exchange": True,
            "source": "registered assets in TimescaleDB (interval=1d)",
        },
        "count": len(symbols),
        "total_bars": sum(bar_counts.values()),
        "by_asset_class": dict(sorted(Counter(r["asset_class"] for r in selected).items())),
        "by_exchange": dict(sorted(Counter(r["exchange"] for r in selected).items())),
        "bar_counts": bar_counts,
        "symbols": symbols,
        "sample_sha256_16": digest,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    console.print(
        f"[green]Froze {len(symbols)} symbols[/] (min {min_bars} bars) → {path} "
        f"· hash {digest}"
    )
    console.print(
        f"[dim]exchanges: {manifest['by_exchange']} · classes: {manifest['by_asset_class']}[/]"
    )


@app.command("export-script")
def export_script(
    symbol: str,
    signal: str = typer.Option("trend", help="trend | breakout | tsmom"),
    platform: str = typer.Option("pine", help="pine | mql5 | tdx"),
    out: str = typer.Option("", help="Write to this file instead of stdout."),
    fast: int = typer.Option(20, help="Fast SMA window (trend)."),
    slow: int = typer.Option(50, help="Slow SMA window (trend)."),
    long_filter: int = typer.Option(200, help="Long-term SMA filter (trend)."),
    entry_window: int = typer.Option(20, help="Donchian entry window (breakout)."),
    exit_window: int = typer.Option(10, help="Donchian exit window (breakout)."),
    adx: float = typer.Option(25.0, help="ADX gate (breakout)."),
    lookback: int = typer.Option(126, help="Trailing-return lookback (tsmom)."),
) -> None:
    """Export a signal definition as a Pine/MQL5/TDX script (ARTHA-412).

    Output convenience only: it renders the same signal logic in a charting
    platform's syntax. It implies no edge and contacts no broker.
    """
    from arthaai.export import SignalSpec, render

    spec = SignalSpec(
        symbol=symbol.strip().upper(),
        kind=signal.strip().lower(),
        fast=fast,
        slow=slow,
        long_filter=long_filter,
        entry_window=entry_window,
        exit_window=exit_window,
        adx_threshold=adx,
        lookback=lookback,
    )
    try:
        text = render(spec, platform)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc

    if out:
        from pathlib import Path

        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        console.print(
            f"[green]Wrote {platform} script[/] for {spec.symbol} · {spec.kind} → {path}"
        )
    else:
        console.print(text)


@app.command("seed-secrets")
def seed_secrets(gateway_token: str = "dev-token") -> None:
    """Write dev secrets (gateway token, ANTHROPIC_API_KEY if set) into Vault."""
    import os

    from arthaai.security import vault

    payload = {"gateway_token": gateway_token}
    for env, secret in (
        ("ANTHROPIC_API_KEY", "anthropic_api_key"),
        ("GEMINI_API_KEY", "gemini_api_key"),
        ("ARTHAAI_LOCAL_API_KEY", "local_api_key"),
    ):
        if os.environ.get(env):
            payload[secret] = os.environ[env]
    vault.put_secret("arthaai", payload)
    console.print(f"stored [bold]{', '.join(payload)}[/] in Vault at secret/arthaai.")


@app.command("llm-status")
def llm_status() -> None:
    """Probe the configured LLM chain and show which providers are reachable."""
    from arthaai.agents.master_llm import provider_status

    rows = provider_status()
    t = Table(title="LLM provider chain", show_header=True, header_style="bold")
    t.add_column("#"); t.add_column("Provider"); t.add_column("Status"); t.add_column("Detail")
    active = None
    for i, r in enumerate(rows, 1):
        mark = "[green]● up[/]" if r["ok"] else "[red]○ down[/]"
        if r["ok"] and active is None:
            active = r["provider"]
        t.add_row(str(i), r["provider"], mark, r["detail"])
    console.print(t)
    console.print(f"[bold]→ analyze will use:[/] [green]{active or 'offline'}[/]  (first reachable in the chain)")


@app.command()
def serve(port: int = 8000) -> None:
    """Run the Tier 1 FastAPI gateway (UI at http://localhost:PORT/)."""
    import uvicorn

    uvicorn.run("arthaai.gateway.app:app", host="0.0.0.0", port=port)


@app.command()
def eval(
    provider: str = typer.Option(None, help="Force a single provider (offline|anthropic|gemini|local). Default: configured chain."),
) -> None:
    """Run golden-fixture eval against the Master Reasoning LLM."""
    from arthaai.eval.harness import run_eval

    with console.status("[bold]running golden-fixture eval…"):
        report = run_eval(provider=provider)

    t = Table(title="LLM Eval · golden fixtures", show_header=True, header_style="bold")
    t.add_column("Fixture"); t.add_column("Expected"); t.add_column("Actual"); t.add_column("Conf"); t.add_column("Band"); t.add_column("Source"); t.add_column("Rationale"); t.add_column("Pass")
    for r in report.results:
        ok = r.direction_correct and r.rationale_ok and r.confidence_band_ok
        t.add_row(
            r.name, r.expected, r.actual, f"{r.confidence:.0%}",
            "[green]ok[/]" if r.confidence_band_ok else "[red]x[/]",
            r.source,
            "[green]yes[/]" if r.rationale_ok else "[red]no[/]",
            "[green]PASS[/]" if ok else "[red]FAIL[/]",
        )
    console.print(t)

    calib = report.calibration_score
    calib_str = f"[bold]{calib:+.2f}[/]  (1=perfect, 0=random, -1=anti)" if calib is not None else "[dim]n/a (no variance — all verdicts same correctness)[/]"

    console.print(Panel(
        f"direction accuracy:     [bold]{report.direction_accuracy:.0%}[/]\n"
        f"rationale rate:         [bold]{report.rationale_rate:.0%}[/]\n"
        f"confidence band match:  [bold]{report.confidence_band_accuracy:.0%}[/]\n"
        f"calibration score:      {calib_str}\n"
        f"avg confidence:         [bold]{report.avg_confidence:.0%}[/]\n"
        f"sources used:           {', '.join(f'{k} ({v})' for k, v in report.sources_used.items())}\n"
        f"overall:                {'[green bold]PASS[/]' if report.passed else '[red bold]FAIL[/]'}",
        title="Eval scorecard", border_style="cyan" if report.passed else "red",
    ))

    if not report.passed:
        raise typer.Exit(1)


@app.command()
def portfolio(
    symbols: str = typer.Option(..., help="Comma-separated symbols for the universe."),
    limit: int = typer.Option(500, help="Bars per symbol."),
) -> None:
    """Covariance-aware portfolio Kelly allocation across a universe (ARTHA-309)."""
    import pandas as pd

    from arthaai.agents import asset_manager, quant_agent, risk
    from arthaai.db import timescale

    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    quant_map: dict[str, dict] = {}
    closes: dict[str, pd.Series] = {}
    with console.status(f"[bold]sizing {len(syms)} assets…"):
        for sym in syms:
            stats = quant_agent.run(sym)
            if not stats.get("available"):
                continue
            df = timescale.load_ohlcv(sym, limit=limit)
            if df.empty:
                continue
            quant_map[sym] = stats
            closes[sym] = df.set_index("ts")["close"].pct_change(fill_method=None)
    if not quant_map:
        console.print("[red]No quant stats available — run ingest first.[/]")
        raise typer.Exit(1)

    returns = pd.DataFrame(closes).dropna(how="all")
    alloc = asset_manager.portfolio_size(quant_map, returns)
    t = Table(title="Portfolio Kelly · covariance-aware allocation")
    t.add_column("Symbol")
    t.add_column("Standalone", justify="right")
    t.add_column("Final", justify="right")
    for sym, fraction in alloc.fractions.items():
        t.add_row(sym, f"{alloc.standalone_fractions[sym]:.2%}", f"{fraction:.2%}")
    console.print(t)

    # Historical tail risk of the sized book (ARTHA-310).
    held = [s for s in alloc.fractions if s in returns.columns]
    if held:
        weights = pd.Series({s: alloc.fractions[s] for s in held})
        book = (returns[held] * weights).sum(axis=1)
        var95 = risk.historical_var(book, 0.95)
        es95 = risk.historical_expected_shortfall(book, 0.95)
        console.print(
            f"[dim]book tail risk: daily 95% VaR {var95:.2%} · ES {es95:.2%} "
            f"({len(book)} obs)[/]"
        )
    console.print(f"[dim]{alloc.rationale}[/]")
    console.print("[dim]Decision-support only · paper context · not investment advice.[/]")


@app.command(name="factors")
def factors(
    action: str = typer.Argument("list", help="list | show | bench | composite"),
    alpha_id: str = typer.Option("", help="Alpha ID for 'show' (e.g. alpha101_001)"),
    zoo: str = typer.Option("", help="Filter by zoo: alpha101, gtja191, qlib158"),
    top: int = typer.Option(20, help="Top-K results for bench"),
    symbols: str = typer.Option("GLD,SLV,XOM", help="Symbols for bench (comma-separated)"),
    horizon: int = typer.Option(1, help="Forward-return horizon / IC embargo step for bench"),
    ic_weighted: bool = typer.Option(
        False, "--ic-weighted", help="Use the IC-weighted composite for 'composite'."
    ),
) -> None:
    """Alpha Zoo factor engine — list, show, or IC-bench factors (BH FDR)."""
    from arthaai.factors.registry import get_default_registry

    reg = get_default_registry()

    if action == "list":
        zoo_filter = zoo or None
        ids = reg.list(zoo=zoo_filter)
        console.print(f"[bold]{len(ids)}[/] alphas registered" + (f" (zoo={zoo})" if zoo else ""))
        # Group by zoo
        by_zoo: dict[str, list[str]] = {}
        for aid in ids:
            z = reg.get(aid).zoo
            by_zoo.setdefault(z, []).append(aid)
        for z, zids in sorted(by_zoo.items()):
            console.print(f"\n  [cyan]{z}[/] ({len(zids)} alphas)")
            for aid in zids[:5]:
                meta = reg.get(aid).meta
                themes = ", ".join(meta.get("theme", []))
                console.print(f"    {aid:25} [{themes}]")
            if len(zids) > 5:
                console.print(f"    [dim]... and {len(zids) - 5} more[/]")

    elif action == "show":
        if not alpha_id:
            console.print("[red]Usage: factors show --alpha-id alpha101_001[/]")
            raise typer.Exit(1)
        try:
            alpha = reg.get(alpha_id)
        except KeyError:
            console.print(f"[red]Alpha '{alpha_id}' not found[/]")
            raise typer.Exit(1)
        meta = alpha.meta
        console.print(Panel(
            f"id:              {alpha.id}\n"
            f"zoo:              {alpha.zoo}\n"
            f"theme:            {', '.join(meta.get('theme', []))}\n"
            f"formula:          {meta.get('formula_latex', '?')}\n"
            f"columns required: {meta.get('columns_required', [])}\n"
            f"universe:         {', '.join(meta.get('universe', []))}\n"
            f"warmup bars:      {meta.get('min_warmup_bars', '?')}\n"
            f"notes:            {meta.get('notes', '')}",
            title=f"Alpha: {alpha.id}",
        ))

    elif action == "bench":
        from arthaai.factors.eval import evaluate_factors
        from arthaai.factors.panel import build_panel_from_symbols, compute_forward_returns

        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        with console.status(f"[bold]building panel for {sym_list}…"):
            panel = build_panel_from_symbols(sym_list, limit=1000)
        if not panel:
            console.print("[red]No data — run `arthaai ingest` first[/]")
            raise typer.Exit(1)

        fwd_ret = compute_forward_returns(panel, horizon=horizon)
        zoo_filter = zoo or None
        alpha_ids = reg.list(zoo=zoo_filter)

        with console.status(f"[bold]computing {len(alpha_ids)} factors…"):
            factor_map = {}
            for aid in alpha_ids:
                try:
                    factor_map[aid] = reg.compute(aid, panel)
                except Exception:
                    continue

        console.print(
            f"Evaluating {len(factor_map)} factors over {len(sym_list)} assets "
            f"(horizon={horizon}, BH FDR α=0.05)…"
        )
        results = evaluate_factors(factor_map, fwd_ret, alpha=0.05, min_count=20, horizon=horizon)

        t = Table(title=f"Factor bench · {zoo or 'all zoos'} · top {top} by |IC|")
        t.add_column("ID"); t.add_column("IC Mean", justify="right"); t.add_column("IR", justify="right")
        t.add_column("t-stat", justify="right"); t.add_column("N", justify="right")
        t.add_column("Signif", justify="center"); t.add_column("Category"); t.add_column("Themes")

        for r in results[:top]:
            color = "green" if r.category == "alive" else "red" if r.category == "reversed" else "dim"
            themes = ", ".join(reg.get(r.alpha_id).meta.get("theme", []))
            t.add_row(
                r.alpha_id,
                f"{r.ic_mean:+.4f}",
                f"{r.ir:+.4f}",
                f"{r.t_stat:.2f}",
                str(r.ic_count),
                "[green]yes[/]" if r.significant else "[dim]no[/]",
                f"[{color}]{r.category}[/]",
                themes,
            )
        console.print(t)
        n_sig = sum(1 for r in results if r.significant)
        console.print(
            f"\n[dim]{len(results)} evaluated · [bold]{n_sig}[/] survive BH FDR · "
            f"{sum(1 for r in results if r.category == 'alive')} alive · "
            f"{sum(1 for r in results if r.category == 'reversed')} reversed · "
            f"{sum(1 for r in results if r.category == 'dead')} dead[/]"
        )

    elif action == "composite":
        from arthaai.factors.composite import (
            composite_from_panel,
            ic_weighted_composite,
            rank_assets,
        )
        from arthaai.factors.panel import build_panel_from_symbols

        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        panel = build_panel_from_symbols(syms)
        if not panel:
            console.print("[red]No OHLCV for the requested symbols — run ingest first.[/]")
            raise typer.Exit(1)
        if ic_weighted:
            comp = ic_weighted_composite(panel, horizon=horizon)
        else:
            comp = composite_from_panel(panel)
        if comp.empty:
            console.print("[yellow]No factors could be computed for this universe.[/]")
            raise typer.Exit(1)
        ranked = rank_assets(comp)
        t = Table(title=f"Cross-sectional factor composite · {len(syms)} symbols")
        t.add_column("Rank", justify="right")
        t.add_column("Symbol")
        t.add_column("Composite", justify="right")
        for i, (sym, score) in enumerate(ranked.items(), start=1):
            t.add_row(str(i), str(sym), f"{score:+.3f}")
        console.print(t)

    else:
        console.print("[red]Usage: factors list | show | bench | composite[/]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
