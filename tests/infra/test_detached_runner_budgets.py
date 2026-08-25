"""Contract tests for tests/infra/detached_runner_budgets.py.

These exercise the shell-constant readers and the readiness window they derive,
none of which launches the runner. The runner's own start/wait/status contracts
live in tests/infra/test_detached_runner.py.
"""

from __future__ import annotations

import re

import pytest

from tests.infra.detached_runner_budgets import (
    _READY_WINDOW_SECONDS,
    _READY_WINDOW_WALL_SECONDS,
    _read_shell_constant,
    _shell_library_source,
)


def test_cadence_constant_reader_raises_when_the_constant_is_absent() -> None:
    """A renamed or deleted cadence constant must red, never fall back healthy.

    This comes out red the moment `_read_shell_constant` grows a default or a
    `try/except` that returns a number: the budgets derived from the readiness
    window would then keep their stale hand-copied values while the runner
    polled on a cadence nobody had checked against them.
    """
    with pytest.raises(AssertionError) as raised:
        _read_shell_constant("detached_runner_launch_lib.sh", "WRAPPER_READY_ATTEMPTS_RENAMED")

    assert "detached_runner_launch_lib.sh" in str(raised.value)
    assert "WRAPPER_READY_ATTEMPTS_RENAMED" in str(raised.value)


def test_cadence_constant_reader_raises_when_the_cadence_value_is_unparseable() -> None:
    """A constant that is declared but not numeric must raise, not be coerced.

    `runner_script` is the live specimen: detached_runner.sh declares it as
    `"${BASH_SOURCE[0]}"`, which satisfies the assignment pattern and is not a
    number, so it exercises the parse failure without a synthetic fixture.
    """
    with pytest.raises(AssertionError) as raised:
        _read_shell_constant("detached_runner.sh", "runner_script")

    assert "detached_runner.sh" in str(raised.value)
    assert "runner_script" in str(raised.value)
    # Discriminate the parse-failure branch from the no-match branch: both
    # branches name the file and the constant, so without a parse-specific
    # fragment this test would still pass if the live `runner_script=` specimen
    # ever drifted and the no-match branch fired instead -- and it would then
    # stop proving that a declared-but-non-numeric constant raises rather than
    # being coerced. "is not a number" and the offending token appear only in
    # the parse-failure message.
    assert "is not a number" in str(raised.value)
    assert "BASH_SOURCE" in str(raised.value)


def test_ready_window_derives_from_the_declared_cadence_constants() -> None:
    """Pin the declared cadence values and the window every derived budget uses.

    Red if either owner retunes its constant without the derived budgets being
    re-checked against the new window, and red if the reader ever returns
    something other than what the shell files actually declare.
    """
    assert _read_shell_constant("detached_runner_launch_lib.sh", "WRAPPER_READY_ATTEMPTS") == 100.0
    assert _read_shell_constant("detached_runner_ownership_lib.sh", "FAST_POLL_INTERVAL_SECONDS") == 0.05
    assert _READY_WINDOW_SECONDS == 5.0
    assert _READY_WINDOW_WALL_SECONDS == 6.0


def test_readiness_poll_pairs_the_cadence_constants_the_window_derives_from() -> None:
    """Pin the poll site the derived window assumes, not just the constants.

    `_READY_WINDOW_SECONDS` multiplies these two constants because
    `wait_for_wrapper_ready` pairs them. Repointing that poll at another cadence
    constant -- `DEFAULT_POLL_INTERVAL_SECONDS` (0.1) is already in scope there --
    leaves both constants declared and parseable, so the fail-closed reader stays
    green while every derived budget silently describes half the real window.
    This is the assertion that comes out red for that edit.
    """
    poll_call = re.compile(
        r'^\s*poll_until "\$\{WRAPPER_READY_ATTEMPTS\}" "\$\{FAST_POLL_INTERVAL_SECONDS\}"',
        re.MULTILINE,
    )

    assert poll_call.search(_shell_library_source("detached_runner_launch_lib.sh")), (
        "the wrapper-readiness poll no longer pairs WRAPPER_READY_ATTEMPTS with "
        "FAST_POLL_INTERVAL_SECONDS, so the budgets derived from their product "
        "no longer describe the readiness window"
    )
