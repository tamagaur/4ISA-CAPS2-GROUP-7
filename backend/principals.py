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
