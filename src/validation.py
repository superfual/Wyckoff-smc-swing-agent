"""
Out-of-Sample Validation Engine
Wyckoff + SMC Spot Swing Agent

Splits historical data into research and validation windows, runs the same
unchanged replay/backtest/analytics pipeline on both, and compares whether
observed edge survives outside the research sample.

This module does not optimize parameters and does not mutate strategy rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .analytics import AnalyticsConfig, PerformanceAnalytics, analyze_backtest
    from .backtest import BacktestConfig, BacktestResult, run_backtest
    from .execution import ExecutionConfig
    from .market_data import Candle, MarketData
    from .orchestrator import AgentConfig
    from .replay import ReplayConfig, ReplayResult, run_replay
    from .risk import RiskConfig
except ImportError:  # Allows: python src/validation.py
    from analytics import AnalyticsConfig, PerformanceAnalytics, analyze_backtest
    from backtest import BacktestConfig, BacktestResult, run_backtest
    from execution import ExecutionConfig
    from market_data import Candle, MarketData
    from orchestrator import AgentConfig
    from replay import ReplayConfig, ReplayResult, run_replay
    from risk import RiskConfig


ValidationVerdict = Literal["ROBUST", "DEGRADED", "FAILED", "INSUFFICIENT_DATA"]

_TIMEFRAME_FIELD = {
    "1d": "daily",
    "4h": "four_hour",
    "1h": "one_hour",
    "15m": "fifteen_minute",
}


@dataclass(frozen=True)
class OOSConfig:
    split_ratio: float = 0.70
    min_research_trades: int = 5
    min_validation_trades: int = 3
    max_expectancy_degradation_pct: float = 50.0
    max_drawdown_multiplier: float = 1.75


@dataclass
class ValidationWindowResult:
    name: str
    start_timestamp: int | None
    end_timestamp: int | None
    replay: ReplayResult
    backtest: BacktestResult
    analytics: PerformanceAnalytics

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OOSValidationResult:
    symbol: str
    reference_timeframe: str
    split_bar_index: int
    split_timestamp: int | None
    research: ValidationWindowResult | None
    validation: ValidationWindowResult | None
    expectancy_research_r: float
    expectancy_validation_r: float
    expectancy_retention_pct: float | None
    win_rate_research_pct: float
    win_rate_validation_pct: float
    profit_factor_research: float | None
    profit_factor_validation: float | None
    drawdown_research_pct: float
    drawdown_validation_pct: float
    verdict: ValidationVerdict
    reasons: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _reference_candles(market: MarketData, timeframe: str) -> list[Candle]:
    field = _TIMEFRAME_FIELD.get(timeframe)
    if field is None:
        raise ValueError(f"Unsupported validation timeframe: {timeframe}")
    return getattr(market, field)


def _slice_market_by_time(market: MarketData, start_ts: int | None, end_ts: int | None) -> MarketData:
    def subset(candles: list[Candle]) -> list[Candle]:
        return [
            candle for candle in candles
            if (start_ts is None or candle.timestamp >= start_ts)
            and (end_ts is None or candle.timestamp < end_ts)
        ]

    one_hour = subset(market.one_hour)
    return MarketData(
        symbol=market.symbol,
        current_price=one_hour[-1].close if one_hour else None,
        daily=subset(market.daily),
        four_hour=subset(market.four_hour),
        one_hour=one_hour,
        fifteen_minute=subset(market.fifteen_minute),
    )


def _run_window(
    name: str,
    market: MarketData,
    *,
    account_equity: float,
    replay_config: ReplayConfig,
    agent_config: AgentConfig | None,
    risk_config: RiskConfig | None,
    execution_config: ExecutionConfig | None,
    backtest_config: BacktestConfig | None,
    analytics_config: AnalyticsConfig | None,
) -> ValidationWindowResult:
    replay = run_replay(
        market,
        account_equity=account_equity,
        config=replay_config,
        agent_config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
    )
    backtest = run_backtest(
        replay,
        market,
        initial_equity=account_equity,
        config=backtest_config,
    )
    analytics = analyze_backtest(backtest, config=analytics_config)
    reference = _reference_candles(market, replay_config.reference_timeframe)
    return ValidationWindowResult(
        name=name,
        start_timestamp=reference[0].timestamp if reference else None,
        end_timestamp=reference[-1].timestamp if reference else None,
        replay=replay,
        backtest=backtest,
        analytics=analytics,
    )


def _profit_factor_value(value: float | None) -> float:
    if value is None:
        return 0.0
    if value == float("inf"):
        return 999999.0
    return value


def validate_out_of_sample(
    market: MarketData,
    *,
    account_equity: float,
    config: OOSConfig | None = None,
    replay_config: ReplayConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
    backtest_config: BacktestConfig | None = None,
    analytics_config: AnalyticsConfig | None = None,
) -> OOSValidationResult:
    """Compare unchanged strategy behavior on research vs unseen data."""

    cfg = config or OOSConfig()
    replay_cfg = replay_config or ReplayConfig()
    errors: list[str] = []

    if not 0.50 <= cfg.split_ratio <= 0.90:
        errors.append("INVALID_SPLIT_RATIO")
    if cfg.min_research_trades < 1 or cfg.min_validation_trades < 1:
        errors.append("INVALID_MIN_TRADE_REQUIREMENT")
    if cfg.max_expectancy_degradation_pct < 0:
        errors.append("INVALID_EXPECTANCY_DEGRADATION")
    if cfg.max_drawdown_multiplier <= 0:
        errors.append("INVALID_DRAWDOWN_MULTIPLIER")
    if account_equity <= 0:
        errors.append("INVALID_ACCOUNT_EQUITY")

    reference = _reference_candles(market, replay_cfg.reference_timeframe)
    if len(reference) < replay_cfg.warmup_bars * 2:
        errors.append("INSUFFICIENT_VALIDATION_BARS")

    if errors:
        return OOSValidationResult(
            symbol=market.symbol,
            reference_timeframe=replay_cfg.reference_timeframe,
            split_bar_index=0,
            split_timestamp=None,
            research=None,
            validation=None,
            expectancy_research_r=0.0,
            expectancy_validation_r=0.0,
            expectancy_retention_pct=None,
            win_rate_research_pct=0.0,
            win_rate_validation_pct=0.0,
            profit_factor_research=None,
            profit_factor_validation=None,
            drawdown_research_pct=0.0,
            drawdown_validation_pct=0.0,
            verdict="INSUFFICIENT_DATA",
            reasons=[],
            interpretation="Out-of-sample validation cannot run because its inputs are invalid or too short.",
            errors=errors,
        )

    split_index = int(len(reference) * cfg.split_ratio)
    split_index = min(max(split_index, replay_cfg.warmup_bars), len(reference) - replay_cfg.warmup_bars)
    split_timestamp = reference[split_index].timestamp

    research_market = _slice_market_by_time(market, None, split_timestamp)
    validation_market = _slice_market_by_time(market, split_timestamp, None)

    research = _run_window(
        "RESEARCH",
        research_market,
        account_equity=account_equity,
        replay_config=replay_cfg,
        agent_config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
        backtest_config=backtest_config,
        analytics_config=analytics_config,
    )
    validation = _run_window(
        "VALIDATION",
        validation_market,
        account_equity=account_equity,
        replay_config=replay_cfg,
        agent_config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
        backtest_config=backtest_config,
        analytics_config=analytics_config,
    )

    reasons: list[str] = []
    research_bt = research.backtest
    validation_bt = validation.backtest

    if research_bt.errors or validation_bt.errors:
        return OOSValidationResult(
            market.symbol, replay_cfg.reference_timeframe, split_index, split_timestamp,
            research, validation, 0.0, 0.0, None, 0.0, 0.0, None, None, 0.0, 0.0,
            "INSUFFICIENT_DATA", ["Research or validation backtest is invalid."],
            "Validation result cannot be trusted because one window failed.", ["WINDOW_BACKTEST_INVALID"],
        )

    research_exp = research_bt.expectancy_r
    validation_exp = validation_bt.expectancy_r
    retention = None
    if research_exp > 0:
        retention = validation_exp / research_exp * 100

    if research_bt.total_trades < cfg.min_research_trades:
        reasons.append(f"Research sample has only {research_bt.total_trades} trades; minimum is {cfg.min_research_trades}.")
    if validation_bt.total_trades < cfg.min_validation_trades:
        reasons.append(f"Validation sample has only {validation_bt.total_trades} trades; minimum is {cfg.min_validation_trades}.")

    if reasons:
        verdict: ValidationVerdict = "INSUFFICIENT_DATA"
    elif research_exp <= 0:
        verdict = "FAILED"
        reasons.append("Research sample does not show positive expectancy, so there is no positive edge to validate.")
    elif validation_exp <= 0:
        verdict = "FAILED"
        reasons.append("Validation expectancy is non-positive; the research edge did not survive unseen data.")
    else:
        degradation_pct = max(0.0, (research_exp - validation_exp) / research_exp * 100)
        drawdown_limit = max(research_bt.max_drawdown_pct * cfg.max_drawdown_multiplier, research_bt.max_drawdown_pct + 1.0)
        pf_research = _profit_factor_value(research_bt.profit_factor)
        pf_validation = _profit_factor_value(validation_bt.profit_factor)

        if degradation_pct <= cfg.max_expectancy_degradation_pct and validation_bt.max_drawdown_pct <= drawdown_limit:
            verdict = "ROBUST"
            reasons.append(f"Validation retained {retention:.1f}% of research expectancy.")
            reasons.append("Validation drawdown remains within the configured robustness limit.")
        else:
            verdict = "DEGRADED"
            if degradation_pct > cfg.max_expectancy_degradation_pct:
                reasons.append(
                    f"Expectancy degraded by {degradation_pct:.1f}%, above the {cfg.max_expectancy_degradation_pct:.1f}% limit."
                )
            if validation_bt.max_drawdown_pct > drawdown_limit:
                reasons.append("Validation drawdown expanded beyond the configured robustness limit.")
            if pf_validation < pf_research * 0.5:
                reasons.append("Validation profit factor fell to less than half the research value.")

    interpretation = {
        "ROBUST": "Positive expectancy persists on unseen data without unacceptable degradation. The edge survives this first out-of-sample checkpoint.",
        "DEGRADED": "The strategy remains positive out-of-sample, but performance weakened enough to require caution before paper trading.",
        "FAILED": "The apparent research edge does not survive the unseen validation window.",
        "INSUFFICIENT_DATA": "There are not enough trustworthy trades to make an out-of-sample judgment yet.",
    }[verdict]

    return OOSValidationResult(
        symbol=market.symbol,
        reference_timeframe=replay_cfg.reference_timeframe,
        split_bar_index=split_index,
        split_timestamp=split_timestamp,
        research=research,
        validation=validation,
        expectancy_research_r=research_exp,
        expectancy_validation_r=validation_exp,
        expectancy_retention_pct=None if retention is None else round(retention, 4),
        win_rate_research_pct=research_bt.win_rate_pct,
        win_rate_validation_pct=validation_bt.win_rate_pct,
        profit_factor_research=research_bt.profit_factor,
        profit_factor_validation=validation_bt.profit_factor,
        drawdown_research_pct=research_bt.max_drawdown_pct,
        drawdown_validation_pct=validation_bt.max_drawdown_pct,
        verdict=verdict,
        reasons=reasons,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Out-of-sample validation engine ready.")
