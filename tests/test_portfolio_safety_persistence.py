from src.paper_runner import PaperRunnerState
from src.paper_session import create_paper_session
from src.persistence import load_checkpoint, save_checkpoint
from src.portfolio_safety import set_kill_switch


def test_kill_switch_and_daily_baseline_survive_checkpoint(tmp_path):
    session = create_paper_session()
    set_kill_switch(session.portfolio_safety, True)
    session.portfolio_safety.current_day_index = 123
    session.portfolio_safety.day_start_equity = 9876.5
    runner = PaperRunnerState(last_cycle_time=123 * 86_400_000, cycles=5)

    path = save_checkpoint(tmp_path / "paper.json", session, runner)
    recovered = load_checkpoint(path)

    assert recovered.recovered is True
    safety = recovered.session.portfolio_safety
    assert safety.kill_switch_active is True
    assert safety.current_day_index == 123
    assert safety.day_start_equity == 9876.5


def test_legacy_checkpoint_without_portfolio_safety_defaults_safe_state(tmp_path):
    session = create_paper_session()
    runner = PaperRunnerState(last_cycle_time=1, cycles=1)
    path = save_checkpoint(tmp_path / "paper.json", session, runner)

    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["paper_session"].pop("portfolio_safety", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    recovered = load_checkpoint(path)
    assert recovered.recovered is True
    assert recovered.session.portfolio_safety.kill_switch_active is False
    assert recovered.session.portfolio_safety.current_day_index is None
