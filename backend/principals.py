"""
backend.principals — one definition of what "filter by principal" means.

Restores the ?principal= query param dropped in 2026-09 (commit c4be61c,
"UNILEVER ONLY"), now that Del Monte is back in scope. Three accepted
values, matching the dashboard's segmented control:

    omitted / 'all'  -> no filter, both principals
    'unilever'       -> Unilever rows only
    'delmonte'       -> Del Monte rows only

Centralised rather than re-implemented per router because the old code
spread 25 hardcoded `principal = 'unilever'` literals across 7 routers;
a single helper means "what does all mean" has exactly one answer, and an
invalid value fails the same way everywhere (400, not a silent empty
result set that reads like "this principal has no data").

IMPORTANT — 'all' is not automatically meaningful. Several metrics cannot
honestly combine the two principals (weeks-of-cover is pesos for Del Monte
but units for Unilever per DEC-03/DEC-10/DEC-13), and those must keep
returning null-with-a-reason under 'all' rather than summing incomparable
figures. This module only builds the SQL predicate; deciding whether a
given metric MAY be combined stays with the caller.
"""
from __future__ import annotations

from fastapi import HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

# The only two principals in the corpus (schema.sql ck_*_principal
# constraints use these exact lowercase spellings).
VALID_PRINCIPALS = ("unilever", "delmonte")

# Shared Query() definition so every router advertises the same param in
# /docs instead of drifting descriptions.
PrincipalQuery = Query(
    None,
    description="Filter to 'unilever' or 'delmonte'. Omit (or pass 'all') for both.",
)


def normalize_principal(principal: str | None) -> str | None:
    """'all'/None/'' -> None (no filter); a valid principal -> itself.

    Case-insensitive so the UI can send 'Unilever' or 'unilever'. Anything
    else raises 400 — an unrecognised principal is a caller bug, and
    silently ignoring it would render a full unfiltered page while the UI
    still showed a specific principal selected.
    """
    if principal is None:
        return None
    value = principal.strip().lower()
    if value in ("", "all"):
        return None
    if value not in VALID_PRINCIPALS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown principal {principal!r}. Expected one of: all, {', '.join(VALID_PRINCIPALS)}.",
        )
    return value


def principal_clause(principal: str | None, column: str) -> tuple[str, dict[str, str]]:
    """Build the SQL fragment + bind params for a principal filter.

    `column` is the fully-qualified column ('ac.principal', 'pd.principal')
    so callers can't accidentally produce an ambiguous reference in a join.
    Returns ('', {}) when no filter applies, so callers can always append
    the fragment unconditionally.

    Parameterised (never interpolated) — `column` comes from the calling
    code, the VALUE always goes through a bind param.
    """
    normalized = normalize_principal(principal)
    if normalized is None:
        return "", {}
    return f" AND {column} = :principal", {"principal": normalized}


def latest_inventory_period(db: Session, principal: str | None) -> str | None:
    """Latest Inventory_Fact_Real._period WITHIN the requested scope.

    Lives here, not in a router, because four routers need it and
    dashboard.py already imports from recommendations.py — a helper in
    dashboard.py would make that a circular import at app start.

    Scoping is load-bearing, not defensive. Measured 2026-09-20: the
    unfiltered MAX resolves to 2026-03, which is Unilever's own max, so
    Unilever reads correctly by coincidence while Del Monte (whose own
    max is 2025-12) matches zero rows and reports NULL stock for all
    15,308 of its SKUs.
    """
    scope_sql, scope_params = principal_clause(principal, "principal")
    sql = "SELECT MAX(_period) AS p FROM Inventory_Fact_Real WHERE 1=1" + scope_sql
    row = db.execute(text(sql), scope_params).mappings().first()
    return row["p"] if row else None


def latest_abc_period(
    db: Session, principal: str | None, at_or_before: str | None = None
) -> str | None:
    """Latest ABC_Classification.classification_period within scope.

    method='single' is REQUIRED (migration 0017): a 't3m' run is live
    alongside 'single', so an unpinned MAX can resolve to a period only
    t3m produced, which then reads back zero 'single' rows — and an
    unpinned join fans out two tier rows per product_key.

    `at_or_before` supports the dashboard's date picker, whose applied end
    month routinely runs ahead of the latest ABC run; without it that
    common case dead-ends instead of falling back to the nearest real run.
    """
    scope_sql, scope_params = principal_clause(principal, "principal")
    sql = (
        "SELECT MAX(classification_period) AS p FROM ABC_Classification "
        "WHERE method = 'single'"
    )
    params: dict = {**scope_params}
    if at_or_before is not None:
        sql += " AND classification_period <= :at_or_before"
        params["at_or_before"] = at_or_before
    sql += scope_sql
    row = db.execute(text(sql), params).mappings().first()
    return row["p"] if row else None
