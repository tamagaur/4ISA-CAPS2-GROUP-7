

def test_generated_months_are_labelled_in_preview_history(monkeypatch):
    """Audit 2026-10-23 finding 8: a generated 2021-22 point carried no label of its own."""
    from backend.routers import category_trends as ct

    class _Rows:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows

    class _Db:
        def execute(self, *_a, **_k):
            return _Rows([{"category": "SOAP", "period": p, "revenue": 10.0, "positive_rows": 1}
                          for p in ("2022-12", "2023-01", "2023-02")])

    monkeypatch.setattr(ct, "placeholder_window", lambda db: {"start": "2021-01", "end": "2022-12"})
    history = ct.trends_for(_Db(), "unilever", ct.PREVIEW)["categories"][0]["history"]
    assert [p.get("origin") for p in history] == ["backcast", None, None]
    real = ct.trends_for(_Db(), "unilever", ct.REAL)["categories"][0]["history"]
    assert all("origin" not in p for p in real)
