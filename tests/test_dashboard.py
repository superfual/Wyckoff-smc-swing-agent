from pathlib import Path


ROOT = Path("dashboard")


def test_dashboard_static_entrypoints_and_safety_copy_exist():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    script = (ROOT / "app.js").read_text(encoding="utf-8")

    assert '<meta name="viewport"' in html
    assert 'href="styles.css"' in html
    assert 'src="app.js"' in html
    assert "PAPER ONLY" in html
    assert "REAL ORDERS" in html and "DISABLED" in html
    assert "No look-ahead" in html
    assert "BTCUSDT" in script and "AAVEUSDT" in script
    assert "BLOCKED" in script and "SCANNED_ONLY" in script
    assert "@media(max-width:580px)" in css


def test_pages_workflow_deploys_only_the_static_dashboard():
    workflow = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "actions/upload-pages-artifact@v3" in workflow
    assert "path: dashboard" in workflow
    assert "actions/deploy-pages@v4" in workflow
