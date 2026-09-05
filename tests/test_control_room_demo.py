import subprocess
import sys

from scripts.run_control_room_demo import main


def test_offline_control_room_demo_is_reproducible(capsys):
    assert main(["--mode", "offline", "--symbols", "BTCUSDT,ETHUSDT"]) == 0
    first = capsys.readouterr().out
    assert main(["--mode", "offline", "--symbols", "BTCUSDT,ETHUSDT"]) == 0
    second = capsys.readouterr().out

    assert first == second
    assert "PAPER_CYCLE_COMPLETE" in first
    assert "PAPER ONLY" in first
    assert "CLOSED CANDLES ONLY | NO LOOK-AHEAD | REAL ORDERS DISABLED" in first
    assert "BTCUSDT" in first and "ETHUSDT" in first
    assert "checkpoint=YES" in first


def test_demo_script_runs_from_repository_root():
    result = subprocess.run(
        [sys.executable, "scripts/run_control_room_demo.py", "--symbols", "BTCUSDT"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "BINANCE SPOT CONTROL ROOM" in result.stdout


def test_live_mode_requires_an_explicit_injected_callback():
    try:
        main(["--mode", "live"])
    except ValueError as exc:
        assert "requires --tool-call and --captured-at" in str(exc)
    else:
        raise AssertionError("expected ValueError")
