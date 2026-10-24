r"""One definition of a 'YYYY-MM' month query parameter.

The old pattern, r"^\d{4}-(0[1-9]|1[0-2])$", admitted 0000-01. Python has no year 0, so the date arithmetic behind
twelve routes raised ValueError and answered 500 (QA 2026-10-24, finding 5). Years 1900-2099 are accepted: far
wider than the data (2023 on) and the date dimension (to 2028), and nowhere near the date range's edges. Written
without a lookahead, which the regex engine pydantic uses does not support.
"""
PERIOD_PATTERN = r"^(19|20)\d{2}-(0[1-9]|1[0-2])$"
