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


def test_health_and_status_answer_without_a_token(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    for path in ("/health", "/status"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json() == {"status": "ok", "commit": "unknown"}


def test_health_names_the_commit_render_built(monkeypatch):
    """So the deployed API's commit can be compared with the branch it is said to deploy (2026-11-17)."""
    monkeypatch.setenv("RENDER_GIT_COMMIT", "c6fc80a1234567890abcdef")
    assert client.get("/health").json() == {"status": "ok", "commit": "c6fc80a12345"}


def test_sidebar_pings_status_not_health():
    source = SIDEBAR.read_text(encoding="utf-8")
    pinged = re.findall(r"fetch\(`\$\{API_URL\}(/[^`?]*)", source)
    assert pinged == ["/status"]


def test_health_and_status_never_open_a_database_session():
    """The login page pings this to wake a sleeping instance, so it must answer on its own: no auth
    and no database. A get_db that raises proves neither route reaches for one."""
    from backend.deps import get_db

    def _no_database():
        raise AssertionError("the health check opened a database session")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = _no_database
    try:
        for path in ("/health", "/status"):
            assert client.get(path).status_code == 200, path
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_status_says_when_the_database_does_not_answer_only_when_asked(monkeypatch):
    """The sidebar's light asks with ?db=1: up with the database down must not read as online (2026-11-18).
    Still HTTP 200, so the login page's wake check is unaffected; without the parameter no database is touched."""
    import backend.main as main

    monkeypatch.setattr(main, "_database_answers", lambda: False)
    assert client.get("/status?db=1").json()["database"] == "unreachable"
    assert client.get("/status?db=1").status_code == 200
    assert "database" not in client.get("/status").json()
    monkeypatch.setattr(main, "_database_answers", lambda: True)
    assert client.get("/status?db=1").json()["database"] == "ok"


def test_the_database_probe_is_remembered_and_never_raises(monkeypatch):
    """The route is public: one probe per TTL, however many callers, and a failure is an answer, not a 500."""
    import backend.main as main
    import backend.deps as deps

    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(deps, "_get_read_engine", boom)
    main._db_probe.update(at=float("-inf"), ok=True)
    assert main._database_answers() is False
    assert main._database_answers() is False      # remembered: no third and fourth try
    assert len(calls) == 2                        # one probe = two tries
    main._db_probe.update(at=float("-inf"), ok=True)


def test_the_probe_is_stamped_before_it_runs_so_a_hung_database_starts_one_probe(monkeypatch):
    """A caller arriving while a probe is in flight reads the last answer instead of starting its own."""
    import backend.main as main
    import backend.deps as deps

    seen = []

    def slow_engine():
        seen.append(main._db_probe["at"])          # the stamp is already this probe's, not the old one
        raise RuntimeError("hung")

    monkeypatch.setattr(deps, "_get_read_engine", slow_engine)
    main._db_probe.update(at=float("-inf"), ok=True)
    main._database_answers()
    assert seen and seen[0] != float("-inf")
    main._db_probe.update(at=float("-inf"), ok=True)


def test_one_dropped_pooled_connection_is_not_unreachable(monkeypatch):
    import backend.main as main
    import backend.deps as deps

    tries = []

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): return None

    class _Engine:
        def connect(self):
            tries.append(1)
            if len(tries) == 1:
                raise RuntimeError("server closed the connection unexpectedly")
            return _Conn()

    monkeypatch.setattr(deps, "_get_read_engine", lambda: _Engine())
    main._db_probe.update(at=float("-inf"), ok=False)
    assert main._database_answers() is True and len(tries) == 2
    main._db_probe.update(at=float("-inf"), ok=True)


def test_sidebar_asks_for_the_database_and_shows_it():
    source = SIDEBAR.read_text(encoding="utf-8")
    assert "/status?db=1" in source and "DATABASE OFFLINE" in source
