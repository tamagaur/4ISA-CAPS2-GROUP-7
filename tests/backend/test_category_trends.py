

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


def test_delmonte_category_absent_month_has_no_revenue_value():
    """QA finding 7 (2026-10-30): a Del Monte category with no row in a reported month is a gap, not 0.0; Unilever's is a real zero."""
    from backend.routers import category_trends as ct

    class _Rows:
        def __init__(self, rows): self.rows = rows
        def mappings(self): return self
        def all(self): return self.rows

    class _Db:
        def execute(self, *_a, **_k):
            return _Rows([{"category": "A", "period": "2023-01", "revenue": 10.0, "positive_rows": 1},
                          {"category": "A", "period": "2023-02", "revenue": 10.0, "positive_rows": 1},
                          {"category": "B", "period": "2023-01", "revenue": 5.0, "positive_rows": 1}])

    for principal, expect in (("delmonte", None), ("unilever", 0.0)):
        cats = {c["category"]: c for c in ct.trends_for(_Db(), principal, ct.REAL)["categories"]}
        point = cats["B"]["history"][1]
        assert point["reason"] and point["revenue"] == expect, principal
