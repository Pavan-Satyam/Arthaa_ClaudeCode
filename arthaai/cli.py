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


@app.command("seed-news")
def seed_news() -> None:
    """Load illustrative, source-attributed news into Qdrant."""
    from arthaai.data.seed_news import seed

    n = seed()
    console.print(f"seeded [bold]{n}[/] news documents into Qdrant.")


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
def ingest(symbol: str, days: int = 730) -> None:
    """Pull OHLCV for SYMBOL into TimescaleDB."""
    from arthaai.data import ingest as ingest_mod

    n = ingest_mod.ingest(symbol, lookback_days=days)
    console.print(f"ingested [bold]{n}[/] bars for [bold]{symbol.upper()}[/].")


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
        ev.add_row("DB_Agent", db["trend"], f"close {db['last_close']} · RSI {db['rsi14'] and round(db['rsi14'],1)} · ADX {db.get('adx14','—')} ({db.get('regime','')}) · {db['bars']} bars")
    if quant.get("available"):
        ev.add_row("Quant", f"μ {quant['mu']:+.2%}", f"σ {quant['sigma']:.2%} · W {quant['win_prob']:.2f} · R {quant['win_loss_ratio']:.2f}")
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
) -> None:
    """Run the pipeline, then place a PAPER order through Tier 4 guardrails."""
    from arthaai.execution import ExecutionEngine, TradingHalted
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

    engine = ExecutionEngine(equity=equity)
    try:
        order = engine.submit(symbol, alloc, last_price, direction)
    except TradingHalted as exc:
        console.print(Panel(str(exc), title="Tier 4 · trading halted", border_style="red"))
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]{order.side.upper()}[/] {order.symbol}  ·  notional ${order.notional:,.2f}  "
        f"({alloc['final_fraction']:.2%} of ${equity:,.0f})\n"
        f"stop-loss @ {order.stop_loss}  ·  drawdown breaker [{engine.breaker_state}]  ·  "
        f"[bold]PAPER[/]",
        title="Tier 4 · paper execution", border_style="magenta",
    ))
    console.print("[dim]Simulated order only — no broker contacted.[/]")


@app.command()
def backtest(
    symbol: str,
    warmup: int = 60,
    limit: int = 500,
    signal: str = typer.Option("trend", help="trend (SMA-cross) | breakout (Donchian 55/20)"),
    adx: float = typer.Option(0.0, help="ADX regime gate for breakout (e.g. 25 = only enter when trending)"),
) -> None:
    """Walk-forward backtest with look-ahead guards (offline evaluation)."""
    from arthaai.backtest import run_backtest

    with console.status(f"[bold]backtesting {symbol.upper()}…"):
        res = run_backtest(symbol, warmup=warmup, limit=limit, signal=signal, adx_threshold=adx)
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
    console.print(t)
    console.print("[dim]Look-ahead-bias guarded: signal at day t only sees bars ≤ t.[/]")


@app.command()
def consume(max_messages: int = 10) -> None:
    """Consume ingestion events from the Kafka/Redpanda bus (needs `kafka` extra)."""
    from arthaai.data.consumer import consume as run_consume

    n = run_consume(max_messages=max_messages)
    console.print(f"consumed [bold]{n}[/] ingest events.")


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


if __name__ == "__main__":
    app()
