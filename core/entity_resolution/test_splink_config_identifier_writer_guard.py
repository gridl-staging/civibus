"""Deterministic identifier-writer guards for Splink configuration."""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
from pathlib import Path

from test_support.line_budget import HARD_LINE_LIMIT, oversized_modules

_SPLINK_TEST_MODULE_PATTERN = "test_*splink_config*.py"


def test_splink_config_test_modules_stay_under_hard_line_limit() -> None:
    """Focused test owners must remain at or below the repository hard limit."""
    test_modules = sorted(Path(__file__).parent.glob(_SPLINK_TEST_MODULE_PATTERN))

    assert test_modules, f"Splink config test-module glob matched nothing: {_SPLINK_TEST_MODULE_PATTERN}"

    offenders = oversized_modules(test_modules)

    assert not offenders, f"Splink config test modules exceed {HARD_LINE_LIMIT} lines: {offenders}"


def test_deterministic_identifier_writer_guard_stays_in_existing_owner() -> None:
    """The deterministic-rule scan and evidence predicates belong in the original owner."""
    from core.entity_resolution import test_splink_config as owner

    assert owner.DETERMINISTIC_ORG_RULES
    owned_functions = (
        owner._identifier_keys_named_in_deterministic_rules,
        owner._production_files_that_could_write_identifiers,
        owner._writes_key_to_organization_identifiers,
    )
    assert {function.__module__ for function in owned_functions} == {owner.__name__}


def _constant_string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _subscript_key(node: ast.Subscript) -> str | None:
    return _constant_string_value(node.slice)


def _dict_literal_contains_key(node: ast.AST, key: str) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    return any(
        _dict_expression_can_contain_key(value, key) if dict_key is None else _constant_string_value(dict_key) == key
        for dict_key, value in zip(node.keys, node.values, strict=True)
    )


def _dict_expression_can_contain_key(node: ast.AST, key: str) -> bool:
    if _dict_literal_contains_key(node, key):
        return True
    if isinstance(node, ast.IfExp):
        return _dict_expression_can_contain_key(node.body, key) or _dict_expression_can_contain_key(
            node.orelse,
            key,
        )
    if isinstance(node, ast.Call):
        if _call_name(node.func) == "dict" and any(keyword.arg == key for keyword in node.keywords):
            return True
        values = [*node.args, *(keyword.value for keyword in node.keywords)]
        return any(_dict_expression_can_contain_key(value, key) for value in values)
    return False


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _organization_call_identifier_argument(call: ast.Call) -> ast.AST | None:
    if _call_name(call.func) != "Organization":
        return None
    for keyword in call.keywords:
        if keyword.arg == "identifiers":
            return keyword.value
    return None


def _assigns_key_to_local_identifiers(node: ast.AST, key: str) -> bool:
    targets: list[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    elif isinstance(node, ast.AugAssign):
        targets = [node.target]

    for target in targets:
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "identifiers"
            and _subscript_key(target) == key
        ):
            return True
    return False


def _updates_local_identifiers_with_key(node: ast.AST, key: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "update":
        return False
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "identifiers":
        return False
    return any(keyword.arg == key for keyword in node.keywords) or any(
        _dict_expression_can_contain_key(argument, key) for argument in node.args
    )


def _local_identifiers_assignment_contains_key(node: ast.AST, key: str) -> bool | None:
    if isinstance(node, ast.Assign):
        targets = node.targets
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
        value = node.value
    else:
        return None

    if value is None:
        return None
    for target in targets:
        if isinstance(target, ast.Name) and target.id == "identifiers":
            return _dict_expression_can_contain_key(value, key)
    return None


def _walk_without_nested_scopes(node: ast.AST) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    nested_scope_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

    def visit(current_node: ast.AST) -> None:
        nodes.append(current_node)
        if current_node is not node and isinstance(current_node, nested_scope_types):
            return
        for child in ast.iter_child_nodes(current_node):
            visit(child)

    visit(node)
    return nodes


def _expression_writes_key_to_organization_identifiers(
    node: ast.AST | None,
    key: str,
    identifiers_contains_key: bool,
) -> bool:
    if node is None:
        return False
    for expression_node in _walk_without_nested_scopes(node):
        if not isinstance(expression_node, ast.Call):
            continue
        identifier_argument = _organization_call_identifier_argument(expression_node)
        if identifier_argument is not None and _dict_expression_can_contain_key(identifier_argument, key):
            return True
        if (
            identifiers_contains_key
            and isinstance(identifier_argument, ast.Name)
            and identifier_argument.id == "identifiers"
        ):
            return True
    return False


def _statement_updates_identifier_state(statement: ast.stmt, key: str, identifiers_contains_key: bool) -> bool:
    assigned_key_state = _local_identifiers_assignment_contains_key(statement, key)
    if assigned_key_state is not None:
        return assigned_key_state
    if _assigns_key_to_local_identifiers(statement, key):
        return True
    for node in _walk_without_nested_scopes(statement):
        if _updates_local_identifiers_with_key(node, key):
            return True
    return identifiers_contains_key


_NESTED_STATEMENT_PARTS = (ast.stmt, ast.excepthandler, ast.match_case)

_IMPLICITLY_RAISING_NODES = (ast.Call, ast.Attribute, ast.Subscript, ast.BinOp, ast.Await)


def _statement_own_expression_nodes(statement: ast.stmt) -> list[ast.AST]:
    """Nodes the statement itself evaluates, excluding nested bodies and lambdas.

    Nested statement bodies are analyzed separately and report their own
    exception exits, and a lambda body runs only once the lambda is called.
    """
    nodes: list[ast.AST] = []
    pending = [child for child in ast.iter_child_nodes(statement) if not isinstance(child, _NESTED_STATEMENT_PARTS)]
    while pending:
        node = pending.pop()
        nodes.append(node)
        if isinstance(node, ast.Lambda):
            continue
        pending.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, _NESTED_STATEMENT_PARTS))
    return nodes


def _statement_can_raise_implicitly(statement: ast.stmt) -> bool:
    """Whether evaluating the statement's own expressions can raise.

    Calls, attribute access, subscripting, arithmetic, and awaits raise in
    practice; loading a bare name or building a literal container does not, so a
    plain ``identifiers = {}`` rebind never hands its state to an exception path.
    """
    if isinstance(statement, ast.Raise):
        return False
    return any(isinstance(node, _IMPLICITLY_RAISING_NODES) for node in _statement_own_expression_nodes(statement))


@dataclass(frozen=True)
class _ExceptionExit:
    identifiers_contains_key: bool
    exception_type: str | None


def _exception_exits_from_states(states: set[bool], exception_type: str | None = None) -> set[_ExceptionExit]:
    return {_ExceptionExit(state, exception_type) for state in states}


def _exception_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Call):
        return _exception_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _raised_exception_name(node: ast.AST | None) -> str | None:
    """Return a statically known raised type, leaving dynamic values unknown."""
    exception_target = node.func if isinstance(node, ast.Call) else node
    if not isinstance(exception_target, ast.Name):
        return None
    exception_class = getattr(builtins, exception_target.id, None)
    if isinstance(exception_class, type) and issubclass(exception_class, BaseException):
        return exception_target.id
    return None


def _handler_exception_names(handler: ast.ExceptHandler) -> set[str] | None:
    if handler.type is None:
        return None
    if isinstance(handler.type, ast.Tuple):
        return {name for element in handler.type.elts if (name := _exception_name(element)) is not None}
    handler_name = _exception_name(handler.type)
    return {handler_name} if handler_name is not None else set()


def _handler_catches_exception_exit(handler: ast.ExceptHandler, exception_exit: _ExceptionExit) -> bool:
    handler_names = _handler_exception_names(handler)
    if handler_names is None:
        return True
    if exception_exit.exception_type is None:
        return True
    if exception_exit.exception_type in handler_names:
        return True

    exception_class = getattr(builtins, exception_exit.exception_type, None)
    if not isinstance(exception_class, type) or not issubclass(exception_class, BaseException):
        return False
    for handler_name in handler_names:
        handler_class = getattr(builtins, handler_name, None)
        if isinstance(handler_class, type) and issubclass(handler_class, BaseException):
            if issubclass(exception_class, handler_class):
                return True
    return False


def _handler_fully_consumes_exception_exit(
    handler: ast.ExceptHandler,
    exception_exit: _ExceptionExit,
) -> bool:
    if not _handler_catches_exception_exit(handler, exception_exit):
        return False
    handler_names = _handler_exception_names(handler)
    return (
        handler.type is None
        or exception_exit.exception_type is not None
        or (handler_names is not None and "BaseException" in handler_names)
    )


@dataclass
class _IdentifierFlow:
    """Identifier-key states an analyzed block can leave behind.

    ``reachable`` includes terminating paths observable by ``finally``;
    the other sets classify the way states leave the block.
    """

    found_writer: bool
    reachable: set[bool]
    exception_exits: set[_ExceptionExit]
    continuing: set[bool]
    returns: set[bool]
    breaks: set[bool]
    continues: set[bool]


def _writer_found_flow() -> _IdentifierFlow:
    return _IdentifierFlow(True, set(), set(), set(), set(), set(), set())


def _pass_through_flow(starting_states: set[bool]) -> _IdentifierFlow:
    return _IdentifierFlow(False, set(starting_states), set(), set(starting_states), set(), set(), set())


def _merge_branch_flow(merged: _IdentifierFlow, branch: _IdentifierFlow) -> None:
    """Fold one alternative execution path into the merged flow of a statement."""
    merged.reachable.update(branch.reachable)
    merged.exception_exits.update(branch.exception_exits)
    if branch.found_writer:
        merged.found_writer = True
        return
    merged.continuing.update(branch.continuing)
    merged.returns.update(branch.returns)
    merged.breaks.update(branch.breaks)
    merged.continues.update(branch.continues)


def _analyze_identifier_writer_statements(
    statements: list[ast.stmt],
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    reachable = set(starting_states)
    exception_exits: set[_ExceptionExit] = set()
    continuing = set(starting_states)
    returns: set[bool] = set()
    breaks: set[bool] = set()
    continues: set[bool] = set()
    for statement in statements:
        flow = _analyze_identifier_writer_statement(statement, key, continuing)
        reachable.update(flow.reachable)
        if flow.found_writer:
            return _writer_found_flow()
        exception_exits.update(flow.exception_exits)
        if _statement_can_raise_implicitly(statement):
            # The statement can raise part-way through, so the states entering it
            # are observable by an enclosing handler even without an explicit raise.
            exception_exits.update(_exception_exits_from_states(continuing))
        continuing = flow.continuing
        returns.update(flow.returns)
        breaks.update(flow.breaks)
        continues.update(flow.continues)
        if not continuing:
            break
    return _IdentifierFlow(False, reachable, exception_exits, continuing, returns, breaks, continues)


def _analyze_if_statement(
    statement: ast.If,
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    if isinstance(statement.test, ast.Constant):
        selected_branch = statement.body if bool(statement.test.value) else statement.orelse
        if selected_branch:
            return _analyze_identifier_writer_statements(selected_branch, key, starting_states)
        return _pass_through_flow(starting_states)

    merged = _IdentifierFlow(False, set(starting_states), set(), set(), set(), set(), set())
    for identifiers_contains_key in starting_states:
        _merge_branch_flow(
            merged,
            _analyze_identifier_writer_statements(statement.body, key, {identifiers_contains_key}),
        )
        if merged.found_writer:
            return _writer_found_flow()

        if statement.orelse:
            _merge_branch_flow(
                merged,
                _analyze_identifier_writer_statements(statement.orelse, key, {identifiers_contains_key}),
            )
            if merged.found_writer:
                return _writer_found_flow()
        else:
            merged.continuing.add(identifiers_contains_key)

    return merged


def _literal_while_test_truthiness(statement: ast.For | ast.AsyncFor | ast.While) -> bool | None:
    if isinstance(statement, ast.While) and isinstance(statement.test, ast.Constant):
        return bool(statement.test.value)
    return None


def _literal_for_iterable_cardinality(statement: ast.For | ast.AsyncFor | ast.While) -> int | None:
    if not isinstance(statement, (ast.For, ast.AsyncFor)):
        return None
    if isinstance(statement.iter, (ast.List, ast.Tuple)):
        if any(isinstance(element, ast.Starred) for element in statement.iter.elts):
            return None
        return len(statement.iter.elts)
    if not isinstance(statement.iter, (ast.Set, ast.Dict)):
        return None
    optional_elements = statement.iter.elts if isinstance(statement.iter, ast.Set) else statement.iter.keys
    if any(element is None or isinstance(element, ast.Starred) for element in optional_elements):
        return None
    elements = [element for element in optional_elements if element is not None]
    if len(elements) <= 1:
        return len(elements)
    try:
        return len({ast.literal_eval(element) for element in elements})
    except (TypeError, ValueError):
        return None


def _analyze_loop_statement(
    statement: ast.For | ast.AsyncFor | ast.While,
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    literal_for_iterable_cardinality = _literal_for_iterable_cardinality(statement)
    if literal_for_iterable_cardinality == 0:
        if statement.orelse:
            return _analyze_identifier_writer_statements(statement.orelse, key, starting_states)
        return _pass_through_flow(starting_states)

    literal_while_truthiness = _literal_while_test_truthiness(statement)
    if literal_while_truthiness is False:
        if statement.orelse:
            return _analyze_identifier_writer_statements(statement.orelse, key, starting_states)
        return _pass_through_flow(starting_states)

    reachable = set(starting_states)
    body_entry_states = set(starting_states)
    analyzed_entry_states: set[bool] = set()
    normal_completion_states = (
        set()
        if literal_while_truthiness is True or literal_for_iterable_cardinality is not None
        else set(starting_states)
    )
    exception_exit_states: set[_ExceptionExit] = set()
    return_exit_states: set[bool] = set()
    break_exit_states: set[bool] = set()

    completed_iterations = 0
    while unanalyzed_states := body_entry_states - analyzed_entry_states:
        if literal_for_iterable_cardinality is not None and completed_iterations == literal_for_iterable_cardinality:
            break
        completed_iterations += 1
        analyzed_entry_states.update(unanalyzed_states)
        body_flow = _analyze_identifier_writer_statements(statement.body, key, unanalyzed_states)
        reachable.update(body_flow.reachable)
        if body_flow.found_writer:
            return _writer_found_flow()
        next_iteration_states = body_flow.continuing | body_flow.continues
        if literal_for_iterable_cardinality is None:
            body_entry_states.update(next_iteration_states)
        else:
            body_entry_states = next_iteration_states
        exception_exit_states.update(body_flow.exception_exits)
        return_exit_states.update(body_flow.returns)
        break_exit_states.update(body_flow.breaks)
        if literal_for_iterable_cardinality is not None:
            normal_completion_states = set(next_iteration_states)
        elif literal_while_truthiness is not True:
            normal_completion_states.update(next_iteration_states)

    if statement.orelse:
        else_flow = _analyze_identifier_writer_statements(statement.orelse, key, normal_completion_states)
        reachable.update(else_flow.reachable)
        if else_flow.found_writer:
            return _writer_found_flow()
        loop_exit_states = break_exit_states | else_flow.continuing | else_flow.breaks
        return _IdentifierFlow(
            False,
            reachable,
            exception_exit_states | else_flow.exception_exits,
            loop_exit_states,
            return_exit_states | else_flow.returns,
            set(),
            else_flow.continues,
        )
    return _IdentifierFlow(
        False,
        reachable,
        exception_exit_states,
        normal_completion_states | break_exit_states,
        return_exit_states,
        set(),
        set(),
    )


def _analyze_with_statement(
    statement: ast.With | ast.AsyncWith,
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    return _analyze_identifier_writer_statements(statement.body, key, starting_states)


def _analyze_try_statement(
    statement: ast.Try,
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    body_flow = _analyze_identifier_writer_statements(statement.body, key, starting_states)
    if body_flow.found_writer:
        return _writer_found_flow()

    merged = _IdentifierFlow(
        False,
        set(body_flow.reachable),
        set(),
        set(),
        set(body_flow.returns),
        set(body_flow.breaks),
        set(body_flow.continues),
    )
    if statement.orelse:
        _merge_branch_flow(
            merged,
            _analyze_identifier_writer_statements(statement.orelse, key, body_flow.continuing),
        )
        if merged.found_writer:
            return _writer_found_flow()
    else:
        merged.continuing.update(body_flow.continuing)

    uncaught_exception_exits = set(body_flow.exception_exits)
    for handler in statement.handlers:
        caught_exception_exits = {
            exception_exit
            for exception_exit in uncaught_exception_exits
            if _handler_catches_exception_exit(handler, exception_exit)
        }
        handler_entry_states = {exception_exit.identifiers_contains_key for exception_exit in caught_exception_exits}
        _merge_branch_flow(
            merged,
            _analyze_identifier_writer_statements(handler.body, key, handler_entry_states),
        )
        if merged.found_writer:
            return _writer_found_flow()
        uncaught_exception_exits = {
            exception_exit
            for exception_exit in uncaught_exception_exits
            if not _handler_fully_consumes_exception_exit(handler, exception_exit)
        }

    merged.exception_exits.update(uncaught_exception_exits)

    if not statement.finalbody:
        return merged
    return _analyze_finally_block(statement.finalbody, key, merged)


def _analyze_finally_block(
    finalbody: list[ast.stmt],
    key: str,
    try_flow: _IdentifierFlow,
) -> _IdentifierFlow:
    """Run the finally body once per exit path the guarded try can take.

    The exception path is analyzed for writer evidence only: the exception keeps
    propagating afterwards, so its states must not fall through past the try.
    """
    exception_path = _analyze_exception_finally_path(finalbody, key, try_flow.exception_exits)
    normal_path = _analyze_identifier_writer_statements(finalbody, key, try_flow.continuing)
    return_path = _analyze_identifier_writer_statements(finalbody, key, try_flow.returns)
    break_path = _analyze_identifier_writer_statements(finalbody, key, try_flow.breaks)
    continue_path = _analyze_identifier_writer_statements(finalbody, key, try_flow.continues)

    reachable = set(try_flow.reachable)
    for path in (exception_path, normal_path, return_path, break_path, continue_path):
        reachable.update(path.reachable)
        if path.found_writer:
            return _writer_found_flow()

    returns = (
        exception_path.returns
        | normal_path.returns
        | return_path.continuing
        | return_path.returns
        | break_path.returns
        | continue_path.returns
    )
    breaks = (
        exception_path.breaks
        | normal_path.breaks
        | return_path.breaks
        | break_path.continuing
        | break_path.breaks
        | continue_path.breaks
    )
    continues = (
        exception_path.continues
        | normal_path.continues
        | return_path.continues
        | continue_path.continuing
        | continue_path.continues
        | break_path.continues
    )
    exception_exits = set(exception_path.exception_exits)
    exception_exits.update(normal_path.exception_exits)
    exception_exits.update(return_path.exception_exits)
    exception_exits.update(break_path.exception_exits)
    exception_exits.update(continue_path.exception_exits)
    return _IdentifierFlow(False, reachable, exception_exits, normal_path.continuing, returns, breaks, continues)


def _analyze_exception_finally_path(
    finalbody: list[ast.stmt],
    key: str,
    exception_exits: set[_ExceptionExit],
) -> _IdentifierFlow:
    merged = _IdentifierFlow(False, set(), set(), set(), set(), set(), set())
    for exception_exit in exception_exits:
        path = _analyze_identifier_writer_statements(finalbody, key, {exception_exit.identifiers_contains_key})
        _merge_branch_flow(merged, path)
        if merged.found_writer:
            return _writer_found_flow()
        merged.exception_exits.update(_ExceptionExit(state, exception_exit.exception_type) for state in path.continuing)
    merged.continuing.clear()
    return merged


def _match_pattern_is_irrefutable(pattern: ast.pattern) -> bool:
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None or _match_pattern_is_irrefutable(pattern.pattern)
    if isinstance(pattern, ast.MatchOr):
        return any(_match_pattern_is_irrefutable(alternative) for alternative in pattern.patterns)
    return False


def _match_case_guard_truthiness(match_case: ast.match_case) -> bool | None:
    """Whether a case guard is a literal that always holds, never holds, or is unknown."""
    if match_case.guard is None:
        return True
    if isinstance(match_case.guard, ast.Constant):
        return bool(match_case.guard.value)
    return None


def _analyze_match_statement(
    statement: ast.Match,
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    merged = _IdentifierFlow(False, set(starting_states), set(), set(), set(), set(), set())
    has_unconditional_case = False
    for match_case in statement.cases:
        guard_truthiness = _match_case_guard_truthiness(match_case)
        if guard_truthiness is False:
            continue
        _merge_branch_flow(
            merged,
            _analyze_identifier_writer_statements(match_case.body, key, starting_states),
        )
        if merged.found_writer:
            return _writer_found_flow()
        if guard_truthiness is True and _match_pattern_is_irrefutable(match_case.pattern):
            has_unconditional_case = True
            break

    if not has_unconditional_case:
        merged.continuing.update(starting_states)
    return merged


def _analyze_simple_statement(
    statement: ast.stmt,
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    reachable = set(starting_states)
    exception_exits: set[_ExceptionExit] = set()
    continuing: set[bool] = set()
    returns: set[bool] = set()
    for identifiers_contains_key in starting_states:
        if _expression_writes_key_to_organization_identifiers(statement, key, identifiers_contains_key):
            return _writer_found_flow()
        next_state = _statement_updates_identifier_state(statement, key, identifiers_contains_key)
        reachable.add(next_state)
        if isinstance(statement, ast.Raise):
            exception_exits.add(_ExceptionExit(next_state, _raised_exception_name(statement.exc)))
        elif isinstance(statement, ast.Assert):
            literal_truthiness = bool(statement.test.value) if isinstance(statement.test, ast.Constant) else None
            if literal_truthiness is not True:
                exception_exits.add(_ExceptionExit(next_state, "AssertionError"))
            if literal_truthiness is not False:
                continuing.add(next_state)
        elif isinstance(statement, ast.Return):
            returns.add(next_state)
        else:
            continuing.add(next_state)
    return _IdentifierFlow(False, reachable, exception_exits, continuing, returns, set(), set())


def _analyze_identifier_writer_statement(
    statement: ast.stmt,
    key: str,
    starting_states: set[bool],
) -> _IdentifierFlow:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return _pass_through_flow(starting_states)
    if isinstance(statement, ast.If):
        return _analyze_if_statement(statement, key, starting_states)
    if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
        return _analyze_loop_statement(statement, key, starting_states)
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return _analyze_with_statement(statement, key, starting_states)
    if isinstance(statement, ast.Try):
        return _analyze_try_statement(statement, key, starting_states)
    if isinstance(statement, ast.Match):
        return _analyze_match_statement(statement, key, starting_states)
    if isinstance(statement, ast.Break):
        return _IdentifierFlow(False, set(starting_states), set(), set(), set(), set(starting_states), set())
    if isinstance(statement, ast.Continue):
        return _IdentifierFlow(False, set(starting_states), set(), set(), set(), set(), set(starting_states))
    return _analyze_simple_statement(statement, key, starting_states)


def _function_writes_key_to_organization_identifiers(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    key: str,
) -> bool:
    return _analyze_identifier_writer_statements(function_node.body, key, {False}).found_writer
