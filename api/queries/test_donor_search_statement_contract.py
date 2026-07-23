"""Placeholder/parameter arity contract for the donor-search statement builder.

This file exists because of a real ten-day production outage. On 2026-07-13,
commit ``947dc9df3`` changed the shared receipt fragment to
``contribution_insights_transaction_where_sql(max_date_sql="%s")`` so the
person *cycle* path could bind a coverage-end date. Donor search splices the
same fragment but never bound the new parameter, so every ``/donors`` query
raised ``psycopg.ProgrammingError: the query has 5 placeholders but 4
parameters were passed`` and returned HTTP 500.

Nothing caught it: ``api/queries/test_donor_search.py`` is
``pytest.mark.integration`` (deselected by ``make test``) and skips outright
when no Postgres is reachable, and the production smoke gate never visits
``/donors``. So this module is deliberately DB-free and un-marked — it runs in
the default suite on every machine, with no fixtures and no services.

See ``docs/live-state/2026_07_23_public_surface_audit.md``.
"""

from __future__ import annotations

import re

import pytest

from api.queries import campaign_finance as campaign_finance_queries


# psycopg substitutes exactly one parameter per ``%s``. A doubled ``%%`` is an
# escaped literal percent sign — the donor SQL uses those for LIKE wildcards
# (``'%%' || LOWER(%s) || '%%'``) and for the ``LIKE '1%%'`` receipt-type
# prefix — and consumes no parameter. Matching ``%s`` that is NOT preceded by
# another ``%`` therefore reproduces psycopg's own arity rule exactly.
_PLACEHOLDER_PATTERN = re.compile(r"(?<!%)%s")

# One parameter per placeholder, in bind order: the mode-specific search term,
# the CONTRIBUTION_INSIGHTS_MIN_DATE lower bound, then LIMIT and OFFSET.
# Donor search has no upper date bound (see the screen spec at
# docs/reference/screen_specs/donor_lookup.md, which scopes results by
# officeholder currency and itemization, never by a date ceiling), so binding
# four parameters is the correct arity rather than an accident of history.
_EXPECTED_DONOR_SEARCH_PARAMETER_COUNT = 4


@pytest.mark.parametrize(
    ("search_mode", "search_query"),
    [
        ("name", "smith"),
        ("employer", "acme industries"),
        ("zip", "27701"),
    ],
)
def test_donor_search_statement_binds_one_parameter_per_placeholder(
    search_mode: str,
    search_query: str,
) -> None:
    """Every rendered donor-search mode must bind exactly its own placeholders.

    Both assertions matter and neither subsumes the other: the arity assertion
    pins the known answer (four parameters) so a silently-dropped bind cannot
    pass, and the placeholder assertion pins the statement to that answer so a
    newly-spliced ``%s`` from a shared fragment cannot pass either. The
    2026-07-13 regression changed only the second of those.
    """
    statement, parameters = campaign_finance_queries._build_donor_search_statement(
        q=search_query,
        by=search_mode,
        limit=20,
        offset=0,
    )

    assert len(parameters) == _EXPECTED_DONOR_SEARCH_PARAMETER_COUNT
    assert len(_PLACEHOLDER_PATTERN.findall(statement)) == len(parameters)
