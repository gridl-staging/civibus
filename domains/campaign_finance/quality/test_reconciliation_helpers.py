"""Shared helper functions for reconciliation contract tests."""

from __future__ import annotations


def mock_conn_with_side_effect(side_effect: list[tuple]) -> tuple[object, object]:
    """Build a mock connection whose cursor returns values from side_effect."""
    from unittest.mock import MagicMock

    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = side_effect
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, mock_cursor


def flatten_params(value: object) -> list[object]:
    """Flatten nested params tuples/lists into a flat list."""
    if isinstance(value, (list, tuple)):
        flattened: list[object] = []
        for item in value:
            flattened.extend(flatten_params(item))
        return flattened
    return [value]


def sql_and_params_text(call: object) -> tuple[str, str]:
    """Return normalized lowercase SQL + params text from a mock execute() call."""
    call_args = tuple(getattr(call, "args", ()))
    tuple_args = tuple(call[0]) if call and call[0] else ()
    sql = call_args[0] if len(call_args) > 0 else (tuple_args[0] if len(tuple_args) > 0 else "")
    params = call_args[1] if len(call_args) > 1 else (tuple_args[1] if len(tuple_args) > 1 else ())
    normalized_sql = " ".join(str(sql).lower().split())
    normalized_params = " ".join(str(params).lower().split())
    return normalized_sql, normalized_params


def query_uses_cypher(sql: str) -> bool:
    """Return whether SQL uses AGE/Cypher edge projection."""
    return "cypher(" in sql and "match" in sql and "source_record_id" in sql


def query_references_edge_label(sql: str, params_text: str, *, edge_label: str) -> bool:
    """Return whether SQL/params reference the expected campaign-finance edge label."""
    label_lower = edge_label.lower()
    return f":{label_lower}" in sql or label_lower in params_text


def has_source_record_id_join(sql: str) -> bool:
    """Return whether SQL scopes edge source_record_id via source_record.id."""
    import re

    normalized = " ".join(sql.lower().split())
    source_record_id_token = r"(?:\b[a-z_][\w]*\.)?source_record_id\b"
    direct_join_match = re.search(
        rf"(?:{source_record_id_token}[^=]{{0,100}}=\s*(?:\([^)]*\)\s*)*(?P<rhs_alias>sr|source_record)\.id\b)"
        rf"|(?:\b(?P<lhs_alias>sr|source_record)\.id\b\s*=\s*(?:\([^)]*\)\s*)*[^=]{{0,100}}{source_record_id_token})",
        normalized,
    )
    if direct_join_match:
        alias = direct_join_match.group("rhs_alias") or direct_join_match.group("lhs_alias")
        if not alias:
            return False
        alias_scoped_to_source_record = bool(
            re.search(
                rf"\b(?:from|join)\s+core\.source_record\s+(?:as\s+)?{alias}\b",
                normalized,
            )
        ) or (alias == "source_record" and bool(re.search(r"\b(?:from|join)\s+core\.source_record\b", normalized)))
        data_source_scoped_to_same_alias = bool(re.search(rf"\b{alias}\.data_source_id\b", normalized))
        return alias_scoped_to_source_record and data_source_scoped_to_same_alias

    # For IN-subquery shapes, require that data_source_id is scoped on the same
    # source_record alias used to select ids consumed by source_record_id.
    return bool(
        re.search(
            rf"{source_record_id_token}.{{0,120}}\bin\s*\(\s*select\b.{{0,160}}\b(?P<alias>sr|source_record)\.id\b"
            r".{0,260}\bfrom\s+core\.source_record\s+(?:as\s+)?(?P=alias)\b"
            r".{0,260}\bwhere\b.{0,260}\b(?P=alias)\.data_source_id\b",
            normalized,
        )
    )


def has_type_allowlist_in_sql_or_params(sql: str, params_text: str, type_values: frozenset[str]) -> bool:
    """Return True only when every route type appears as an exact quoted literal."""
    import re

    normalized_sql = " ".join(str(sql).lower().split())
    normalized_params = " ".join(str(params_text).lower().split())
    normalized_types = {t.lower() for t in type_values}
    if not normalized_types:
        return False

    quoted_literals = {
        match.group(1).replace("''", "'")
        for match in re.finditer(r"'((?:''|[^'])*)'", f"{normalized_sql} {normalized_params}")
    }
    return normalized_types.issubset(quoted_literals)


def _routes_count_through_table(sql: str, table_name: str) -> bool:
    """Return whether COUNT semantics are tied to the expected table route."""
    import re

    normalized = " ".join(sql.lower().split())
    table_pattern = re.escape(table_name.lower())
    from_mentions = list(
        re.finditer(
            rf"\bfrom\s+{table_pattern}(?:\s+(?:as\s+)?(?P<alias>[a-z_][\w]*))?\b",
            normalized,
        )
    )
    join_mentions = list(
        re.finditer(
            rf"\bjoin\s+{table_pattern}(?:\s+(?:as\s+)?(?P<alias>[a-z_][\w]*))?\b",
            normalized,
        )
    )
    if not from_mentions and not join_mentions:
        return False

    count_match = re.search(r"\bcount\s*\(\s*(?:distinct\s+)?(?P<expr>[^)]+?)\s*\)", normalized)
    if not count_match:
        return False
    count_expr = count_match.group("expr").strip()

    # COUNT(*) is valid when the expected route table is a FROM relation.
    # This still rejects wrong-table shapes where the table is only joined.
    if count_expr == "*":
        return bool(from_mentions)

    aliases = {
        alias
        for match in [*from_mentions, *join_mentions]
        for alias in [match.group("alias")]
        if alias
        and alias
        not in {
            "where",
            "group",
            "order",
            "limit",
            "offset",
            "on",
            "using",
            "left",
            "right",
            "full",
            "inner",
            "outer",
            "cross",
            "union",
        }
    }
    qualifiers = set(aliases)
    qualifiers.add(table_name.lower())
    if "." in table_name:
        qualifiers.add(table_name.lower().split(".")[-1])

    qualifier_match = re.match(
        r"(?P<qualifier>[a-z_][\w]*(?:\.[a-z_][\w]*)?)\.[a-z_][\w]*$",
        count_expr.split("::", 1)[0].strip().strip("()"),
    )
    if qualifier_match:
        return qualifier_match.group("qualifier") in qualifiers

    # Unqualified COUNT(column) is only safe when the route table appears in FROM.
    return bool(from_mentions)


def routes_to_filing_table(sql: str) -> bool:
    """Return whether SQL routes FILED denominator logic through cf.filing."""
    return _routes_count_through_table(sql, "cf.filing")


def routes_to_candidate_committee_link_table(sql: str) -> bool:
    """Return whether SQL routes AFFILIATED_WITH denominator through cf.candidate_committee_link."""
    return _routes_count_through_table(sql, "cf.candidate_committee_link")


def routes_to_transaction_table(sql: str) -> bool:
    """Return whether SQL routes transaction-derived denominator logic through cf.transaction."""
    return _routes_count_through_table(sql, "cf.transaction")


def call_matches_family_route(
    sql: str,
    params_text: str,
    family: str,
    *,
    contribution_types: frozenset[str],
    expenditure_types: frozenset[str],
) -> bool:
    """Return True if an execute call carries the route semantics for the given family."""
    if family == "CONTRIBUTED_TO":
        return (
            routes_to_transaction_table(sql)
            and has_type_allowlist_in_sql_or_params(sql, params_text, contribution_types)
            and "support_oppose is null" in sql
        )
    if family == "SPENT_ON":
        return (
            routes_to_transaction_table(sql)
            and has_type_allowlist_in_sql_or_params(sql, params_text, expenditure_types)
            and "support_oppose is null" in sql
        )
    if family == "SUPPORTS":
        return routes_to_transaction_table(sql) and has_exact_support_oppose_routing(
            sql, params_text, discriminator="S"
        )
    if family == "OPPOSES":
        return routes_to_transaction_table(sql) and has_exact_support_oppose_routing(
            sql, params_text, discriminator="O"
        )
    if family == "AFFILIATED_WITH":
        return routes_to_candidate_committee_link_table(sql)
    if family == "FILED":
        return routes_to_filing_table(sql)
    return False


def has_candidate_eligibility_join(sql: str) -> bool:
    """Return whether SQL joins cf.candidate on recipient_candidate_id.

    Matches the load_ie_edges() pattern that inner-joins cf.candidate to
    ensure only IE rows with a resolved candidate can be counted.
    """
    import re

    normalized = " ".join(sql.lower().split())
    return bool(
        re.search(
            r"\bjoin\s+cf\.candidate\b.{0,60}\b(?:cand|candidate)\.id\s*=\s*\w+\.recipient_candidate_id\b"
            r"|\brecipient_candidate_id\s*=\s*(?:cand|candidate)\.id\b",
            normalized,
        )
    )


def has_exact_support_oppose_routing(sql: str, params: object, *, discriminator: str) -> bool:
    """Return whether SQL proves exact SUPPORTS/OPPOSES routing semantics."""
    import re

    normalized = " ".join(sql.lower().split())
    flattened_upper = {str(item).upper() for item in flatten_params(params)}
    params_upper_text = " ".join(str(params).upper().split())
    discriminator_lower = discriminator.lower()
    has_discriminator_param = discriminator in flattened_upper or f"'{discriminator}'" in params_upper_text

    has_literal_equality = bool(
        re.search(
            rf"support_oppose\s*=\s*'{discriminator_lower}'",
            normalized,
        )
    )
    has_placeholder_equality = bool(re.search(r"support_oppose\s*=\s*%s", normalized)) and has_discriminator_param
    if has_literal_equality or has_placeholder_equality:
        return True

    has_support_oppose_in = bool(re.search(r"support_oppose\s+in\s*\(", normalized))
    has_grouped_split = bool(re.search(r"group\s+by\b.{0,120}\bsupport_oppose\b", normalized))
    has_filter_split = (
        "filter (where" in normalized and "support_oppose" in normalized and "'s'" in normalized and "'o'" in normalized
    )
    has_case_split = (
        "case when" in normalized and "support_oppose" in normalized and "'s'" in normalized and "'o'" in normalized
    )
    params_have_both = {"S", "O"}.issubset(flattened_upper) or (
        "'S'" in params_upper_text and "'O'" in params_upper_text
    )
    literals_have_both = "'s'" in normalized and "'o'" in normalized
    has_explicit_split = (
        has_filter_split
        or has_case_split
        or (has_support_oppose_in and has_grouped_split and (params_have_both or literals_have_both))
    )
    return has_explicit_split
