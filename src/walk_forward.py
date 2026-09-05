"""
Walk-Forward Validation Engine
Wyckoff + SMC Spot Swing Agent

Evaluates the unchanged strategy across multiple chronological research/test
windows. Each test window is strictly after its research window, so robustness
is judged across time instead of from a single train/test split.

This module does not optimize strategy parameters between folds.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .analytics import AnalyticsConfig
    from .backtest import BacktestConfig, BacktestResult
    from .execution import ExecutionConfig
    from .market_data import Candle, MarketData
    from .orchestrator import AgentConfig
    from .replay import ReplayConfig
    from .risk import RiskConfig
    from .validation import OOSConfig, ValidationWindowResult, _run_window, _slice_market_by_time
except ImportError:
    from analytics import AnalyticsConfig
    from backtest import BacktestConfig, BacktestResult
    from execution import ExecutionConfig
    from market_data import Candle, MarketData
    from orchestrator import AgentConfig
    from replay import ReplayConfig
    from risk import RiskConfig
    from validation import OOSConfig, ValidationWindowResult, _run_window, _slice_market_by_time


WalkForwardVerdict = Literal["ROBUST", "MIXED", "FAILED", "INSUFFICIENT_DATA"]

_TIMEFRAME_FIELD = {
    "1d": "daily",
    "4h": "four_hour",
    "1h": "one_hour",
    "15m": "fifteen_minute",
}


@dataclass(frozen=True)
class WalkForwardConfig:
    research_bars: int = 240
    validation_bars: int = 80
    step_bars: int = 80
    expanding_research: bool = False
    min_folds: int = 3
    min_research_trades: int = 3
    min_validation_trades: int = 2
    min_positive_fold_ratio: float = 0.60
    min_robust_fold_ratio: float = 0.50
    max_expectancy_degradation_pct: float = 50.0
    max_drawdown_multiplier: float = 1.75


@dataclass
class WalkForwardFold:
    fold: int
    research_start_index: int
    research_end_index: int
    validation_start_index: int
    validation_end_index: int
    research: ValidationWindowResult
    validation: ValidationWindowResult
    research_expectancy_r: float
    validation_expectancy_r: float
    expectancy_retention_pct: float | None
    verdict: str
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WalkForwardResult:
    symbol: str
    reference_timeframe: str
    folds: list[WalkForwardFold]
    total_folds: int
    robust_folds: int
    degraded_folds: int
    failed_folds: int
    insufficient_folds: int
    positive_validation_folds: int
    positive_fold_ratio: float
    robust_fold_ratio: float
    average_research_expectancy_r: float
    average_validation_expectancy_r: float
    verdict: WalkForwardVerdict
    reasons: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _reference_candles(market: MarketData, timeframe: str) -> list[Candle]:
    field = _TIMEFRAME_FIELD.get(timeframe)
    if field is None:
        raise ValueError(f"Unsupported walk-forward timeframe: {timeframe}")
    return getattr(market, field)


def _fold_verdict(research: BacktestResult, validation: BacktestResult, cfg: WalkForwardConfig) -> tuple[str, list[str], float | None]:
    reasons: list[str] = []
    if research.total_trades < cfg.min_research_trades or validation.total_trades < cfg.min_validation_trades:
        if research.total_trades < cfg.min_research_trades:
            reasons.append(f"Research has {research.total_trades} trades; minimum is {cfg.min_research_trades}.")
        if validation.total_trades < cfg.min_validation_trades:
            reasons.append(f"Validation has {validation.total_trades} trades; minimum is {cfg.min_validation_trades}.")
        return "INSUFFICIENT_DATA", reasons, None

    research_exp = research.expectancy_r
    validation_exp = validation.expectancy_r
    retention = validation_exp / research_exp * 100 if research_exp > 0 else None

    if research_exp <= 0:
        return "FAILED", ["Research expectancy is non-positive."], retention
    if validation_exp <= 0:
        return "FAILED", ["Validation expectancy is non-positive."], retention

    degradation = max(0.0, (research_exp - validation_exp) / research_exp * 100)
    dd_limit = max(research.max_drawdown_pct * cfg.max_drawdown_multiplier, research.max_drawdown_pct + 1.0)
    if degradation <= cfg.max_expectancy_degradation_pct and validation.max_drawdown_pct <= dd_limit:
        reasons.append(f"Validation retained {retention:.1f}% of research expectancy.")
        return "ROBUST", reasons, retention

    if degradation > cfg.max_expectancy_degradation_pct:
        reasons.append(f"Expectancy degraded by {degradation:.1f}%.")
    if validation.max_drawdown_pct > dd_limit:
        reasons.append("Validation drawdown exceeded the fold robustness limit.")
    return "DEGRADED", reasons, retention


def run_walk_forward(
    market: MarketData,
    *,
    account_equity: float,
    config: WalkForwardConfig | None = None,
    replay_config: ReplayConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
    backtest_config: BacktestConfig | None = None,
    analytics_config: AnalyticsConfig | None = None,
) -> WalkForwardResult:
    cfg = config or WalkForwardConfig()
    replay_cfg = replay_config or ReplayConfig()
    errors: list[str] = []

    if cfg.research_bars < replay_cfg.warmup_bars:
        errors.append("RESEARCH_WINDOW_BELOW_WARMUP")
    if cfg.validation_bars < replay_cfg.warmup_bars:
        errors.append("VALIDATION_WINDOW_BELOW_WARMUP")
    if cfg.step_bars < 1 or cfg.min_folds < 1:
        errors.append("INVALID_WALK_FORWARD_CONFIG")
    if cfg.min_research_trades < 1 or cfg.min_validation_trades < 1:
        errors.append("INVALID_MIN_TRADE_REQUIREMENT")
    if not 0 < cfg.min_positive_fold_ratio <= 1 or not 0 < cfg.min_robust_fold_ratio <= 1:
        errors.append("INVALID_FOLD_RATIO")
    if account_equity <= 0:
        errors.append("INVALID_ACCOUNT_EQUITY")

    reference = _reference_candles(market, replay_cfg.reference_timeframe)
    if len(reference) < cfg.research_bars + cfg.validation_bars:
        errors.append("INSUFFICIENT_WALK_FORWARD_BARS")

    if errors:
        return WalkForwardResult(
            market.symbol, replay_cfg.reference_timeframe, [], 0, 0, 0, 0, 0, 0,
            0.0, 0.0, 0.0, 0.0, "INSUFFICIENT_DATA", [],
            "Walk-forward validation cannot run because its configuration or history is insufficient.", errors,
        )

    folds: list[WalkForwardFold] = []
    validation_start = cfg.research_bars
    fold_number = 1
    while validation_start + cfg.validation_bars <= len(reference):
        research_start = 0 if cfg.expanding_research else validation_start - cfg.research_bars
        research_end = validation_start
        validation_end = validation_start + cfg.validation_bars

        research_start_ts = reference[research_start].timestamp
        validation_start_ts = reference[validation_start].timestamp
        validation_end_ts = reference[validation_end].timestamp if validation_end < len(reference) else None

        research_market = _slice_market_by_time(market, research_start_ts, validation_start_ts)
        validation_market = _slice_market_by_time(market, validation_start_ts, validation_end_ts)

        research = _run_window(
            f"FOLD_{fold_number}_RESEARCH", research_market,
            account_equity=account_equity, replay_config=replay_cfg, agent_config=agent_config,
            risk_config=risk_config, execution_config=execution_config,
            backtest_config=backtest_config, analytics_config=analytics_config,
        )
        validation = _run_window(
            f"FOLD_{fold_number}_VALIDATION", validation_market,
            account_equity=account_equity, replay_config=replay_cfg, agent_config=agent_config,
            risk_config=risk_config, execution_config=execution_config,
            backtest_config=backtest_config, analytics_config=analytics_config,
        )

        if research.backtest.errors or validation.backtest.errors:
            verdict, reasons, retention = "INSUFFICIENT_DATA", ["A fold backtest is invalid."], None
        else:
            verdict, reasons, retention = _fold_verdict(research.backtest, validation.backtest, cfg)

        folds.append(WalkForwardFold(
            fold=fold_number,
            research_start_index=research_start,
            research_end_index=research_end - 1,
            validation_start_index=validation_start,
            validation_end_index=validation_end - 1,
            research=research,
            validation=validation,
            research_expectancy_r=research.backtest.expectancy_r,
            validation_expectancy_r=validation.backtest.expectancy_r,
            expectancy_retention_pct=None if retention is None else round(retention, 4),
            verdict=verdict,
            reasons=reasons,
        ))
        fold_number += 1
        validation_start += cfg.step_bars

    total = len(folds)
    robust = sum(f.verdict == "ROBUST" for f in folds)
    degraded = sum(f.verdict == "DEGRADED" for f in folds)
    failed = sum(f.verdict == "FAILED" for f in folds)
    insufficient = sum(f.verdict == "INSUFFICIENT_DATA" for f in folds)
    usable = [f for f in folds if f.verdict != "INSUFFICIENT_DATA"]
    positive = sum(f.validation_expectancy_r > 0 for f in usable)
    positive_ratio = positive / len(usable) if usable else 0.0
    robust_ratio = robust / len(usable) if usable else 0.0
    avg_research = sum(f.research_expectancy_r for f in usable) / len(usable) if usable else 0.0
    avg_validation = sum(f.validation_expectancy_r for f in usable) / len(usable) if usable else 0.0

    reasons: list[str] = []
    if total < cfg.min_folds or not usable:
        verdict: WalkForwardVerdict = "INSUFFICIENT_DATA"
        reasons.append(f"Only {total} folds were generated; minimum is {cfg.min_folds}.")
    elif avg_validation <= 0 or positive_ratio < 0.50:
        verdict = "FAILED"
        reasons.append("Average validation expectancy is non-positive or fewer than half of usable folds are positive.")
    elif positive_ratio >= cfg.min_positive_fold_ratio and robust_ratio >= cfg.min_robust_fold_ratio:
        verdict = "ROBUST"
        reasons.append(f"{positive_ratio * 100:.1f}% of usable validation folds have positive expectancy.")
        reasons.append(f"{robust_ratio * 100:.1f}% of usable folds meet the strict robustness criteria.")
    else:
        verdict = "MIXED"
        reasons.append("The strategy remains positive overall, but robustness is inconsistent across time windows.")

    interpretation = {
        "ROBUST": "The unchanged strategy preserves positive edge across multiple chronological validation windows.",
        "MIXED": "Edge survives in aggregate, but results vary enough across time to require more validation before paper trading.",
        "FAILED": "The strategy does not preserve a dependable positive edge across chronological validation windows.",
        "INSUFFICIENT_DATA": "There are not enough trustworthy walk-forward folds to judge temporal robustness yet.",
    }[verdict]

    return WalkForwardResult(
        symbol=market.symbol,
        reference_timeframe=replay_cfg.reference_timeframe,
        folds=folds,
        total_folds=total,
        robust_folds=robust,
        degraded_folds=degraded,
        failed_folds=failed,
        insufficient_folds=insufficient,
        positive_validation_folds=positive,
        positive_fold_ratio=round(positive_ratio, 4),
        robust_fold_ratio=round(robust_ratio, 4),
        average_research_expectancy_r=round(avg_research, 4),
        average_validation_expectancy_r=round(avg_validation, 4),
        verdict=verdict,
        reasons=reasons,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Walk-forward validation engine ready.")
