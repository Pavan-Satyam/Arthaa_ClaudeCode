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
def ingest(
    symbol: str,
    days: int = typer.Option(730, help="Lookback days (ignored if data already exists)."),
    timeframe: str = typer.Option("1d", help="Candle timeframe: 1d, 1h, 5m, 1m."),
    provider: str = typer.Option("auto", help="Data provider: auto (LSE→yfinance), lse, yfinance."),
) -> None:
    """Pull OHLCV for SYMBOL into TimescaleDB via the provider chain.

    Default 'auto' tries LSE first, falls back to yfinance if the symbol
    isn't available on LSE (e.g. USO). Use --provider lse or --provider
    yfinance to force a single source.
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


@app.command(name="factors")
def factors(
    action: str = typer.Argument("list", help="list | show | bench"),
    alpha_id: str = typer.Option("", help="Alpha ID for 'show' (e.g. alpha101_001)"),
    zoo: str = typer.Option("", help="Filter by zoo: alpha101, gtja191, qlib158"),
    top: int = typer.Option(20, help="Top-K results for bench"),
    symbols: str = typer.Option("GLD,SLV,XOM", help="Symbols for bench (comma-separated)"),
) -> None:
    """Alpha Zoo factor engine — list, show, or bench factors."""
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
        from arthaai.factors.panel import build_panel_from_symbols, compute_forward_returns
        from arthaai.factors.eval import compute_ic_series, compute_ic_stats, categorise

        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        with console.status(f"[bold]building panel for {sym_list}…"):
            panel = build_panel_from_symbols(sym_list, limit=1000)
        if not panel:
            console.print("[red]No data — run `arthaai ingest` first[/]")
            raise typer.Exit(1)

        fwd_ret = compute_forward_returns(panel)
        zoo_filter = zoo or None
        alpha_ids = reg.list(zoo=zoo_filter)

        console.print(f"Evaluating {len(alpha_ids)} factors over {len(sym_list)} assets…")
        t = Table(title=f"Factor bench · {zoo or 'all zoos'} · top {top} by |IR|")
        t.add_column("ID"); t.add_column("IC Mean", justify="right"); t.add_column("IR", justify="right")
        t.add_column("t-stat", justify="right"); t.add_column("Category"); t.add_column("Themes")

        results: list[tuple] = []
        for aid in alpha_ids:
            try:
                factor_df = reg.compute(aid, panel)
                ic = compute_ic_series(factor_df, fwd_ret)
                if ic.empty:
                    continue
                stats = compute_ic_stats(ic)
                cat = categorise(stats["ic_mean"], stats["ic_positive_ratio"], stats["ic_std"], stats["ic_count"])
                meta = reg.get(aid).meta
                results.append((aid, stats, cat, ", ".join(meta.get("theme", []))))
            except Exception:
                continue

        results.sort(key=lambda x: abs(x[1]["ir"]), reverse=True)
        for aid, stats, cat, themes in results[:top]:
            color = "green" if cat == "alive" else "red" if cat == "reversed" else "dim"
            t.add_row(
                aid,
                f"{stats['ic_mean']:+.4f}",
                f"{stats['ir']:+.4f}",
                f"{stats['t_stat']:.2f}",
                f"[{color}]{cat}[/]",
                themes,
            )
        console.print(t)
        console.print(f"\n[dim]{len(results)} factors evaluated · {sum(1 for _,_,c,_ in results if c=='alive')} alive · {sum(1 for _,_,c,_ in results if c=='reversed')} reversed · {sum(1 for _,_,c,_ in results if c=='dead')} dead[/]")

    else:
        console.print("[red]Usage: factors list | show | bench[/]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
