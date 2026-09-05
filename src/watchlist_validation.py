"""Deterministic read-only validation for the configured Spot watchlist.

This module joins the existing closed-candle feed gate, lightweight scanner,
candidate ranking and selective deep analysis.  It accepts already-fetched
market data and observed ticker prices so one host can capture a single batch
decision time without coupling this repository to an MCP transport.

It never mutates paper portfolio state and never sends exchange orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Mapping, Sequence

try:
    from .binance_live_paper_validation import SymbolFeedValidation, validate_symbol_feed
    from .execution import ExecutionConfig
    from .market_data import MarketData
    from .orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from .paper_runner import PaperRunnerConfig, build_closed_snapshot
    from .risk import RiskConfig
    from .scanner import ScanResult, WatchlistSymbol, rank_scan_results, scan_market
except ImportError:
    from binance_live_paper_validation import SymbolFeedValidation, validate_symbol_feed
    from execution import ExecutionConfig
    from market_data import MarketData
    from orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from paper_runner import PaperRunnerConfig, build_closed_snapshot
    from risk import RiskConfig
    from scanner import ScanResult, WatchlistSymbol, rank_scan_results, scan_market


DEEP_ANALYSIS_CLASSIFICATIONS = frozenset({"WATCH", "HIGH_INTEREST"})


@dataclass(frozen=True)
class WatchlistValidationConfig:
    reference_timeframe: str = "1h"
    require_observed_price: bool = True
    deep_analysis_classifications: frozenset[str] = DEEP_ANALYSIS_CLASSIFICATIONS


@dataclass
class WatchlistSymbolResult:
    symbol: str
    priority: str
    rank: int | None
    observed_spot_price: float | None
    feed: SymbolFeedValidation | None
    scan: ScanResult | None
    deep_analysis_selected: bool
    decision: AgentDecision | None
    status: str
    blockers: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WatchlistValidationResult:
    decision_time: int
    ready: bool
    paper_only: bool
    expected_symbols: list[str]
    provider_symbols: list[str]
    ranked_symbols: list[str]
    deep_analysis_symbols: list[str]
    symbols: list[WatchlistSymbolResult]
    blockers: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _normalized_watchlist(watchlist: Sequence[WatchlistSymbol]) -> list[WatchlistSymbol]:
    normalized: list[WatchlistSymbol] = []
    seen: set[str] = set()
    for item in watchlist:
        symbol = item.symbol.upper().strip()
        priority = item.priority.upper().strip()
        if not symbol or symbol in seen:
            raise ValueError("Watchlist symbols must be non-empty and unique")
        if not symbol.endswith("USDT"):
            raise ValueError(f"Unsupported non-USDT Spot symbol: {symbol}")
        if priority not in {"HIGH", "MEDIUM", "LOW"}:
            raise ValueError(f"Unsupported watchlist priority: {priority}")
        seen.add(symbol)
        normalized.append(WatchlistSymbol(symbol, priority))
    if not normalized:
        raise ValueError("Watchlist must contain at least one enabled symbol")
    return normalized


def _price(value: object) -> float | None:
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def validate_watchlist_batch(
    markets: Sequence[MarketData],
    watchlist: Sequence[WatchlistSymbol],
    *,
    decision_time: int,
    observed_prices: Mapping[str, float] | None = None,
    account_equity: float = 10_000.0,
    config: WatchlistValidationConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
) -> WatchlistValidationResult:
    """Validate and rank one immutable, paper-only multi-symbol snapshot."""

    cfg = config or WatchlistValidationConfig()
    agent_cfg = agent_config or AgentConfig(trading_mode="SPOT")
    if decision_time < 0:
        raise ValueError("decision_time must be >= 0")
    if account_equity <= 0:
        raise ValueError("account_equity must be > 0")
    if agent_cfg.trading_mode != "SPOT":
        raise ValueError("Watchlist real-feed validation is SPOT only")

    configured = _normalized_watchlist(watchlist)
    priorities = {item.symbol: item.priority for item in configured}
    expected = [item.symbol for item in configured]
    expected_set = set(expected)
    provider_symbols = [market.symbol.upper() for market in markets]
    blockers: list[str] = []

    duplicates = sorted({symbol for symbol in provider_symbols if provider_symbols.count(symbol) > 1})
    missing = sorted(expected_set - set(provider_symbols))
    unexpected = sorted(set(provider_symbols) - expected_set)
    if duplicates:
        blockers.append("DUPLICATE_PROVIDER_SYMBOLS:" + ",".join(duplicates))
    if missing:
        blockers.append("MISSING_PROVIDER_SYMBOLS:" + ",".join(missing))
    if unexpected:
        blockers.append("UNEXPECTED_PROVIDER_SYMBOLS:" + ",".join(unexpected))

    market_by_symbol: dict[str, MarketData] = {}
    for market in markets:
        market_by_symbol.setdefault(market.symbol.upper(), market)

    normalized_prices = {
        str(symbol).upper(): _price(value)
        for symbol, value in (observed_prices or {}).items()
    }
    runner_cfg = PaperRunnerConfig(
        reference_timeframe=cfg.reference_timeframe,
        require_reference_candle=True,
        require_exact_reference_close=True,
    )

    interim: dict[str, WatchlistSymbolResult] = {}
    valid_scans: list[ScanResult] = []
    closed_markets: dict[str, MarketData] = {}

    for item in configured:
        symbol = item.symbol
        market = market_by_symbol.get(symbol)
        price = normalized_prices.get(symbol)
        symbol_blockers: list[str] = []
        if market is None:
            interim[symbol] = WatchlistSymbolResult(
                symbol, item.priority, None, price, None, None, False, None,
                "INVALID_FEED", ["MISSING_PROVIDER_SYMBOL"],
            )
            continue
        if cfg.require_observed_price and price is None:
            symbol_blockers.append("MISSING_OR_INVALID_OBSERVED_PRICE")

        feed = validate_symbol_feed(
            market,
            decision_time=decision_time,
            runner_config=runner_cfg,
            smc_timeframe=agent_cfg.smc_timeframe,
        )
        symbol_blockers.extend(feed.blockers)
        scan: ScanResult | None = None
        if not symbol_blockers:
            closed = build_closed_snapshot(
                market,
                decision_time=decision_time,
                reference_timeframe=cfg.reference_timeframe,
            )
            closed_markets[symbol] = closed
            scan = scan_market(closed, priority=item.priority)
            if scan.errors:
                symbol_blockers.extend(scan.errors)
            else:
                valid_scans.append(scan)

        interim[symbol] = WatchlistSymbolResult(
            symbol=symbol,
            priority=item.priority,
            rank=None,
            observed_spot_price=price,
            feed=feed,
            scan=scan,
            deep_analysis_selected=False,
            decision=None,
            status="VALID" if not symbol_blockers else "INVALID_FEED",
            blockers=list(dict.fromkeys(symbol_blockers)),
        )

    ranked = rank_scan_results(valid_scans)
    ranked_symbols = [scan.symbol for scan in ranked]
    for rank, scan in enumerate(ranked, start=1):
        result = interim[scan.symbol]
        result.rank = rank
        if scan.classification not in cfg.deep_analysis_classifications:
            result.status = "SCANNED_ONLY"
            continue
        result.deep_analysis_selected = True
        decision = analyze_symbol(
            closed_markets[scan.symbol],
            account_equity=account_equity,
            config=replace(agent_cfg, watchlist_priority=priorities[scan.symbol], trading_mode="SPOT"),
            risk_config=risk_config,
            execution_config=execution_config,
        )
        result.decision = decision
        result.status = decision.action
        if decision.errors:
            for error in decision.errors:
                result.blockers.append(f"DEEP_ANALYSIS_ERROR:{error}")
        if decision.action == "ENTER_SHORT":
            result.blockers.append("SPOT_SHORT_INVARIANT_BREACH")
            blockers.append(f"{scan.symbol}:SPOT_SHORT_INVARIANT_BREACH")
            result.status = "BLOCKED"

    for symbol, result in interim.items():
        blockers.extend(f"{symbol}:{blocker}" for blocker in result.blockers)

    ordered = sorted(
        interim.values(),
        key=lambda result: (result.rank is None, result.rank or 10**9, expected.index(result.symbol)),
    )
    deep_symbols = [result.symbol for result in ordered if result.deep_analysis_selected]
    unique_blockers = list(dict.fromkeys(blockers))
    return WatchlistValidationResult(
        decision_time=decision_time,
        ready=not unique_blockers,
        paper_only=True,
        expected_symbols=expected,
        provider_symbols=provider_symbols,
        ranked_symbols=ranked_symbols,
        deep_analysis_symbols=deep_symbols,
        symbols=ordered,
        blockers=unique_blockers,
    )


def render_watchlist_validation(result: WatchlistValidationResult) -> str:
    lines = [
        f"SPOT WATCHLIST VALIDATION: {'READY' if result.ready else 'BLOCKED'}",
        f"Decision time: {result.decision_time}",
        "Mode: PAPER ONLY",
    ]
    for item in result.symbols:
        score = "n/a" if item.scan is None else f"{item.scan.score:.1f}"
        classification = "n/a" if item.scan is None else item.scan.classification
        lines.append(
            f"{item.rank or '-':>2} {item.symbol} [{item.priority}] "
            f"score={score} class={classification} deep={item.deep_analysis_selected} status={item.status}"
        )
        if item.blockers:
            lines.append("   blockers=" + ",".join(item.blockers))
    if result.blockers:
        lines.append("Global blockers: " + "; ".join(result.blockers))
    return "\n".join(lines)
