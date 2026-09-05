"""Operational readiness checks for connecting a real read-only Spot paper feed.

This is separate from strategy promotion readiness. It answers whether the paper
runtime plumbing is configured safely enough to consume real closed-candle data.
It never enables exchange orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

try:
    from .execution import ExecutionConfig
    from .orchestrator import AgentConfig
    from .paper_runner import PaperRunnerConfig
    from .paper_runtime import PaperRuntime, PaperRuntimeConfig
except ImportError:
    from execution import ExecutionConfig
    from orchestrator import AgentConfig
    from paper_runner import PaperRunnerConfig
    from paper_runtime import PaperRuntime, PaperRuntimeConfig


@dataclass(frozen=True)
class LivePaperReadiness:
    ready: bool
    checks: tuple[tuple[str, bool], ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_live_paper_readiness(
    runtime: PaperRuntime,
    *,
    runtime_config: PaperRuntimeConfig | None = None,
    runner_config: PaperRunnerConfig | None = None,
    agent_config: AgentConfig | None = None,
    execution_config: ExecutionConfig | None = None,
) -> LivePaperReadiness:
    runtime_cfg = runtime_config or PaperRuntimeConfig(checkpoint_path=runtime.checkpoint_path)
    runner_cfg = runner_config or PaperRunnerConfig()
    agent_cfg = agent_config or AgentConfig()
    execution_cfg = execution_config or ExecutionConfig(trading_mode=agent_cfg.trading_mode)

    checks = (
        ("NO_STICKY_RUNTIME_ERRORS", not runtime.errors),
        ("SPOT_AGENT_MODE", agent_cfg.trading_mode == "SPOT"),
        ("SPOT_EXECUTION_MODE", execution_cfg.trading_mode == "SPOT"),
        ("MODE_CONSISTENT", agent_cfg.trading_mode == execution_cfg.trading_mode),
        ("CHECKPOINT_ENABLED", runtime_cfg.checkpoint_after_cycle),
        ("AUTO_RECOVERY_ENABLED", runtime_cfg.auto_recover),
        ("STATE_PATH_IS_LOCAL", runtime_cfg.checkpoint_path.startswith("state/")),
        ("FAIR_ALLOCATION_ENABLED", runner_cfg.fair_same_cycle_allocation),
        ("EXACT_CLOSED_CANDLE_REQUIRED", runner_cfg.require_exact_reference_close),
        ("HAS_SYMBOLS", bool(runtime.symbols)),
    )
    blockers = tuple(code for code, passed in checks if not passed)
    return LivePaperReadiness(ready=not blockers, checks=checks, blockers=blockers)


def render_live_paper_readiness(result: LivePaperReadiness) -> str:
    lines = [f"LIVE PAPER READINESS: {'READY' if result.ready else 'BLOCKED'}"]
    lines.extend(f"  {'PASS' if passed else 'FAIL'} {code}" for code, passed in result.checks)
    if result.blockers:
        lines.append("Blockers: " + ", ".join(result.blockers))
    return "\n".join(lines)
