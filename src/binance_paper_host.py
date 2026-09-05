"""
Binance MCP Paper Host Harness
Wyckoff + SMC Spot Swing Agent

Small host-facing composition layer that wires a concrete MCP tool-call function
into the read-only Binance MCP bridge, Binance market-data provider, and
PaperRuntime. This is intentionally paper-only: it contains no exchange order,
account, transfer, or credential operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

try:
    from .binance_adapter import BinanceAdapterConfig, BinanceMarketDataProvider
    from .binance_mcp_bridge import BinanceMCPBridgeConfig, BinanceMCPClientBridge
    from .paper_runtime import (
        PaperRuntime,
        PaperRuntimeConfig,
        RuntimeCycleResult,
        create_paper_runtime,
        run_runtime_cycle,
    )
    from .paper_runner import PaperRunnerConfig
    from .paper_session import PaperSessionConfig
    from .paper_trading import PaperTradingConfig
    from .orchestrator import AgentConfig
    from .risk import RiskConfig
    from .execution import ExecutionConfig
except ImportError:
    from binance_adapter import BinanceAdapterConfig, BinanceMarketDataProvider
    from binance_mcp_bridge import BinanceMCPBridgeConfig, BinanceMCPClientBridge
    from paper_runtime import (
        PaperRuntime,
        PaperRuntimeConfig,
        RuntimeCycleResult,
        create_paper_runtime,
        run_runtime_cycle,
    )
    from paper_runner import PaperRunnerConfig
    from paper_session import PaperSessionConfig
    from paper_trading import PaperTradingConfig
    from orchestrator import AgentConfig
    from risk import RiskConfig
    from execution import ExecutionConfig


ToolCall = Callable[[str, dict[str, Any]], Any]


class CallableMCPInvoker:
    """Adapts a host callable to the MCPToolInvoker protocol."""

    def __init__(self, tool_call: ToolCall) -> None:
        if not callable(tool_call):
            raise TypeError("tool_call must be callable")
        self._tool_call = tool_call

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return self._tool_call(tool_name, arguments)


@dataclass(frozen=True)
class BinancePaperHostConfig:
    runtime: PaperRuntimeConfig = PaperRuntimeConfig()
    bridge: BinanceMCPBridgeConfig = BinanceMCPBridgeConfig()
    adapter: BinanceAdapterConfig = BinanceAdapterConfig()
    runner: PaperRunnerConfig = PaperRunnerConfig()
    paper: PaperTradingConfig = PaperTradingConfig()
    agent: AgentConfig = AgentConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    session: PaperSessionConfig = PaperSessionConfig()


@dataclass
class BinancePaperHost:
    runtime: PaperRuntime
    provider: BinanceMarketDataProvider
    config: BinancePaperHostConfig


def create_binance_paper_host(
    tool_call: ToolCall,
    *,
    symbols: Sequence[str] | None = None,
    config: BinancePaperHostConfig | None = None,
) -> BinancePaperHost:
    """Compose the paper-only Binance MCP stack for one host process."""
    cfg = config or BinancePaperHostConfig()
    invoker = CallableMCPInvoker(tool_call)
    bridge = BinanceMCPClientBridge(invoker, cfg.bridge)
    provider = BinanceMarketDataProvider(bridge, cfg.adapter)
    runtime = create_paper_runtime(
        symbols=symbols,
        runtime_config=cfg.runtime,
        session_config=cfg.session,
    )
    return BinancePaperHost(runtime=runtime, provider=provider, config=cfg)


def run_binance_paper_cycle(
    host: BinancePaperHost,
    *,
    decision_time: int,
) -> RuntimeCycleResult:
    """Run exactly one paper cycle using the composed read-only Binance stack."""
    cfg = host.config
    return run_runtime_cycle(
        host.runtime,
        host.provider,
        decision_time=decision_time,
        runtime_config=cfg.runtime,
        runner_config=cfg.runner,
        paper_config=cfg.paper,
        agent_config=cfg.agent,
        risk_config=cfg.risk,
        execution_config=cfg.execution,
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Binance MCP paper host harness ready; host tool_call callable required.")
