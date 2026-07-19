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
def ingest(symbol: str, days: int = 730) -> None:
    """Pull OHLCV for SYMBOL into TimescaleDB."""
    from arthaai.data import ingest as ingest_mod

    n = ingest_mod.ingest(symbol, lookback_days=days)
    console.print(f"ingested [bold]{n}[/] bars for [bold]{symbol.upper()}[/].")


@app.command()
def analyze(symbol: str, skip_ingest: bool = typer.Option(False, help="Use existing OHLCV.")) -> None:
    """Run the full multi-agent analysis pipeline for SYMBOL."""
    from arthaai.orchestration import analyze as run_analyze

    symbol = symbol.upper()
    with console.status(f"[bold]running multi-agent pipeline for {symbol}…"):
        state = run_analyze(symbol, skip_ingest=skip_ingest)

    db, quant = state.get("db", {}), state.get("quant", {})
    news, alt = state.get("news", {}), state.get("alt", {})
    verdict, alloc = state.get("verdict", {}), state.get("allocation", {})

    ev = Table(title=f"Agent evidence · {symbol}", show_header=True, header_style="bold")
    ev.add_column("Agent"); ev.add_column("Signal"); ev.add_column("Detail")
    if db.get("available"):
        ev.add_row("DB_Agent", db["trend"], f"close {db['last_close']} · RSI {db['rsi14'] and round(db['rsi14'],1)} · {db['bars']} bars")
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
def serve(port: int = 8000) -> None:
    """Run the Tier 1 FastAPI gateway."""
    import uvicorn

    uvicorn.run("arthaai.gateway.app:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    app()
