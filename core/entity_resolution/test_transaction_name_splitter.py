from __future__ import annotations

from uuid import uuid4

import pytest

from core.entity_resolution.transaction_counterparty_resolver import (
    _UnresolvedTransaction,
    _person_transaction_row,
    _split_first_and_last_name,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, (None, None)),
        ("", (None, None)),
        ("SMITH", ("SMITH", None)),
        ("John Smith", ("John", "Smith")),
        ("SMITH, JOHN", ("SMITH,", "JOHN")),
        ("SMITH, JOHN JR", ("SMITH,", "JR")),
        ("John Smith Jr.", ("John", "Jr.")),
        ("O'BRIEN, MARY", ("O'BRIEN,", "MARY")),
        ("DE LA CRUZ, MARIA", ("DE", "MARIA")),
    ],
)
def test_split_first_and_last_name_characterizes_current_transaction_outputs(
    value: str | None,
    expected: tuple[str | None, str | None],
) -> None:
    assert _split_first_and_last_name(value) == expected


def test_person_transaction_row_preserves_split_fields_and_prefixes() -> None:
    unresolved = _UnresolvedTransaction(
        transaction_id=uuid4(),
        contributor_name_raw="John Quincy Smith",
        contributor_employer=None,
        contributor_occupation=None,
        contributor_city=None,
        contributor_state=None,
        contributor_zip=None,
        raw_fields={},
        transaction_role="donor",
        person_candidate_ids=set(),
        organization_candidate_ids=set(),
    )

    transaction_row = _person_transaction_row(unresolved)

    assert transaction_row["first_name"] == "John"
    assert transaction_row["last_name"] == "Smith"
    assert transaction_row["last_name_prefix5"] == "Smith"
    assert transaction_row["last_name_prefix3"] == "Smi"
