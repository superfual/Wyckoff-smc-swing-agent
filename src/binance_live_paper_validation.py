"""Read-only Binance live-paper feed preflight validation.

Validates real market-data snapshots before they are allowed to mutate paper
portfolio state. Binance klines normally include the currently forming candle;
that raw candle is expected and is reported as a warning when the closed-candle
projection safely removes it. Strategy-history sufficiency is evaluated on the
closed snapshot before the feed may become READY. This module never authenticates
to an exchange and never sends orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

try:
    from .execution import ExecutionConfig
    from .history_sufficiency import HistorySufficiency, evaluate_history_sufficiency
    from .market_data import MarketData
    from .orchestrator import AgentConfig
    from .paper_readiness import LivePaperReadiness, evaluate_live_paper_readiness
    from .paper_runner import PaperRunnerConfig, build_closed_snapshot
    from .paper_runtime import MarketDataProvider, PaperRuntime, PaperRuntimeConfig
except ImportError:
    from execution import ExecutionConfig
    from history_sufficiency import HistorySufficiency, evaluate_history_sufficiency
    from market_data import MarketData
    from orchestrator import AgentConfig
    from paper_readiness import LivePaperReadiness, evaluate_live_paper_readiness
    from paper_runner import PaperRunnerConfig, build_closed_snapshot
    from paper_runtime import MarketDataProvider, PaperRuntime, PaperRuntimeConfig

_TIMEFRAME_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000, "15m": 900_000}
_TIMEFRAME_FIELD = {"1d": "daily", "4h": "four_hour", "1h": "one_hour", "15m": "fifteen_minute"}


@dataclass(frozen=True)
class SymbolFeedValidation:
    symbol: str
    valid: bool
    current_price: float | None
    reference_close_time: int | None
    raw_candle_counts: tuple[tuple[str, int], ...]
    candle_counts: tuple[tuple[str, int], ...]
    open_candle_counts: tuple[tuple[str, int], ...]
    history: HistorySufficiency
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class BinanceLivePaperPreflight:
    ready: bool
    decision_time: int
    readiness: LivePaperReadiness
    provider_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    unexpected_symbols: tuple[str, ...]
    symbols: tuple[SymbolFeedValidation, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _reference_close_time(market: MarketData, timeframe: str) -> int | None:
    candles = getattr(market, _TIMEFRAME_FIELD[timeframe])
    if not candles:
        return None
    return candles[-1].timestamp + _TIMEFRAME_MS[timeframe]


def _validate_symbol_feed(
    market: MarketData,
    *,
    decision_time: int,
    runner_config: PaperRunnerConfig,
    smc_timeframe: str,
) -> SymbolFeedValidation:
    blockers: list[str] = []
    warnings: list[str] = []
    closed = build_closed_snapshot(
        market,
        decision_time=decision_time,
        reference_timeframe=runner_config.reference_timeframe,
    )
    raw_counts = tuple((name, len(getattr(market, field))) for name, field in _TIMEFRAME_FIELD.items())
    counts = tuple((name, len(getattr(closed, field))) for name, field in _TIMEFRAME_FIELD.items())
    open_counts: list[tuple[str, int]] = []
    for timeframe, field in _TIMEFRAME_FIELD.items():
        raw = getattr(market, field)
        closed_tf = getattr(closed, field)
        dropped = len(raw) - len(closed_tf)
        open_counts.append((timeframe, max(dropped, 0)))
        if dropped > 0:
            warnings.append(f"EXPECTED_OPEN_CANDLE_DROPPED:{timeframe}:{dropped}")

    reference_close = _reference_close_time(closed, runner_config.reference_timeframe)
    if closed.current_price is None or closed.current_price <= 0:
        blockers.append("INVALID_CLOSED_REFERENCE_PRICE")
    if runner_config.require_reference_candle and reference_close is None:
        blockers.append("REFERENCE_CANDLE_UNAVAILABLE")
    if runner_config.require_exact_reference_close and reference_close is not None and reference_close != decision_time:
        blockers.append("REFERENCE_CANDLE_NOT_FRESH")
    for timeframe, field in _TIMEFRAME_FIELD.items():
        candles = getattr(closed, field)
        if not candles:
            blockers.append(f"MISSING_TIMEFRAME:{timeframe}")
        elif any(candle.timestamp + _TIMEFRAME_MS[timeframe] > decision_time for candle in candles):
            blockers.append(f"UNCLOSED_CANDLE_LEAK:{timeframe}")

    history = evaluate_history_sufficiency(closed, smc_timeframe=smc_timeframe)
    blockers.extend(history.blockers)
    warnings.extend(history.warnings)

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_warnings = tuple(dict.fromkeys(warnings))
    return SymbolFeedValidation(
        symbol=market.symbol.upper(),
        valid=not unique_blockers,
        current_price=closed.current_price,
        reference_close_time=reference_close,
        raw_candle_counts=raw_counts,
        candle_counts=counts,
        open_candle_counts=tuple(open_counts),
        history=history,
        warnings=unique_warnings,
        blockers=unique_blockers,
    )


def validate_binance_live_paper_feed(
    runtime: PaperRuntime,
    provider: MarketDataProvider,
    *,
    decision_time: int,
    runtime_config: PaperRuntimeConfig | None = None,
    runner_config: PaperRunnerConfig | None = None,
    agent_config: AgentConfig | None = None,
    execution_config: ExecutionConfig | None = None,
) -> BinanceLivePaperPreflight:
    """Fetch and validate real read-only snapshots without mutating paper state."""
    if decision_time < 0:
        raise ValueError("decision_time must be >= 0")

    runtime_cfg = runtime_config or PaperRuntimeConfig(checkpoint_path=runtime.checkpoint_path)
    runner_cfg = runner_config or PaperRunnerConfig()
    agent_cfg = agent_config or AgentConfig()
    readiness = evaluate_live_paper_readiness(
        runtime,
        runtime_config=runtime_cfg,
        runner_config=runner_cfg,
        agent_config=agent_cfg,
        execution_config=execution_config,
    )
    blockers: list[str] = list(readiness.blockers)

    try:
        markets = provider.fetch_markets(runtime.symbols, decision_time=decision_time)
    except Exception as exc:
        return BinanceLivePaperPreflight(
            ready=False,
            decision_time=decision_time,
            readiness=readiness,
            provider_symbols=(),
            missing_symbols=tuple(runtime.symbols),
            unexpected_symbols=(),
            symbols=(),
            blockers=tuple(dict.fromkeys(blockers + [f"MARKET_DATA_PROVIDER_ERROR:{type(exc).__name__}"])),
        )

    if not isinstance(markets, list) or any(not isinstance(item, MarketData) for item in markets):
        return BinanceLivePaperPreflight(
            ready=False,
            decision_time=decision_time,
            readiness=readiness,
            provider_symbols=(),
            missing_symbols=tuple(runtime.symbols),
            unexpected_symbols=(),
            symbols=(),
            blockers=tuple(dict.fromkeys(blockers + ["INVALID_PROVIDER_RESULT"])),
        )

    provider_symbols = tuple(market.symbol.upper() for market in markets)
    expected = set(runtime.symbols)
    missing = tuple(sorted(expected - set(provider_symbols)))
    unexpected = tuple(sorted(set(provider_symbols) - expected))
    if missing:
        blockers.append("MISSING_PROVIDER_SYMBOLS:" + ",".join(missing))
    if unexpected:
        blockers.append("UNEXPECTED_PROVIDER_SYMBOLS:" + ",".join(unexpected))

    validations = tuple(
        _validate_symbol_feed(
            market,
            decision_time=decision_time,
            runner_config=runner_cfg,
            smc_timeframe=agent_cfg.smc_timeframe,
        )
        for market in markets
        if market.symbol.upper() in expected
    )
    for item in validations:
        blockers.extend(f"{item.symbol}:{blocker}" for blocker in item.blockers)

    unique_blockers = tuple(dict.fromkeys(blockers))
    return BinanceLivePaperPreflight(
        ready=readiness.ready and not unique_blockers,
        decision_time=decision_time,
        readiness=readiness,
        provider_symbols=provider_symbols,
        missing_symbols=missing,
        unexpected_symbols=unexpected,
        symbols=validations,
        blockers=unique_blockers,
    )


def render_binance_live_paper_preflight(result: BinanceLivePaperPreflight) -> str:
    lines = [f"BINANCE LIVE PAPER PREFLIGHT: {'READY' if result.ready else 'BLOCKED'}"]
    lines.append(f"Decision time: {result.decision_time}")
    for item in result.symbols:
        raw = ", ".join(f"{tf}={count}" for tf, count in item.raw_candle_counts)
        closed = ", ".join(f"{tf}={count}" for tf, count in item.candle_counts)
        lines.append(
            f"{item.symbol}: {'PASS' if item.valid else 'FAIL'} | price={item.current_price} | "
            f"reference_close={item.reference_close_time} | raw[{raw}] | closed[{closed}] | "
            f"history={'PASS' if item.history.ready else 'BLOCKED'}"
        )
        if item.warnings:
            lines.append("  Warnings: " + ", ".join(item.warnings))
        if item.blockers:
            lines.append("  Blockers: " + ", ".join(item.blockers))
    if result.blockers:
        lines.append("Global blockers: " + "; ".join(result.blockers))
    return "\n".join(lines)
