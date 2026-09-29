"""The sidebar's status light and the liveness check it pings.

/health and /status are the same check. The sidebar pings /status because
EasyPrivacy, the tracker list behind Brave Shields, uBlock Origin and AdBlock,
blocks ||onrender.com/health: on 2026-09-29 the light read SYS OFFLINE in
those browsers while every data request worked. Render's own health check
still uses /health, server to server, where no browser list applies."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
SIDEBAR = Path(__file__).resolve().parents[2] / "frontend/src/components/Sidebar.jsx"


def test_health_and_status_answer_without_a_token():
    for path in ("/health", "/status"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json() == {"status": "ok"}


def test_sidebar_pings_status_not_health():
    source = SIDEBAR.read_text(encoding="utf-8")
    pinged = re.findall(r"fetch\(`\$\{API_URL\}(/[^`?]*)", source)
    assert pinged == ["/status"]
