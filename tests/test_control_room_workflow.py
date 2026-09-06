from pathlib import Path


WORKFLOW = Path(".github/workflows/control-room-demo.yml")


def test_control_room_workflow_exposes_manual_dispatch_and_safe_demo():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Control-Room Demo" in text
    assert "workflow_dispatch:" in text
    assert "python scripts/run_control_room_demo.py" in text
    assert "Mode: PAPER ONLY" in text
    assert "CLOSED CANDLES ONLY | NO LOOK-AHEAD | REAL ORDERS DISABLED" in text
    assert "actions/upload-artifact@v4" in text
    assert "permissions:\n  contents: read" in text


def test_control_room_workflow_contains_no_live_exchange_surface():
    text = WORKFLOW.read_text(encoding="utf-8").lower()

    forbidden = ("api_key", "api_secret", "create_order", "place_order", "futures_order")
    assert all(token not in text for token in forbidden)
