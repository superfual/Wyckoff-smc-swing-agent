from src.portfolio_safety import (
    DAY_MS,
    PortfolioSafetyConfig,
    PortfolioSafetyState,
    assess_portfolio_safety,
    set_kill_switch,
)


def test_allows_entries_below_limits():
    state = PortfolioSafetyState()
    result = assess_portfolio_safety(state=state, timestamp=DAY_MS, equity=10_000, open_positions=1)
    assert result.allow_new_entries is True
    assert result.blockers == ()
    assert state.day_start_equity == 10_000


def test_max_concurrent_positions_blocks_new_entries():
    result = assess_portfolio_safety(
        state=PortfolioSafetyState(),
        timestamp=DAY_MS,
        equity=10_000,
        open_positions=3,
        config=PortfolioSafetyConfig(max_concurrent_positions=3),
    )
    assert result.allow_new_entries is False
    assert "MAX_CONCURRENT_POSITIONS_REACHED" in result.blockers


def test_correlation_group_blocks_third_crypto_beta_position():
    result = assess_portfolio_safety(
        state=PortfolioSafetyState(),
        timestamp=DAY_MS,
        equity=10_000,
        open_positions=2,
        candidate_symbol="SOLUSDT",
        open_symbols=("BTCUSDT", "ETHUSDT"),
        config=PortfolioSafetyConfig(
            max_concurrent_positions=5,
            max_positions_per_correlation_group=2,
        ),
    )
    assert result.allow_new_entries is False
    assert "CORRELATION_GROUP_LIMIT_REACHED:CRYPTO_BETA" in result.blockers


def test_different_correlation_group_can_still_enter():
    result = assess_portfolio_safety(
        state=PortfolioSafetyState(),
        timestamp=DAY_MS,
        equity=10_000,
        open_positions=2,
        candidate_symbol="UNIUSDT",
        open_symbols=("BTCUSDT", "ETHUSDT"),
        config=PortfolioSafetyConfig(
            max_concurrent_positions=5,
            max_positions_per_correlation_group=2,
        ),
    )
    assert result.allow_new_entries is True


def test_daily_loss_guard_uses_stable_day_baseline_and_resets_next_day():
    state = PortfolioSafetyState()
    cfg = PortfolioSafetyConfig(max_daily_loss_pct=3.0)
    assess_portfolio_safety(state=state, timestamp=DAY_MS + 1, equity=10_000, open_positions=0, config=cfg)
    loss = assess_portfolio_safety(state=state, timestamp=DAY_MS + 2, equity=9_690, open_positions=0, config=cfg)
    assert loss.daily_pnl_pct == -3.1
    assert "DAILY_LOSS_LIMIT_REACHED" in loss.blockers

    reset = assess_portfolio_safety(state=state, timestamp=2 * DAY_MS + 1, equity=9_690, open_positions=0, config=cfg)
    assert reset.allow_new_entries is True
    assert reset.daily_pnl_pct == 0.0
    assert state.day_start_equity == 9_690


def test_kill_switch_is_explicit_and_reversible():
    state = PortfolioSafetyState()
    set_kill_switch(state, True)
    blocked = assess_portfolio_safety(state=state, timestamp=0, equity=10_000, open_positions=0)
    assert blocked.blockers == ("PORTFOLIO_KILL_SWITCH_ACTIVE",)

    set_kill_switch(state, False)
    allowed = assess_portfolio_safety(state=state, timestamp=1, equity=10_000, open_positions=0)
    assert allowed.allow_new_entries is True


def test_invalid_safety_config_fails_closed():
    try:
        assess_portfolio_safety(
            state=PortfolioSafetyState(),
            timestamp=0,
            equity=10_000,
            open_positions=0,
            config=PortfolioSafetyConfig(max_concurrent_positions=0),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
