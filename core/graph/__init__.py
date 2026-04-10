from __future__ import annotations

import hashlib
from typing import Any

import psycopg
from psycopg import sql

GRAPH_NAME = "civibus"


def _cypher_dollar_quote_tag(cypher_template: str) -> sql.SQL:
    """Build a dollar-quote delimiter not present in the Cypher template."""
    if "\x00" in cypher_template:
        raise ValueError("Cypher template cannot contain null bytes")

    base_tag = "$civibus_cypher$"
    if base_tag not in cypher_template:
        return sql.SQL(base_tag)

    digest = hashlib.sha256(cypher_template.encode("utf-8")).hexdigest()
    for width in range(8, len(digest) + 1, 8):
        candidate = f"$civibus_cypher_{digest[:width]}$"
        if candidate not in cypher_template:
            return sql.SQL(candidate)

    raise ValueError("Failed to construct a safe Cypher dollar-quote delimiter")


def _build_formatted_cypher_do_statement(
    *,
    cypher_template: str,
    format_args: tuple[object, ...],
    leading_query_sql: sql.SQL,
) -> sql.Composed:
    """Build a PL/pgSQL DO statement that executes a format()-parameterized Cypher query."""
    cypher_quote_tag = _cypher_dollar_quote_tag(cypher_template)
    format_arguments_sql = sql.SQL(", ").join(sql.Literal(arg) for arg in format_args)
    return sql.SQL(
        """
        DO $$
        BEGIN
            EXECUTE format(
                $sql$
                {leading_query_sql}
                FROM ag_catalog.cypher({graph_name}, {cypher_quote_tag}
{cypher_template}
                {cypher_quote_tag}) AS (v agtype)
                $sql$,
                {format_arguments}
            );
        END
        $$;
        """
    ).format(
        leading_query_sql=leading_query_sql,
        graph_name=sql.Literal(GRAPH_NAME),
        cypher_quote_tag=cypher_quote_tag,
        cypher_template=sql.SQL(cypher_template),
        format_arguments=format_arguments_sql,
    )


def _escape_cypher_literal(value: str) -> str:
    """Escape a string for safe embedding in a double-quoted Cypher literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _execute_formatted_cypher(
    conn: psycopg.Connection,
    cypher_template: str,
    *format_args: object,
    leading_query_sql: sql.SQL = sql.SQL("SELECT *"),
) -> None:
    """Execute a Cypher statement via the shared PL/pgSQL format() wrapper."""
    statement = _build_formatted_cypher_do_statement(
        cypher_template=cypher_template,
        format_args=format_args,
        leading_query_sql=leading_query_sql,
    )
    conn.execute(statement)


def age_post_connect(conn: psycopg.Connection) -> None:
    """Post-connect hook that initializes AGE for Cypher queries.

    Pass to ``get_connection(post_connect=age_post_connect)``.
    """
    conn.execute("LOAD 'age'")
    conn.execute('SET search_path = ag_catalog, "$user", public')


def ensure_graph(conn: psycopg.Connection) -> None:
    """Create the civibus graph if it does not already exist. Idempotent."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s",
            (GRAPH_NAME,),
        )
        if cur.fetchone() is not None:
            return

    conn.execute("SELECT ag_catalog.create_graph(%s)", (GRAPH_NAME,))


def query_formatted_cypher(
    conn: psycopg.Connection,
    cypher_template: str,
    *format_args: object,
) -> list[Any]:
    """Execute a read Cypher query via PL/pgSQL format() and return agtype rows."""
    conn.execute("DROP TABLE IF EXISTS _cypher_query_results")
    conn.execute("CREATE TEMP TABLE _cypher_query_results (v agtype)")

    if not format_args:
        cypher_quote_tag = _cypher_dollar_quote_tag(cypher_template)
        statement = sql.SQL(
            """
            INSERT INTO _cypher_query_results
            SELECT *
            FROM ag_catalog.cypher({graph_name}, {cypher_quote_tag}
{cypher_template}
            {cypher_quote_tag}) AS (v agtype)
            """
        ).format(
            graph_name=sql.Literal(GRAPH_NAME),
            cypher_quote_tag=cypher_quote_tag,
            cypher_template=sql.SQL(cypher_template),
        )
    else:
        statement = _build_formatted_cypher_do_statement(
            cypher_template=cypher_template,
            format_args=format_args,
            leading_query_sql=sql.SQL(
                """
                INSERT INTO _cypher_query_results
                SELECT *
                """
            ),
        )

    conn.execute(statement)

    with conn.cursor() as cur:
        cur.execute("SELECT v FROM _cypher_query_results")
        rows = cur.fetchall()

    conn.execute("DROP TABLE _cypher_query_results")
    return [row[0] for row in rows]
