"""Control-flow regressions for the organization identifier-writer guard."""

from __future__ import annotations

import ast
from pathlib import Path

from core.entity_resolution.test_splink_config_identifier_writer_guard import (
    _function_writes_key_to_organization_identifiers,
)


def test_organization_identifier_writer_guard_ignores_nested_local_assignments() -> None:
    """A nested identifier assignment must not vouch for an outer Organization call."""
    function_node = ast.parse(
        """
def build_organization():
    identifiers = {}

    def build_person_identifiers():
        identifiers = {}
        identifiers["dead_key"] = "person-only"
        return identifiers

    return Organization(identifiers=identifiers)
"""
    ).body[0]

    assert isinstance(function_node, ast.FunctionDef)
    assert not _function_writes_key_to_organization_identifiers(function_node, "dead_key")


def test_organization_identifier_writer_guard_tracks_rebound_local_identifiers() -> None:
    """A stale identifier write must not vouch for a later rebound Organization call."""
    function_node = ast.parse(
        """
def build_organization():
    identifiers = {}
    identifiers["dead_key"] = "person-only"
    person = Person(identifiers=identifiers)

    identifiers = {}
    return Organization(identifiers=identifiers, canonical_name=person.canonical_name)
"""
    ).body[0]

    assert isinstance(function_node, ast.FunctionDef)
    assert not _function_writes_key_to_organization_identifiers(function_node, "dead_key")


def test_organization_identifier_writer_guard_preserves_branch_alternatives() -> None:
    """A true-branch write must not vouch for an else-branch Organization call."""
    function_node = ast.parse(
        """
def build_organization(is_person):
    identifiers = {}
    if is_person:
        identifiers["dead_key"] = "person-only"
        return Person(identifiers=identifiers)
    else:
        return Organization(identifiers=identifiers)
"""
    ).body[0]

    assert isinstance(function_node, ast.FunctionDef)
    assert not _function_writes_key_to_organization_identifiers(function_node, "dead_key")


def test_organization_identifier_writer_guard_terminates_paths_after_raise() -> None:
    """An unreachable Organization call must not make a person-only key live."""
    function_node = ast.parse(
        """
def build_person():
    identifiers = {}
    identifiers["dead_key"] = "person-only"
    person = Person(identifiers=identifiers)
    raise ValueError("person could not be built")
    return Organization(identifiers=identifiers, canonical_name=person.canonical_name)
"""
    ).body[0]

    assert isinstance(function_node, ast.FunctionDef)
    assert not _function_writes_key_to_organization_identifiers(function_node, "dead_key")


def test_organization_identifier_writer_guard_terminates_paths_after_assert() -> None:
    """A literal-false assertion makes a later Organization call unreachable."""
    function_node = ast.parse(
        """
def build_person():
    identifiers = {}
    identifiers["dead_key"] = "person-only"
    person = Person(identifiers=identifiers)
    assert False
    return Organization(identifiers=identifiers, canonical_name=person.canonical_name)
"""
    ).body[0]

    assert isinstance(function_node, ast.FunctionDef)
    assert not _function_writes_key_to_organization_identifiers(function_node, "dead_key")


def _parse_single_function(source: str) -> ast.FunctionDef:
    function_node = ast.parse(source).body[0]
    assert isinstance(function_node, ast.FunctionDef)
    return function_node


def test_organization_identifier_writer_guard_traverses_compound_statements() -> None:
    """Compound-body writes must vouch for a later Organization call."""
    writer_functions = [
        """
def build_organization(rows):
    identifiers = {}
    for row in rows:
        identifiers["fec_committee_id"] = row.committee_id
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(context):
    identifiers = {}
    with context:
        identifiers["fec_committee_id"] = "C001"
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
    except ValueError:
        identifiers = {}
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(row):
    identifiers = {}
    while row.has_committee:
        identifiers["fec_committee_id"] = row.committee_id
        break
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(row):
    identifiers = {}
    match row.kind:
        case "committee":
            identifiers["fec_committee_id"] = row.committee_id
    return Organization(identifiers=identifiers)
""",
    ]

    for source in writer_functions:
        assert _function_writes_key_to_organization_identifiers(
            _parse_single_function(source),
            "fec_committee_id",
        )


def test_organization_identifier_writer_guard_rejects_loop_body_rebind_before_organization() -> None:
    """A loop-local rebind must clear stale identifier state before Organization."""
    function_node = _parse_single_function(
        """
def build_organization(rows):
    identifiers = {}
    identifiers["dead_key"] = "person-only"
    for row in rows:
        identifiers = {}
        return Organization(identifiers=identifiers)
    return None
"""
    )
    empty_iterable_functions = [
        _parse_single_function(
            f"""
def build_organization(row):
    identifiers = {{"dead_key": row.person_id}}
    for item in {empty_iterable}:
        return Organization(identifiers=identifiers, source=item)
    return None
"""
        )
        for empty_iterable in ("()", "[]", "{}")
    ]
    empty_iterable_else_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    for item in ():
        pass
    else:
        identifiers["fec_committee_id"] = row.committee_id
    return Organization(identifiers=identifiers)
"""
    )

    assert not _function_writes_key_to_organization_identifiers(function_node, "dead_key")
    for empty_iterable_function in empty_iterable_functions:
        assert not _function_writes_key_to_organization_identifiers(empty_iterable_function, "dead_key")
    assert _function_writes_key_to_organization_identifiers(
        empty_iterable_else_function,
        "fec_committee_id",
    )


def test_organization_identifier_writer_guard_discards_nonempty_literal_for_fallthrough() -> None:
    """A guaranteed loop body must replace stale entry state before fall-through."""
    guaranteed_nonempty_rebind_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {"dead_key": row.person_id}
    for item in [1]:
        identifiers = {}
    return Organization(identifiers=identifiers)
"""
    )
    unknown_iterable_rebind_function = _parse_single_function(
        """
def build_organization(rows):
    identifiers = {"dead_key": "person-only"}
    for row in rows:
        identifiers = {}
    return Organization(identifiers=identifiers)
"""
    )

    assert not _function_writes_key_to_organization_identifiers(
        guaranteed_nonempty_rebind_function,
        "dead_key",
    )
    assert _function_writes_key_to_organization_identifiers(unknown_iterable_rebind_function, "dead_key")


def test_organization_identifier_writer_guard_bounds_literal_for_iterations() -> None:
    """A literal loop must not execute beyond its exact iterable cardinality."""
    one_iteration_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    for item in [1]:
        if identifiers:
            return Organization(identifiers=identifiers)
        identifiers["dead_key"] = row.person_id
    return None
"""
    )

    assert not _function_writes_key_to_organization_identifiers(
        one_iteration_function,
        "dead_key",
    )


def test_organization_identifier_writer_guard_treats_starred_literal_cardinality_as_unknown() -> None:
    """A starred literal can supply enough items to reach a later iteration."""
    starred_iterable_function = _parse_single_function(
        """
def build_organization(rows, row):
    identifiers = {}
    for item in [*rows]:
        if identifiers:
            return Organization(identifiers=identifiers)
        identifiers["dead_key"] = row.person_id
    return None
"""
    )

    assert _function_writes_key_to_organization_identifiers(
        starred_iterable_function,
        "dead_key",
    )


def test_organization_identifier_writer_guard_does_not_leak_try_state_through_finally() -> None:
    """Exception-path states must not survive a try on the normal path."""
    rebound_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["dead_key"] = row.person_id
        identifiers = {}
    finally:
        log_processed(row)
    return Organization(identifiers=identifiers)
"""
    )
    live_writer_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["dead_key"] = row.committee_id
    finally:
        log_processed(row)
    return Organization(identifiers=identifiers)
"""
    )

    assert not _function_writes_key_to_organization_identifiers(rebound_function, "dead_key")
    assert _function_writes_key_to_organization_identifiers(live_writer_function, "dead_key")


def test_organization_identifier_writer_guard_tracks_conditional_identifier_maps() -> None:
    """Conditional and helper-filtered maps can carry keys to an Organization."""
    writer_sources = [
        """
def build_organization(row):
    identifiers = {"fec_committee_id": row.committee_id} if row.committee_id else {}
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(row):
    return Organization(
        identifiers=filter_identifiers({"ga_filer_id": row.filer_id}),
    )
""",
        """
def build_organization(row):
    identifiers = dict(fec_committee_id=row.committee_id)
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(row):
    identifiers = {}
    identifiers.update(fec_committee_id=row.committee_id)
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(row):
    identifiers = {**{"fec_committee_id": row.committee_id}}
    return Organization(identifiers=identifiers)
""",
    ]

    for source in writer_sources:
        assert _function_writes_key_to_organization_identifiers(
            _parse_single_function(source),
            "ga_filer_id" if "ga_filer_id" in source else "fec_committee_id",
        )


def test_organization_identifier_writer_guard_requires_guaranteed_compound_bodies() -> None:
    """An irrefutable compound body must replace, not preserve, its entry state."""
    guaranteed_rebind_functions = [
        """
def build_organization(row):
    identifiers = {"dead_key": row.person_id}
    match row.kind:
        case _:
            identifiers = {}
    return Organization(identifiers=identifiers)
""",
        """
def build_organization(row):
    identifiers = {"dead_key": row.person_id}
    while True:
        identifiers = {}
        break
    return Organization(identifiers=identifiers)
""",
    ]
    optional_rebind_function = _parse_single_function(
        """
def build_organization(rows):
    identifiers = {"dead_key": "person-only"}
    for row in rows:
        identifiers = {}
    return Organization(identifiers=identifiers)
"""
    )

    for source in guaranteed_rebind_functions:
        assert not _function_writes_key_to_organization_identifiers(
            _parse_single_function(source),
            "dead_key",
        )
    assert _function_writes_key_to_organization_identifiers(optional_rebind_function, "dead_key")


def test_organization_identifier_writer_guard_preserves_loop_break_exit_states() -> None:
    """A break bypasses loop else without making later body statements reachable."""
    break_writer_function = _parse_single_function(
        """
def build_organization(rows):
    identifiers = {}
    for row in rows:
        identifiers["fec_committee_id"] = row.committee_id
        break
    else:
        identifiers = {}
    return Organization(identifiers=identifiers)
"""
    )
    unreachable_writer_function = _parse_single_function(
        """
def build_organization(rows):
    identifiers = {"dead_key": "person-only"}
    for row in rows:
        continue
        return Organization(identifiers=identifiers)
    return None
"""
    )

    assert _function_writes_key_to_organization_identifiers(
        break_writer_function,
        "fec_committee_id",
    )
    assert not _function_writes_key_to_organization_identifiers(unreachable_writer_function, "dead_key")


def test_organization_identifier_writer_guard_rejects_unreachable_guarded_match_cases(tmp_path: Path) -> None:
    """A literal-false branch must not certify a writer or consume fall-through."""
    unreachable_guard_function = _parse_single_function(
        """
def build_person(row):
    identifiers = {}
    identifiers["dead_key"] = row.person_id
    match row.kind:
        case _ if False:
            return Organization(identifiers=identifiers)
    return None
"""
    )
    always_taken_guard_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {"dead_key": row.person_id}
    match row.kind:
        case _ if True:
            identifiers = {}
    return Organization(identifiers=identifiers)
"""
    )
    unreachable_if_function = _parse_single_function(
        """
def build_person(row):
    identifiers = {"dead_key": row.person_id}
    if False:
        return Organization(identifiers=identifiers)
    return None
"""
    )
    unreachable_direct_literal_path = tmp_path / "unreachable_direct_literal.py"
    unreachable_direct_literal_path.write_text(
        """
def build_person(row):
    if False:
        return Organization(identifiers={"dead_key": row.person_id})
    return None
""",
        encoding="utf-8",
    )

    assert not _function_writes_key_to_organization_identifiers(unreachable_guard_function, "dead_key")
    assert not _function_writes_key_to_organization_identifiers(always_taken_guard_function, "dead_key")
    assert not _function_writes_key_to_organization_identifiers(unreachable_if_function, "dead_key")
    from core.entity_resolution.test_splink_config import _writes_key_to_organization_identifiers

    assert not _writes_key_to_organization_identifiers(unreachable_direct_literal_path, "dead_key")


def test_organization_identifier_writer_guard_propagates_nested_exception_states() -> None:
    """A write on a nested terminating path must still reach an enclosing except handler."""
    uncaught_raise_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    if row.is_person:
        identifiers["dead_key"] = row.person_id
        raise RetryableRowError(row)
    return Organization(identifiers=identifiers)
"""
    )
    caught_writer_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        if row.has_committee:
            identifiers["fec_committee_id"] = row.committee_id
            raise RetryableRowError(row)
    except RetryableRowError:
        return Organization(identifiers=identifiers)
    return None
"""
    )

    assert _function_writes_key_to_organization_identifiers(caught_writer_function, "fec_committee_id")
    assert not _function_writes_key_to_organization_identifiers(uncaught_raise_function, "dead_key")


def test_organization_identifier_writer_guard_rejects_stale_try_except_states() -> None:
    """Only states that can raise inside the try body may enter an except handler."""
    stale_rebind_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["dead_key"] = row.person_id
        identifiers = {}
    except RetryableRowError:
        return Organization(identifiers=identifiers)
    return None
"""
    )
    caught_writer_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        if row.has_committee:
            identifiers["fec_committee_id"] = row.committee_id
            raise RetryableRowError(row)
    except RetryableRowError:
        return Organization(identifiers=identifiers)
    return None
"""
    )

    assert not _function_writes_key_to_organization_identifiers(stale_rebind_function, "dead_key")
    assert _function_writes_key_to_organization_identifiers(caught_writer_function, "fec_committee_id")


def test_organization_identifier_writer_guard_rejects_stale_try_finally_states() -> None:
    """Finally writer evidence must use true exception exits, not every intermediate state."""
    stale_finally_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["dead_key"] = row.person_id
        identifiers = {}
    finally:
        return Organization(identifiers=identifiers)
"""
    )
    live_exception_finally_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        raise RetryableRowError(row)
    finally:
        return Organization(identifiers=identifiers)
"""
    )

    assert not _function_writes_key_to_organization_identifiers(stale_finally_function, "dead_key")
    assert _function_writes_key_to_organization_identifiers(
        live_exception_finally_function,
        "fec_committee_id",
    )


def test_organization_identifier_writer_guard_reaches_handlers_from_implicit_raises() -> None:
    """A try body that raises only implicitly must still vouch for its handler writers."""
    implicit_raise_except_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        validate_committee(row)
    except CommitteeValidationError:
        return Organization(identifiers=identifiers)
    return None
"""
    )
    implicit_raise_finally_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        validate_committee(row)
        identifiers = {}
    finally:
        return Organization(identifiers=identifiers)
"""
    )

    assert _function_writes_key_to_organization_identifiers(
        implicit_raise_except_function,
        "fec_committee_id",
    )
    assert _function_writes_key_to_organization_identifiers(
        implicit_raise_finally_function,
        "fec_committee_id",
    )


def test_organization_identifier_writer_guard_routes_explicit_raises_to_matching_handlers() -> None:
    """Known explicit raises must not enter incompatible typed handlers."""
    mismatched_handler_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["dead_key"] = row.person_id
        raise ValueError(row)
    except KeyError:
        return Organization(identifiers=identifiers)
    return None
"""
    )
    matching_handler_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        raise ValueError(row)
    except ValueError:
        return Organization(identifiers=identifiers)
    return None
"""
    )
    implicit_raise_handler_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        validate_committee(row)
    except ValueError:
        return Organization(identifiers=identifiers)
    return None
"""
    )

    assert not _function_writes_key_to_organization_identifiers(mismatched_handler_function, "dead_key")
    assert _function_writes_key_to_organization_identifiers(matching_handler_function, "fec_committee_id")
    assert _function_writes_key_to_organization_identifiers(
        implicit_raise_handler_function,
        "fec_committee_id",
    )


def test_organization_identifier_writer_guard_routes_explicit_raises_to_superclass_handlers() -> None:
    """Known explicit raises must enter handlers for their Python superclasses."""
    superclass_handler_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        raise ValueError(row)
    except Exception:
        return Organization(identifiers=identifiers)
    return None
"""
    )

    assert _function_writes_key_to_organization_identifiers(
        superclass_handler_function,
        "fec_committee_id",
    )


def test_organization_identifier_writer_guard_treats_dynamic_raises_as_unknown() -> None:
    """A raised local value may hold an exception accepted by a typed handler."""
    dynamic_raise_function = _parse_single_function(
        """
def build_organization(row, error):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        raise error
    except ValueError:
        return Organization(identifiers=identifiers)
    return None
"""
    )
    dynamic_factory_raise_function = _parse_single_function(
        """
def build_organization(row, make_error):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        raise make_error()
    except ValueError:
        return Organization(identifiers=identifiers)
    return None
"""
    )

    for function in (dynamic_raise_function, dynamic_factory_raise_function):
        assert _function_writes_key_to_organization_identifiers(
            function,
            "fec_committee_id",
        )


def test_organization_identifier_writer_guard_propagates_uncaught_nested_try_exits() -> None:
    """An unmatched inner exception must remain available to an outer handler."""
    outer_handler_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        try:
            identifiers["fec_committee_id"] = row.committee_id
            raise ValueError(row)
        except KeyError:
            return None
    except ValueError:
        return Organization(identifiers=identifiers)
    return None
"""
    )

    assert _function_writes_key_to_organization_identifiers(
        outer_handler_function,
        "fec_committee_id",
    )


def test_organization_identifier_writer_guard_consumes_implicit_exits_caught_by_baseexception() -> None:
    """A BaseException handler prevents its caught unknown exit reaching outer handlers."""
    fully_caught_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        try:
            identifiers["dead_key"] = row.person_id
            validate_committee(row)
        except BaseException:
            return None
    except ValueError:
        return Organization(identifiers=identifiers)
    return None
"""
    )

    assert not _function_writes_key_to_organization_identifiers(
        fully_caught_function,
        "dead_key",
    )


def test_organization_identifier_writer_guard_reaches_finally_from_return_exit() -> None:
    """Return exits through a finally body must preserve or override flow correctly."""
    implicit_return_finally_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["fec_committee_id"] = row.committee_id
        return row
    finally:
        return Organization(identifiers=identifiers)
"""
    )
    stale_return_finally_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        identifiers["dead_key"] = row.person_id
        identifiers = {}
        return row
    finally:
        return Organization(identifiers=identifiers)
"""
    )
    exception_overridden_by_return_function = _parse_single_function(
        """
def build_organization(row):
    identifiers = {}
    try:
        try:
            identifiers["fec_committee_id"] = row.committee_id
            raise CommitteeValidationError(row)
        finally:
            return row
    finally:
        return Organization(identifiers=identifiers)
"""
    )

    assert _function_writes_key_to_organization_identifiers(
        implicit_return_finally_function,
        "fec_committee_id",
    )
    assert not _function_writes_key_to_organization_identifiers(
        stale_return_finally_function,
        "dead_key",
    )
    assert _function_writes_key_to_organization_identifiers(
        exception_overridden_by_return_function,
        "fec_committee_id",
    )
