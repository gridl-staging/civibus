from __future__ import annotations

import ast
from decimal import Decimal
import inspect
import textwrap
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.pq import TransactionStatus

from core.db import (
    insert_data_source,
    insert_entity_source,
    insert_organization,
    insert_person,
    insert_source_record,
)
from core.entity_resolution import transaction_counterparty_resolver as resolver_module
from core.entity_resolution.extract import (
    _donor_identity_id,
    _donor_identity_schedule_a_predicate_sql,
)
from core.entity_resolution.l8_regression import _normalize_address
from core.entity_resolution.persist import persist_auto_merge_clusters
from core.types.python.models import (
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from core.entity_resolution.transaction_counterparty_resolver import (
    resolve_nc_transaction_counterparties,
)
from domains.campaign_finance.ingest.filing_loader import update_transaction_contributor_identity_ids


pytestmark = pytest.mark.integration

_TEST_DATA_SOURCE_PREFIX = "Test NC Counterparty Resolver Source "
_TEST_SOURCE_RECORD_PREFIX = "test-nc-counterparty-resolver-source-record-"
_TEST_TRANSACTION_PREFIX = "test-nc-counterparty-resolver-transaction-"
_TEST_ADDRESS_PREFIX = "TEST NC COUNTERPARTY RESOLVER ADDRESS "
_TEST_COMMITTEE_PREFIX = "Test NC Counterparty Resolver Committee "
_TEST_FILING_PREFIX = "test-nc-counterparty-resolver-filing-"
_TEST_DONOR_WRITEBACK_PREFIX = "Test Donor Writeback "
_TEST_SUB_ID_BASE = 970_000_000_000_000_000
_NAME_PROJECTION_FIELDS = (
    "first_name",
    "last_name",
    "last_name_prefix5",
    "last_name_prefix3",
)


_ExpressionBindings = dict[str, list[ast.expr]]


def _expression_bindings(tree: ast.AST) -> _ExpressionBindings:
    bindings: _ExpressionBindings = {}
    for assignment in (node for node in ast.walk(tree) if isinstance(node, ast.Assign)):
        for target in assignment.targets:
            if isinstance(target, ast.Name):
                bindings.setdefault(target.id, []).append(assignment.value)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for element in target.elts:
                    if isinstance(element, ast.Name):
                        bindings.setdefault(element.id, []).append(assignment.value)
    return bindings


def _call_path(expression: ast.expr) -> str:
    if isinstance(expression, ast.Call):
        if isinstance(expression.func, ast.Name):
            return expression.func.id
        if isinstance(expression.func, ast.Attribute):
            return expression.func.attr
        return "<dynamic call>"
    return f"<not a call: {type(expression).__name__}>"


def _projection_owner_calls(
    expression: ast.expr,
    bindings: _ExpressionBindings,
    seen_names: frozenset[str] = frozenset(),
) -> list[ast.Call]:
    if isinstance(expression, ast.Call):
        return [expression]
    if isinstance(expression, ast.Name):
        if expression.id in seen_names:
            return []
        calls: list[ast.Call] = []
        for bound_expression in bindings.get(expression.id, []):
            calls.extend(
                _projection_owner_calls(
                    bound_expression,
                    bindings,
                    seen_names | {expression.id},
                )
            )
        return calls
    if isinstance(expression, (ast.Attribute, ast.Subscript)):
        return _projection_owner_calls(expression.value, bindings, seen_names)
    return []


def _constant_name(expression: ast.expr, bindings: _ExpressionBindings) -> str | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    if isinstance(expression, ast.Name) and expression.id == "_NC_NAME_KEY":
        return "Name"
    if isinstance(expression, ast.Name):
        bound_expressions = bindings.get(expression.id, [])
        if len(bound_expressions) == 1:
            return _constant_name(bound_expressions[0], bindings)
    return None


def _uses_raw_transaction_name_source(
    expression: ast.expr,
    bindings: _ExpressionBindings,
    seen_names: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(expression, ast.Name):
        if expression.id in seen_names:
            return False
        bound_expressions = bindings.get(expression.id)
        if bound_expressions is None:
            return expression.id == "_NC_NAME_KEY"
        return bool(bound_expressions) and all(
            _uses_raw_transaction_name_source(
                bound_expression,
                bindings,
                seen_names | {expression.id},
            )
            for bound_expression in bound_expressions
        )
    if isinstance(expression, ast.BoolOp) and isinstance(expression.op, ast.Or):
        return all(_uses_raw_transaction_name_source(value, bindings, seen_names) for value in expression.values)
    if isinstance(expression, ast.Attribute):
        return (
            isinstance(expression.value, ast.Name)
            and expression.value.id == "unresolved"
            and expression.attr == "contributor_name_raw"
        )
    if not isinstance(expression, ast.Call):
        return False
    if _call_path(expression) == "_normalize_text" and len(expression.args) == 1 and not expression.keywords:
        return _uses_raw_transaction_name_source(expression.args[0], bindings, seen_names)
    if (
        isinstance(expression.func, ast.Attribute)
        and expression.func.attr == "get"
        and isinstance(expression.func.value, ast.Attribute)
        and expression.func.value.attr == "raw_fields"
        and isinstance(expression.func.value.value, ast.Name)
        and expression.func.value.value.id == "unresolved"
        and len(expression.args) == 1
        and _constant_name(expression.args[0], bindings) == "Name"
    ):
        return True
    return False


def _returned_fields(tree: ast.AST) -> dict[str, ast.expr]:
    return_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
    assert len(return_nodes) == 1
    assert isinstance(return_nodes[0].value, ast.Dict)
    return {
        key.value: value
        for key, value in zip(return_nodes[0].value.keys, return_nodes[0].value.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _is_first_last_only_parse_name_call(call: ast.Call) -> bool:
    if _call_path(call) != "parse_name":
        return False
    return any(
        keyword.arg == "first_last_only" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        for keyword in call.keywords
    )


def _assert_transaction_counterparty_name_projection_is_owned(source: str) -> None:
    person_row_tree = ast.parse(textwrap.dedent(source))
    bindings = _expression_bindings(person_row_tree)
    returned_fields = _returned_fields(person_row_tree)
    projection_owner_calls = {
        field: _projection_owner_calls(returned_fields[field], bindings) for field in ("first_name", "last_name")
    }

    assert len(projection_owner_calls["first_name"]) == 1
    assert len(projection_owner_calls["last_name"]) == 1
    first_owner = projection_owner_calls["first_name"][0]
    last_owner = projection_owner_calls["last_name"][0]
    assert first_owner is last_owner
    assert _is_first_last_only_parse_name_call(first_owner)
    assert len(first_owner.args) == 1
    assert _uses_raw_transaction_name_source(first_owner.args[0], bindings)


class TestDonorTransactionNameProjection:
    @pytest.fixture(autouse=True)
    def _cleanup_test_rows(self) -> None:
        # These structural and row-projection contracts are pure functions. A
        # class-local autouse fixture keeps the module's DB cleanup fixture from
        # turning their red evidence into a PostgreSQL availability skip.
        return

    @pytest.mark.parametrize(
        ("raw_name", "expected_projection"),
        [
            ("SMITH", (None, "SMITH", "SMITH", "SMI")),
            ("John Smith", ("JOHN", "SMITH", "SMITH", "SMI")),
            ("SMITH, JOHN", ("JOHN", "SMITH", "SMITH", "SMI")),
            ("SMITH, JOHN JR", ("JOHN", "SMITH", "SMITH", "SMI")),
            ("O'BRIEN, MARY", ("MARY", "O'BRIEN", "O'BRI", "O'B")),
            ("DE LA CRUZ, MARIA", ("MARIA", "DE LA CRUZ", "DE LA", "DE ")),
            ("John Quincy Smith", ("JOHN", "SMITH", "SMITH", "SMI")),
        ],
    )
    def test_person_transaction_row_uses_canonical_name_projection(
        self,
        raw_name: str,
        expected_projection: tuple[str | None, str, str, str],
    ) -> None:
        unresolved = resolver_module._UnresolvedTransaction(
            transaction_id=uuid4(),
            contributor_name_raw=raw_name,
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

        transaction_row = resolver_module._person_transaction_row(unresolved)

        actual_projection = tuple(transaction_row[field] for field in _NAME_PROJECTION_FIELDS)
        assert actual_projection == expected_projection

    def test_transaction_counterparty_seam_has_no_third_name_splitter(self) -> None:
        _assert_transaction_counterparty_name_projection_is_owned(
            inspect.getsource(resolver_module._person_transaction_row)
        )

    def test_transaction_counterparty_seam_rejects_upstream_name_helper(self) -> None:
        upstream_helper_source = """
        def _person_transaction_row(unresolved):
            canonical_name = _normalize_text(unresolved.contributor_name_raw) or _normalize_text(
                unresolved.raw_fields.get(_NC_NAME_KEY)
            )
            reparsed_name = _compact_person_tokens(canonical_name)
            parsed_name = parse_name(reparsed_name, first_last_only=True)
            return {
                "first_name": parsed_name.first,
                "last_name": parsed_name.last,
            }
        """

        with pytest.raises(AssertionError):
            _assert_transaction_counterparty_name_projection_is_owned(upstream_helper_source)

    def test_transaction_counterparty_seam_rejects_missing_compatibility_option(self) -> None:
        missing_compatibility_source = """
        def _person_transaction_row(unresolved):
            canonical_name = _normalize_text(unresolved.contributor_name_raw) or _normalize_text(
                unresolved.raw_fields.get(_NC_NAME_KEY)
            )
            parsed_name = parse_name(canonical_name)
            return {
                "first_name": parsed_name.first,
                "last_name": parsed_name.last,
            }
        """

        with pytest.raises(AssertionError):
            _assert_transaction_counterparty_name_projection_is_owned(missing_compatibility_source)


@pytest.fixture(autouse=True)
def _cleanup_test_rows(db_conn: psycopg.Connection) -> None:
    yield
    if db_conn.info.transaction_status == TransactionStatus.INERROR:
        db_conn.rollback()

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM cf.transaction
            WHERE transaction_identifier LIKE %s
            """,
            (f"{_TEST_TRANSACTION_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.cluster_member
            WHERE entity_type = 'donor_identity'
              AND entity_id IN (
                SELECT id
                FROM core.donor_identity
                WHERE canonical_name LIKE %s
              )
            """,
            (f"{_TEST_DONOR_WRITEBACK_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.entity_cluster
            WHERE entity_type = 'donor_identity'
              AND canonical_entity_id IN (
                SELECT id
                FROM core.donor_identity
                WHERE canonical_name LIKE %s
              )
            """,
            (f"{_TEST_DONOR_WRITEBACK_PREFIX}%",),
        )
        cursor.execute(
            "DELETE FROM core.donor_identity WHERE canonical_name LIKE %s",
            (f"{_TEST_DONOR_WRITEBACK_PREFIX}%",),
        )
        cursor.execute(
            "DELETE FROM core.person WHERE canonical_name LIKE %s",
            (f"{_TEST_DONOR_WRITEBACK_PREFIX}%",),
        )
        cursor.execute(
            "DELETE FROM core.organization WHERE canonical_name LIKE %s",
            (f"{_TEST_DONOR_WRITEBACK_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.entity_address
            WHERE entity_type = 'person'
              AND entity_id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'person'
              )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.entity_address
            WHERE entity_type = 'organization'
              AND entity_id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'organization'
              )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.person
            WHERE id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'person'
            )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.organization
            WHERE id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'organization'
            )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.entity_source
            WHERE source_record_id IN (
                SELECT id
                FROM core.source_record
                WHERE source_record_key LIKE %s
            )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute("DELETE FROM cf.filing WHERE filing_fec_id LIKE %s", (f"{_TEST_FILING_PREFIX}%",))
        cursor.execute("DELETE FROM cf.committee WHERE name LIKE %s", (f"{_TEST_COMMITTEE_PREFIX}%",))
        cursor.execute(
            "DELETE FROM core.address WHERE normalized_address LIKE %s",
            (f"{_TEST_ADDRESS_PREFIX}%",),
        )
        cursor.execute(
            "DELETE FROM core.source_record WHERE source_record_key LIKE %s",
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute("DELETE FROM core.data_source WHERE name LIKE %s", (f"{_TEST_DATA_SOURCE_PREFIX}%",))


def _insert_test_committee(conn: psycopg.Connection, label: str) -> UUID:
    committee_fec_id = f"C{uuid4().int % 100_000_000:08d}"
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (fec_committee_id, name)
            VALUES (%s, %s)
            RETURNING id
            """,
            (committee_fec_id, f"{_TEST_COMMITTEE_PREFIX}{label}"),
        )
        return cursor.fetchone()[0]


def _donor_identity_tuple(
    *,
    contributor_name_raw: str,
    contributor_employer: str = "",
    contributor_occupation: str = "",
    contributor_city: str = "Raleigh",
    contributor_state: str = "NC",
    contributor_zip: str = "27601",
) -> dict[str, str]:
    return {
        "contributor_name_raw": contributor_name_raw,
        "contributor_employer": contributor_employer,
        "contributor_occupation": contributor_occupation,
        "contributor_city": contributor_city,
        "contributor_state": contributor_state,
        "contributor_zip": contributor_zip,
    }


def _insert_donor_writeback_person(
    conn: psycopg.Connection,
    canonical_name: str,
) -> UUID:
    _, last_name = canonical_name.rsplit(" ", 1)
    return insert_person(
        conn,
        Person(
            canonical_name=canonical_name,
            first_name=canonical_name.removeprefix(_TEST_DONOR_WRITEBACK_PREFIX).rsplit(" ", 1)[0],
            last_name=last_name,
        ),
    )


def _insert_donor_identity(
    conn: psycopg.Connection,
    donor_tuple: dict[str, str],
    *,
    person_id: UUID | None,
    create_cluster: bool = True,
) -> UUID:
    donor_id = _donor_identity_id(donor_tuple)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.donor_identity (
                id,
                canonical_name,
                contributor_name_raw,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                zip5,
                transaction_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """,
            (
                donor_id,
                donor_tuple["contributor_name_raw"],
                donor_tuple["contributor_name_raw"],
                donor_tuple["contributor_employer"],
                donor_tuple["contributor_occupation"],
                donor_tuple["contributor_city"],
                donor_tuple["contributor_state"],
                donor_tuple["contributor_zip"],
                donor_tuple["contributor_zip"][:5],
            ),
        )
        if not create_cluster:
            return donor_id

        cursor.execute(
            """
            INSERT INTO core.entity_cluster (
                entity_type,
                canonical_entity_id,
                cluster_confidence,
                member_count
            )
            VALUES ('donor_identity', %s, 0.99, 1)
            RETURNING id
            """,
            (donor_id,),
        )
        cluster_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO core.cluster_member (cluster_id, entity_type, entity_id, is_canonical)
            VALUES (%s, 'donor_identity', %s, TRUE)
            """,
            (cluster_id, donor_id),
        )
        cursor.execute(
            """
            UPDATE core.donor_identity
            SET er_cluster_id = %s,
                er_confidence = 0.99
            WHERE id = %s
            """,
            (cluster_id, donor_id),
        )
        if person_id is not None:
            cursor.execute(
                """
                INSERT INTO core.donor_cluster_person (cluster_id, person_id)
                VALUES (%s, %s)
                """,
                (cluster_id, person_id),
            )
    return donor_id


def _insert_donor_writeback_transaction(
    conn: psycopg.Connection,
    *,
    label: str,
    committee_id: UUID,
    filing_id: UUID,
    donor_tuple: dict[str, str],
) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.transaction (
                filing_id,
                committee_id,
                transaction_type,
                transaction_identifier,
                sub_id,
                amount,
                contributor_name_raw,
                contributor_entity_type,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                amendment_indicator
            )
            VALUES (%s, %s, '15', %s, %s, %s, %s, 'IND', %s, %s, %s, %s, %s, 'N')
            RETURNING id
            """,
            (
                filing_id,
                committee_id,
                f"{_TEST_TRANSACTION_PREFIX}{label}",
                _TEST_SUB_ID_BASE + int(label[-3:]),
                Decimal("100.00"),
                donor_tuple["contributor_name_raw"],
                donor_tuple["contributor_employer"],
                donor_tuple["contributor_occupation"],
                donor_tuple["contributor_city"],
                donor_tuple["contributor_state"],
                donor_tuple["contributor_zip"],
            ),
        )
        return cursor.fetchone()[0]


def _seed_donor_writeback_fixture(
    conn: psycopg.Connection,
) -> tuple[dict[str, UUID], UUID]:
    committee_id = _insert_test_committee(conn, "donor-writeback")
    filing_id = _insert_test_filing(conn, committee_id, "donor-writeback")
    resolved_person_id = _insert_donor_writeback_person(conn, f"{_TEST_DONOR_WRITEBACK_PREFIX}Alice Smith")
    resolved_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Alice Smith",
        contributor_employer="ACME CORP",
        contributor_occupation="ENGINEER",
        contributor_city="Raleigh",
        contributor_zip="276010001",
    )
    invalid_cluster_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Invalid Cluster",
        contributor_employer="VOID LLC",
        contributor_occupation="CONSULTANT",
        contributor_city="Raleigh",
        contributor_zip="276020002",
    )
    unresolved_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Unresolved Donor",
        contributor_employer="UNKNOWN",
        contributor_occupation="RETIRED",
        contributor_city="Raleigh",
        contributor_zip="276030003",
    )

    _insert_donor_identity(conn, resolved_tuple, person_id=resolved_person_id)
    _insert_donor_identity(conn, invalid_cluster_tuple, person_id=None)

    transaction_ids = {
        "resolved_a": _insert_donor_writeback_transaction(
            conn,
            label="401",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=resolved_tuple,
        ),
        "resolved_b": _insert_donor_writeback_transaction(
            conn,
            label="402",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=resolved_tuple,
        ),
        "invalid_cluster": _insert_donor_writeback_transaction(
            conn,
            label="403",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=invalid_cluster_tuple,
        ),
        "unresolved": _insert_donor_writeback_transaction(
            conn,
            label="404",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=unresolved_tuple,
        ),
    }
    return transaction_ids, resolved_person_id


def _donor_writeback_rows(
    conn: psycopg.Connection,
    transaction_ids: dict[str, UUID],
) -> dict[str, dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                id,
                contributor_person_id,
                contributor_organization_id,
                num_nonnulls(contributor_person_id, contributor_organization_id) AS identity_count
            FROM cf.transaction
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (list(transaction_ids.values()),),
        )
        rows_by_id = {row["id"]: row for row in cursor.fetchall()}
    return {label: rows_by_id[transaction_id] for label, transaction_id in transaction_ids.items()}


def _scope_donor_writeback_resolver_to_transactions(
    monkeypatch: pytest.MonkeyPatch,
    transaction_ids: dict[str, UUID] | list[UUID],
) -> None:
    selected_transaction_ids = list(transaction_ids.values()) if isinstance(transaction_ids, dict) else transaction_ids
    schedule_a_predicate = _donor_identity_schedule_a_predicate_sql(table_alias="t")

    def _fixture_rows(conn: psycopg.Connection) -> list[dict[str, object]]:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT
                    t.id,
                    t.contributor_organization_id,
                    t.contributor_name_raw,
                    COALESCE(t.contributor_employer, '') AS contributor_employer,
                    COALESCE(t.contributor_occupation, '') AS contributor_occupation,
                    COALESCE(t.contributor_city, '') AS contributor_city,
                    COALESCE(t.contributor_state, '') AS contributor_state,
                    COALESCE(t.contributor_zip, '') AS contributor_zip
                FROM cf.transaction t
                JOIN core.donor_identity di
                  ON di.contributor_name_raw = t.contributor_name_raw
                 AND COALESCE(di.contributor_employer, '') = COALESCE(t.contributor_employer, '')
                 AND COALESCE(di.contributor_occupation, '') = COALESCE(t.contributor_occupation, '')
                 AND COALESCE(di.contributor_city, '') = COALESCE(t.contributor_city, '')
                 AND COALESCE(di.contributor_state, '') = COALESCE(t.contributor_state, '')
                 AND COALESCE(di.contributor_zip, '') = COALESCE(t.contributor_zip, '')
                WHERE t.id = ANY(%s)
                  AND {schedule_a_predicate}
                ORDER BY
                    t.contributor_name_raw,
                    contributor_employer,
                    contributor_occupation,
                    contributor_city,
                    contributor_state,
                    contributor_zip,
                    t.id
                """,
                (selected_transaction_ids,),
            )
            return list(cursor.fetchall())

    monkeypatch.setattr(
        resolver_module,
        "_donor_identity_transaction_rows_for_existing_identities",
        _fixture_rows,
    )


def _donor_person_mapping_by_identity_id(
    conn: psycopg.Connection,
    donor_identity_ids: list[UUID],
) -> dict[UUID, UUID]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT cm.entity_id, dcp.person_id
            FROM core.cluster_member cm
            JOIN core.donor_cluster_person dcp ON dcp.cluster_id = cm.cluster_id
            WHERE cm.entity_type = 'donor_identity'
              AND cm.entity_id = ANY(%s)
              AND cm.split_at IS NULL
            ORDER BY cm.entity_id
            """,
            (donor_identity_ids,),
        )
        return {row["entity_id"]: row["person_id"] for row in cursor.fetchall()}


def _insert_test_filing(conn: psycopg.Connection, committee_id: UUID, label: str) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.filing (filing_fec_id, committee_id, amendment_indicator)
            VALUES (%s, %s, 'N')
            RETURNING id
            """,
            (f"{_TEST_FILING_PREFIX}{label}", committee_id),
        )
        return cursor.fetchone()[0]


def _insert_test_source_record(
    conn: psycopg.Connection,
    *,
    label: str,
    raw_fields: dict[str, object],
    jurisdiction: str = "state/NC",
) -> UUID:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name=f"{_TEST_DATA_SOURCE_PREFIX}{label}",
        source_url="https://example.test/nc-counterparty-resolver",
    )
    insert_data_source(conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"{_TEST_SOURCE_RECORD_PREFIX}{label}",
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    insert_source_record(conn, source_record)
    return source_record.id


def _build_nc_transaction_raw_fields(
    *,
    name: str,
    street_line_1: str,
    city: str,
    state: str,
    zip_code: str,
    occupation: str = "Legislator",
    employer_or_business: str = "NC House",
    transaction_type: str | None = None,
) -> dict[str, str]:
    prefixed_street_line_1 = f"{_TEST_ADDRESS_PREFIX}{street_line_1}"
    raw_fields = {
        "Name": name,
        "Street Line 1": prefixed_street_line_1,
        "Street Line 2": "",
        "City": city,
        "State": state,
        "Zip Code": zip_code,
        "Profession/Job Title": occupation,
        "Employer's Name/Specific Field": employer_or_business,
    }
    if transaction_type is not None:
        raw_fields["Transction Type"] = transaction_type
    return raw_fields


def _insert_address_and_link(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    entity_id: UUID,
    normalized_address: str,
    state: str,
    zip5: str,
) -> None:
    normalized_value = _normalize_address(normalized_address)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.address (id, raw_address, normalized_address, street_number, state, zip5)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (normalized_address) WHERE normalized_address IS NOT NULL
            DO UPDATE SET
                raw_address = EXCLUDED.raw_address,
                street_number = EXCLUDED.street_number,
                state = EXCLUDED.state,
                zip5 = EXCLUDED.zip5
            RETURNING id
            """,
            (uuid4(), normalized_value, normalized_value, "123", state, zip5),
        )
        address_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO core.entity_address (entity_type, entity_id, address_id, address_role, valid_period)
            VALUES (%s, %s, %s, 'mailing', daterange('2024-01-01', NULL, '[)'))
            """,
            (entity_type, entity_id, address_id),
        )


def _insert_person_candidate(
    conn: psycopg.Connection,
    *,
    label: str,
    canonical_name: str,
    identifier_key: str,
    normalized_address: str,
    zip5: str,
) -> UUID:
    first_name, last_name = canonical_name.split(" ", 1)
    person_id = insert_person(
        conn,
        Person(
            canonical_name=canonical_name,
            first_name=first_name,
            last_name=last_name,
            identifiers={
                "voter_reg_id": identifier_key.split(":", 1)[1],
                "employer": "NC House",
                "occupation": "Legislator",
            },
        ),
    )
    _insert_address_and_link(
        conn,
        entity_type="person",
        entity_id=person_id,
        normalized_address=f"{_TEST_ADDRESS_PREFIX}{normalized_address}",
        state="NC",
        zip5=zip5,
    )
    return person_id


def _insert_organization_candidate(
    conn: psycopg.Connection,
    *,
    canonical_name: str,
    ein: str,
    normalized_address: str,
    zip5: str,
) -> UUID:
    organization_id = insert_organization(
        conn,
        Organization(
            canonical_name=canonical_name,
            registered_state="NC",
            identifiers={"ein": ein},
        ),
    )
    _insert_address_and_link(
        conn,
        entity_type="organization",
        entity_id=organization_id,
        normalized_address=f"{_TEST_ADDRESS_PREFIX}{normalized_address}",
        state="NC",
        zip5=zip5,
    )
    return organization_id


def _insert_transaction(
    conn: psycopg.Connection,
    *,
    label: str,
    source_record_id: UUID,
    contributor_name_raw: str,
    contributor_state: str,
    contributor_zip: str,
    contributor_city: str = "Raleigh",
    contributor_employer: str = "NC House",
    contributor_occupation: str = "Legislator",
    transaction_type: str = "15",
) -> UUID:
    committee_id = _insert_test_committee(conn, label)
    filing_id = _insert_test_filing(conn, committee_id, label)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.transaction (
                filing_id,
                committee_id,
                transaction_type,
                transaction_identifier,
                sub_id,
                amount,
                contributor_name_raw,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                amendment_indicator,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'N', %s)
            RETURNING id
            """,
            (
                filing_id,
                committee_id,
                transaction_type,
                f"{_TEST_TRANSACTION_PREFIX}{label}",
                _TEST_SUB_ID_BASE + int(label[-3:]),
                Decimal("100.00"),
                contributor_name_raw,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                source_record_id,
            ),
        )
        return cursor.fetchone()[0]


def _select_transaction_identity_snapshot(
    conn: psycopg.Connection,
    transaction_ids: list[UUID],
) -> list[tuple[UUID, UUID | None, UUID | None, object]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, contributor_person_id, contributor_organization_id, updated_at
            FROM cf.transaction
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (transaction_ids,),
        )
        return list(cursor.fetchall())


def _seed_resolver_fixture(
    db_conn: psycopg.Connection,
) -> tuple[dict[str, UUID], dict[str, UUID]]:
    donor_source_record_id = _insert_test_source_record(
        db_conn,
        label="donor-julia-howard",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Julia Howard",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27601",
            transaction_type="Individual",
        ),
    )
    donor_person_id = _insert_person_candidate(
        db_conn,
        label="donor-match",
        canonical_name="Julia Howard",
        identifier_key="voter_reg_id:VR-JULIA-HOWARD",
        normalized_address="123 Main St Raleigh NC 27601",
        zip5="27601",
    )
    insert_entity_source(db_conn, "person", donor_person_id, donor_source_record_id, "donor")
    donor_transaction_id = _insert_transaction(
        db_conn,
        label="101",
        source_record_id=donor_source_record_id,
        contributor_name_raw="Julia Howard",
        contributor_state="NC",
        contributor_zip="27601",
    )

    vendor_source_record_id = _insert_test_source_record(
        db_conn,
        label="vendor-adams",
        raw_fields=_build_nc_transaction_raw_fields(
            name="ADAMS FOR NC HOUSE",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27602",
            occupation="Business",
            employer_or_business="Campaign Vendor",
            transaction_type="Business/Group/Org",
        ),
    )
    vendor_org_id = _insert_organization_candidate(
        db_conn,
        canonical_name="ADAMS FOR NC HOUSE",
        ein="12-3456789",
        normalized_address="123 Main St Raleigh NC 27602",
        zip5="27602",
    )
    insert_entity_source(db_conn, "organization", vendor_org_id, vendor_source_record_id, "vendor")
    vendor_transaction_id = _insert_transaction(
        db_conn,
        label="102",
        source_record_id=vendor_source_record_id,
        contributor_name_raw="ADAMS FOR NC HOUSE",
        contributor_state="NC",
        contributor_zip="27602",
    )

    ambiguity_source_record_id = _insert_test_source_record(
        db_conn,
        label="ambiguous-setzer",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Mitchell Setzer",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27603",
            transaction_type="Individual",
        ),
    )
    ambiguous_person_a = _insert_person_candidate(
        db_conn,
        label="ambiguous-a",
        canonical_name="Mitchell Setzer",
        identifier_key="voter_reg_id:VR-SETZER",
        normalized_address="123 Main St Raleigh NC 27603",
        zip5="27603",
    )
    ambiguous_person_b = _insert_person_candidate(
        db_conn,
        label="ambiguous-b",
        canonical_name="Mitchell Setzer",
        identifier_key="voter_reg_id:VR-SETZER",
        normalized_address="123 Main St Raleigh NC 27603",
        zip5="27603",
    )
    insert_entity_source(db_conn, "person", ambiguous_person_a, ambiguity_source_record_id, "donor")
    insert_entity_source(db_conn, "person", ambiguous_person_b, ambiguity_source_record_id, "donor")
    ambiguity_transaction_id = _insert_transaction(
        db_conn,
        label="103",
        source_record_id=ambiguity_source_record_id,
        contributor_name_raw="Mitchell Setzer",
        contributor_state="NC",
        contributor_zip="27603",
    )

    return (
        {
            "donor_transaction_id": donor_transaction_id,
            "vendor_transaction_id": vendor_transaction_id,
            "ambiguity_transaction_id": ambiguity_transaction_id,
        },
        {
            "donor_person_id": donor_person_id,
            "vendor_org_id": vendor_org_id,
        },
    )


def test_resolver_links_known_donor_and_vendor_and_skips_ambiguous_match(
    db_conn: psycopg.Connection,
) -> None:
    transaction_ids, expected_ids = _seed_resolver_fixture(db_conn)

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary == {
        "candidate_transactions": 3,
        "mutated_rows": 2,
        "matched_person_rows": 1,
        "matched_organization_rows": 1,
        "skipped_rows": 1,
        "ambiguous_rows": 1,
        "dual_match_rows": 0,
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (list(transaction_ids.values()),),
        )
        rows = {row["id"]: row for row in cursor.fetchall()}

    donor_row = rows[transaction_ids["donor_transaction_id"]]
    vendor_row = rows[transaction_ids["vendor_transaction_id"]]
    ambiguity_row = rows[transaction_ids["ambiguity_transaction_id"]]
    assert donor_row["contributor_person_id"] == expected_ids["donor_person_id"]
    assert donor_row["contributor_organization_id"] is None
    assert vendor_row["contributor_person_id"] is None
    assert vendor_row["contributor_organization_id"] == expected_ids["vendor_org_id"]
    assert ambiguity_row["contributor_person_id"] is None
    assert ambiguity_row["contributor_organization_id"] is None


def test_donor_writeback_links_resolved_cluster_transactions_and_preserves_nulls(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction_ids, resolved_person_id = _seed_donor_writeback_fixture(db_conn)
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, transaction_ids)

    summary = resolver_module.resolve_donor_identity_transactions(db_conn)

    assert summary == {
        "candidate_transactions": 3,
        "mutated_rows": 2,
        "matched_person_rows": 2,
        "skipped_rows": 1,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 1,
        "dual_populated_rows": 0,
    }

    rows = _donor_writeback_rows(db_conn, transaction_ids)
    assert rows["resolved_a"]["contributor_person_id"] == resolved_person_id
    assert rows["resolved_b"]["contributor_person_id"] == resolved_person_id
    assert rows["resolved_a"]["contributor_organization_id"] is None
    assert rows["resolved_b"]["contributor_organization_id"] is None
    assert rows["invalid_cluster"]["contributor_person_id"] is None
    assert rows["unresolved"]["contributor_person_id"] is None
    assert all(row["identity_count"] <= 1 for row in rows.values())

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)::int
            FROM cf.transaction
            WHERE id = ANY(%s)
              AND contributor_person_id IS NOT NULL
            """,
            (list(transaction_ids.values()),),
        )
        assert cursor.fetchone()[0] == 2


def test_donor_writeback_second_run_is_idempotent_and_keeps_identity_columns_stable(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction_ids, _ = _seed_donor_writeback_fixture(db_conn)
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, transaction_ids)

    first_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    before_second_run = _select_transaction_identity_snapshot(db_conn, list(transaction_ids.values()))
    second_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    after_second_run = _select_transaction_identity_snapshot(db_conn, list(transaction_ids.values()))

    assert first_summary["mutated_rows"] == 2
    assert second_summary == {
        "candidate_transactions": 3,
        "mutated_rows": 0,
        "matched_person_rows": 2,
        "skipped_rows": 1,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 1,
        "dual_populated_rows": 0,
    }
    assert after_second_run == before_second_run


def test_donor_writeback_excludes_unpersisted_donor_in_mixed_committee(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_id = _insert_test_committee(db_conn, "mixed-donor-writeback")
    filing_id = _insert_test_filing(db_conn, committee_id, "mixed-donor-writeback")
    resolved_person_id = _insert_donor_writeback_person(
        db_conn,
        f"{_TEST_DONOR_WRITEBACK_PREFIX}Mixed Committee Match",
    )
    persisted_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Mixed Committee Match",
        contributor_employer="PERSISTED INC",
        contributor_occupation="ARCHITECT",
        contributor_city="Raleigh",
        contributor_zip="276050005",
    )
    unrelated_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Same Committee Stranger",
        contributor_employer="UNRELATED LLC",
        contributor_occupation="DESIGNER",
        contributor_city="Raleigh",
        contributor_zip="276060006",
    )
    _insert_donor_identity(db_conn, persisted_tuple, person_id=resolved_person_id)
    transaction_ids = {
        "persisted": _insert_donor_writeback_transaction(
            db_conn,
            label="406",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=persisted_tuple,
        ),
        "unrelated": _insert_donor_writeback_transaction(
            db_conn,
            label="407",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=unrelated_tuple,
        ),
    }
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, transaction_ids)

    summary = resolver_module.resolve_donor_identity_transactions(db_conn)

    assert summary == {
        "candidate_transactions": 1,
        "mutated_rows": 1,
        "matched_person_rows": 1,
        "skipped_rows": 0,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 0,
        "dual_populated_rows": 0,
    }
    rows = _donor_writeback_rows(db_conn, transaction_ids)
    assert rows["persisted"]["contributor_person_id"] == resolved_person_id
    assert rows["unrelated"]["contributor_person_id"] is None
    assert rows["unrelated"]["contributor_organization_id"] is None


def test_donor_writeback_counts_clusterless_donor_identity_as_invalid_cluster(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_id = _insert_test_committee(db_conn, "clusterless-donor-writeback")
    filing_id = _insert_test_filing(db_conn, committee_id, "clusterless-donor-writeback")
    donor_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Clusterless Donor",
        contributor_employer="NO CLUSTER INC",
        contributor_occupation="ANALYST",
        contributor_city="Raleigh",
        contributor_zip="276040004",
    )
    _insert_donor_identity(db_conn, donor_tuple, person_id=None, create_cluster=False)
    transaction_id = _insert_donor_writeback_transaction(
        db_conn,
        label="405",
        committee_id=committee_id,
        filing_id=filing_id,
        donor_tuple=donor_tuple,
    )
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, [transaction_id])

    summary = resolver_module.resolve_donor_identity_transactions(db_conn)

    assert summary == {
        "candidate_transactions": 1,
        "mutated_rows": 0,
        "matched_person_rows": 0,
        "skipped_rows": 1,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 1,
        "dual_populated_rows": 0,
    }
    rows = _donor_writeback_rows(db_conn, {"clusterless": transaction_id})
    assert rows["clusterless"]["contributor_person_id"] is None
    assert rows["clusterless"]["contributor_organization_id"] is None


def test_donor_writeback_uses_person_mapping_created_by_donor_cluster_persistence(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_id = _insert_test_committee(db_conn, "persisted-mapping-donor-writeback")
    filing_id = _insert_test_filing(db_conn, committee_id, "persisted-mapping-donor-writeback")
    donor_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Persisted Mapping",
        contributor_employer="MAPPING INC",
        contributor_occupation="ENGINEER",
        contributor_city="Raleigh",
        contributor_zip="276070007",
    )
    donor_identity_id = _insert_donor_identity(
        db_conn,
        donor_tuple,
        person_id=None,
        create_cluster=False,
    )
    transaction_id = _insert_donor_writeback_transaction(
        db_conn,
        label="408",
        committee_id=committee_id,
        filing_id=filing_id,
        donor_tuple=donor_tuple,
    )
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, [transaction_id])

    cluster_id = persist_auto_merge_clusters(
        db_conn,
        [
            {
                "canonical_entity_id": donor_identity_id,
                "member_ids": {donor_identity_id},
                "min_confidence": 0.99,
                "min_decision": "match",
                "links": [],
            }
        ],
        "donor_identity",
    )[0]

    summary = resolver_module.resolve_donor_identity_transactions(db_conn)

    assert summary == {
        "candidate_transactions": 1,
        "mutated_rows": 1,
        "matched_person_rows": 1,
        "skipped_rows": 0,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 0,
        "dual_populated_rows": 0,
    }
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                dcp.person_id,
                p.er_cluster_id AS person_cluster_id,
                t.contributor_person_id
            FROM core.donor_cluster_person dcp
            JOIN core.person p ON p.id = dcp.person_id
            JOIN cf.transaction t ON t.id = %s
            WHERE dcp.cluster_id = %s
            """,
            (transaction_id, cluster_id),
        )
        mapping_row = cursor.fetchone()

    assert mapping_row is not None
    assert mapping_row["contributor_person_id"] == mapping_row["person_id"]
    assert mapping_row["person_cluster_id"] is None


def test_donor_writeback_split_donor_clusters_map_to_distinct_people(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_id = _insert_test_committee(db_conn, "split-donor-writeback")
    filing_id = _insert_test_filing(db_conn, committee_id, "split-donor-writeback")
    donor_a_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Split Alpha",
        contributor_employer="ORIGINAL CO",
        contributor_occupation="ENGINEER",
        contributor_city="Raleigh",
        contributor_zip="276080008",
    )
    donor_b_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Split Beta",
        contributor_employer="BRANCH CO",
        contributor_occupation="DESIGNER",
        contributor_city="Raleigh",
        contributor_zip="276090009",
    )
    donor_a_id = _insert_donor_identity(db_conn, donor_a_tuple, person_id=None, create_cluster=False)
    donor_b_id = _insert_donor_identity(db_conn, donor_b_tuple, person_id=None, create_cluster=False)
    transaction_ids = {
        "donor_a": _insert_donor_writeback_transaction(
            db_conn,
            label="409",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=donor_a_tuple,
        ),
        "donor_b": _insert_donor_writeback_transaction(
            db_conn,
            label="410",
            committee_id=committee_id,
            filing_id=filing_id,
            donor_tuple=donor_b_tuple,
        ),
    }
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, transaction_ids)

    persist_auto_merge_clusters(
        db_conn,
        [
            {
                "canonical_entity_id": donor_a_id,
                "member_ids": {donor_a_id, donor_b_id},
                "min_confidence": 0.99,
                "min_decision": "match",
                "links": [],
            }
        ],
        "donor_identity",
    )
    first_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    first_rows = _donor_writeback_rows(db_conn, transaction_ids)

    persist_auto_merge_clusters(
        db_conn,
        [
            {
                "canonical_entity_id": donor_a_id,
                "member_ids": {donor_a_id},
                "min_confidence": 0.99,
                "min_decision": "match",
                "links": [],
            },
            {
                "canonical_entity_id": donor_b_id,
                "member_ids": {donor_b_id},
                "min_confidence": 0.99,
                "min_decision": "match",
                "links": [],
            },
        ],
        "donor_identity",
    )
    second_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    second_rows = _donor_writeback_rows(db_conn, transaction_ids)
    mapped_people = _donor_person_mapping_by_identity_id(db_conn, [donor_a_id, donor_b_id])

    assert first_summary["mutated_rows"] == 2
    assert first_rows["donor_a"]["contributor_person_id"] == first_rows["donor_b"]["contributor_person_id"]
    assert second_summary == {
        "candidate_transactions": 2,
        "mutated_rows": 1,
        "matched_person_rows": 2,
        "skipped_rows": 0,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 0,
        "dual_populated_rows": 0,
    }
    assert set(mapped_people) == {donor_a_id, donor_b_id}
    assert mapped_people[donor_a_id] != mapped_people[donor_b_id]
    assert second_rows["donor_a"]["contributor_person_id"] == mapped_people[donor_a_id]
    assert second_rows["donor_b"]["contributor_person_id"] == mapped_people[donor_b_id]
    assert second_rows["donor_a"]["contributor_person_id"] != second_rows["donor_b"]["contributor_person_id"]
    assert all(row["identity_count"] <= 1 for row in second_rows.values())


def test_donor_writeback_clears_stale_person_when_mapping_becomes_invalid(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_id = _insert_test_committee(db_conn, "stale-clear-donor-writeback")
    filing_id = _insert_test_filing(db_conn, committee_id, "stale-clear-donor-writeback")
    person_id = _insert_donor_writeback_person(db_conn, f"{_TEST_DONOR_WRITEBACK_PREFIX}Stale Clear")
    donor_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Stale Clear",
        contributor_employer="STALE INC",
        contributor_occupation="ANALYST",
        contributor_city="Raleigh",
        contributor_zip="276100010",
    )
    donor_identity_id = _insert_donor_identity(db_conn, donor_tuple, person_id=person_id)
    transaction_id = _insert_donor_writeback_transaction(
        db_conn,
        label="411",
        committee_id=committee_id,
        filing_id=filing_id,
        donor_tuple=donor_tuple,
    )
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, [transaction_id])

    first_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    db_conn.execute(
        """
        DELETE FROM core.donor_cluster_person
        WHERE cluster_id = (
            SELECT er_cluster_id
            FROM core.donor_identity
            WHERE id = %s
        )
        """,
        (donor_identity_id,),
    )
    second_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    rows = _donor_writeback_rows(db_conn, {"stale": transaction_id})

    assert first_summary["mutated_rows"] == 1
    assert second_summary == {
        "candidate_transactions": 1,
        "mutated_rows": 1,
        "matched_person_rows": 0,
        "skipped_rows": 1,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 1,
        "dual_populated_rows": 0,
    }
    assert rows["stale"]["contributor_person_id"] is None
    assert rows["stale"]["contributor_organization_id"] is None


def test_donor_writeback_preserves_organization_when_person_mapping_becomes_invalid(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_id = _insert_test_committee(db_conn, "organization-preservation-donor-writeback")
    filing_id = _insert_test_filing(db_conn, committee_id, "organization-preservation-donor-writeback")
    person_id = _insert_donor_writeback_person(
        db_conn,
        f"{_TEST_DONOR_WRITEBACK_PREFIX}Organization Preservation",
    )
    organization_id = insert_organization(
        db_conn,
        Organization(canonical_name=f"{_TEST_DONOR_WRITEBACK_PREFIX}Organization Owner"),
    )
    donor_tuple = _donor_identity_tuple(
        contributor_name_raw=f"{_TEST_DONOR_WRITEBACK_PREFIX}Organization Preservation",
        contributor_employer="OWNERSHIP INC",
        contributor_occupation="ANALYST",
        contributor_city="Raleigh",
        contributor_zip="276110011",
    )
    donor_identity_id = _insert_donor_identity(db_conn, donor_tuple, person_id=person_id)
    transaction_id = _insert_donor_writeback_transaction(
        db_conn,
        label="412",
        committee_id=committee_id,
        filing_id=filing_id,
        donor_tuple=donor_tuple,
    )
    _scope_donor_writeback_resolver_to_transactions(monkeypatch, [transaction_id])

    first_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    organization_assignment_mutated = update_transaction_contributor_identity_ids(
        db_conn,
        transaction_id=transaction_id,
        contributor_person_id=None,
        contributor_organization_id=organization_id,
    )
    db_conn.execute(
        """
        DELETE FROM core.donor_cluster_person
        WHERE cluster_id = (
            SELECT er_cluster_id
            FROM core.donor_identity
            WHERE id = %s
        )
        """,
        (donor_identity_id,),
    )

    second_summary = resolver_module.resolve_donor_identity_transactions(db_conn)
    rows = _donor_writeback_rows(db_conn, {"organization_owned": transaction_id})

    assert first_summary["mutated_rows"] == 1
    assert organization_assignment_mutated is True
    assert second_summary == {
        "candidate_transactions": 1,
        "mutated_rows": 0,
        "matched_person_rows": 0,
        "skipped_rows": 1,
        "unresolved_rows": 0,
        "ambiguous_cluster_rows": 0,
        "invalid_cluster_rows": 1,
        "dual_populated_rows": 0,
    }
    assert rows["organization_owned"]["contributor_person_id"] is None
    assert rows["organization_owned"]["contributor_organization_id"] == organization_id
    assert rows["organization_owned"]["identity_count"] == 1


def test_resolver_includes_transactions_seeded_with_loader_jurisdiction_casing(
    db_conn: psycopg.Connection,
) -> None:
    source_record_id = _insert_test_source_record(
        db_conn,
        label="loader-jurisdiction-casing",
        jurisdiction="state/NC",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Loader Jurisdiction Case",
            street_line_1="77 Capitol Ave",
            city="Raleigh",
            state="NC",
            zip_code="27605",
            transaction_type="Individual",
        ),
    )
    person_id = _insert_person_candidate(
        db_conn,
        label="loader-jurisdiction-person",
        canonical_name="Loader Jurisdiction Case",
        identifier_key="voter_reg_id:VR-LOADER-CASE",
        normalized_address="77 Capitol Ave Raleigh NC 27605",
        zip5="27605",
    )
    insert_entity_source(db_conn, "person", person_id, source_record_id, "donor")
    transaction_id = _insert_transaction(
        db_conn,
        label="104",
        source_record_id=source_record_id,
        contributor_name_raw="Loader Jurisdiction Case",
        contributor_state="NC",
        contributor_zip="27605",
        transaction_type="Individual",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary["candidate_transactions"] == 1
    assert summary["mutated_rows"] == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row["contributor_person_id"] == person_id
    assert row["contributor_organization_id"] is None


def test_resolver_second_run_is_idempotent_with_stable_transaction_identity_columns(
    db_conn: psycopg.Connection,
) -> None:
    transaction_ids, _ = _seed_resolver_fixture(db_conn)
    target_transaction_ids = list(transaction_ids.values())

    first_summary = resolve_nc_transaction_counterparties(db_conn)
    before_second_run = _select_transaction_identity_snapshot(db_conn, target_transaction_ids)
    second_summary = resolve_nc_transaction_counterparties(db_conn)
    after_second_run = _select_transaction_identity_snapshot(db_conn, target_transaction_ids)

    assert first_summary["mutated_rows"] == 2
    assert second_summary == {
        "candidate_transactions": 1,
        "mutated_rows": 0,
        "matched_person_rows": 0,
        "matched_organization_rows": 0,
        "skipped_rows": 1,
        "ambiguous_rows": 1,
        "dual_match_rows": 0,
    }
    assert after_second_run == before_second_run


def test_resolver_uses_transaction_context_when_source_record_has_both_donor_and_vendor_rows(
    db_conn: psycopg.Connection,
) -> None:
    shared_source_record_id = _insert_test_source_record(
        db_conn,
        label="mixed-role-shared-record",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Mixed Role Shared",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27604",
        ),
    )

    donor_person_id = _insert_person_candidate(
        db_conn,
        label="mixed-role-donor",
        canonical_name="Mixed Role Shared",
        identifier_key="voter_reg_id:VR-MIXED-DONOR",
        normalized_address="123 Main St Raleigh NC 27604",
        zip5="27604",
    )
    vendor_org_id = _insert_organization_candidate(
        db_conn,
        canonical_name="Mixed Role Shared",
        ein="98-7654321",
        normalized_address="123 Main St Raleigh NC 27604",
        zip5="27604",
    )
    insert_entity_source(db_conn, "person", donor_person_id, shared_source_record_id, "donor")
    insert_entity_source(db_conn, "organization", vendor_org_id, shared_source_record_id, "vendor")

    donor_transaction_id = _insert_transaction(
        db_conn,
        label="201",
        source_record_id=shared_source_record_id,
        contributor_name_raw="Mixed Role Shared",
        contributor_state="NC",
        contributor_zip="27604",
        transaction_type="Individual",
    )
    vendor_transaction_id = _insert_transaction(
        db_conn,
        label="202",
        source_record_id=shared_source_record_id,
        contributor_name_raw="Mixed Role Shared",
        contributor_state="NC",
        contributor_zip="27604",
        transaction_type="Business/Group/Org",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary == {
        "candidate_transactions": 2,
        "mutated_rows": 2,
        "matched_person_rows": 1,
        "matched_organization_rows": 1,
        "skipped_rows": 0,
        "ambiguous_rows": 0,
        "dual_match_rows": 0,
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            ([donor_transaction_id, vendor_transaction_id],),
        )
        rows = {row["id"]: row for row in cursor.fetchall()}

    assert rows[donor_transaction_id]["contributor_person_id"] == donor_person_id
    assert rows[donor_transaction_id]["contributor_organization_id"] is None
    assert rows[vendor_transaction_id]["contributor_person_id"] is None
    assert rows[vendor_transaction_id]["contributor_organization_id"] == vendor_org_id


def test_resolver_includes_nc_contributor_organization_role_candidates(
    db_conn: psycopg.Connection,
) -> None:
    source_record_id = _insert_test_source_record(
        db_conn,
        label="org-contributor-role",
        raw_fields=_build_nc_transaction_raw_fields(
            name="ORG CONTRIBUTOR ROLE LLC",
            street_line_1="88 Broad Street",
            city="Raleigh",
            state="NC",
            zip_code="27601",
            occupation="Business",
            employer_or_business="ORG CONTRIBUTOR ROLE LLC",
            transaction_type="Business/Group/Org",
        ),
    )
    organization_id = _insert_organization_candidate(
        db_conn,
        canonical_name="ORG CONTRIBUTOR ROLE LLC",
        ein="55-4433221",
        normalized_address="88 Broad St Raleigh NC 27601",
        zip5="27601",
    )
    insert_entity_source(db_conn, "organization", organization_id, source_record_id, "contributor")
    transaction_id = _insert_transaction(
        db_conn,
        label="301",
        source_record_id=source_record_id,
        contributor_name_raw="ORG CONTRIBUTOR ROLE LLC",
        contributor_state="NC",
        contributor_zip="27601",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary["mutated_rows"] == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row["contributor_person_id"] is None
    assert row["contributor_organization_id"] == organization_id


def test_resolver_uses_nc_transaction_type_for_role_specific_identifier_and_address(
    db_conn: psycopg.Connection,
) -> None:
    source_record_id = _insert_test_source_record(
        db_conn,
        label="nc-transaction-type-organization",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Portal Participant Label",
            street_line_1="900 Market St",
            city="Raleigh",
            state="NC",
            zip_code="27602",
            occupation="Business",
            employer_or_business="Acme Group",
            transaction_type="Business/Group/Org",
        ),
    )
    person_id = _insert_person_candidate(
        db_conn,
        label="wrong-side-person",
        canonical_name="Real Transaction Name",
        identifier_key="voter_reg_id:VR-SHARED-ROLE",
        normalized_address="900 Market St Raleigh NC 27602",
        zip5="27602",
    )
    organization_id = _insert_organization_candidate(
        db_conn,
        canonical_name="Real Transaction Name",
        ein="11-2233445",
        normalized_address="900 Market St Raleigh NC 27602",
        zip5="27602",
    )
    insert_entity_source(db_conn, "person", person_id, source_record_id, "donor")
    insert_entity_source(db_conn, "organization", organization_id, source_record_id, "vendor")

    transaction_id = _insert_transaction(
        db_conn,
        label="302",
        source_record_id=source_record_id,
        contributor_name_raw="Real Transaction Name",
        contributor_state="NC",
        contributor_zip="27602",
        transaction_type="Business/Group/Org",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary["mutated_rows"] == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row["contributor_person_id"] is None
    assert row["contributor_organization_id"] == organization_id
