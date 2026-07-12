from __future__ import annotations

import inspect

import api.queries.campaign_finance as campaign_finance_queries

DONOR_SEARCH_DOCSTRING_FUNCTIONS = (
    "_normalize_donor_search_input",
    "_build_donor_search_statement",
    "_shape_donor_search_results",
    "search_donors",
)


def _docstring_for(function_name: str) -> str:
    docstring = inspect.getdoc(getattr(campaign_finance_queries, function_name))
    assert docstring is not None
    return docstring


def test_donor_search_docstrings_are_closed_out_without_generic_stubs() -> None:
    docstrings = {function_name: _docstring_for(function_name) for function_name in DONOR_SEARCH_DOCSTRING_FUNCTIONS}

    assert len(set(docstrings.values())) == len(docstrings)
