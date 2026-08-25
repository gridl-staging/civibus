"""Cadence and budget facts the detached-runner tests derive from the runner's shell.

Split out of `tests/infra/detached_runner_helpers.py`: that module owns the
harness's process and fixture machinery, while this one owns the single reading
of the runner's declared shell constants and the readiness-window budgets every
timing-sensitive test derives from them. `SCRIPT_PATH` stays on the helper
module, which remains the one owner of where the runner lives.
"""

from __future__ import annotations

import re

from tests.infra.detached_runner_helpers import SCRIPT_PATH


def _shell_library_source(filename: str) -> str:
    """Read a runner shell file that sits beside the runner script.

    Single owner for that read, so a test pinning where a constant is declared
    and a test deriving a budget from its value never disagree about the path.
    """
    return (SCRIPT_PATH.parent / filename).read_text(encoding="utf-8")


def _declared_shell_constant_text(filename: str, name: str) -> str:
    """Return the raw token `filename` assigns to the shell constant `name`.

    Single owner of the assignment regex and the fail-closed no-match raise, so
    a numeric reader and an operator-visible-string check (e.g. `--help`) share
    one definition of how a constant is declared instead of drifting apart.
    """
    declared = re.search(rf"^{re.escape(name)}=(\S+)$", _shell_library_source(filename), re.MULTILINE)
    assert declared is not None, f"{filename} no longer declares {name}"
    return declared.group(1)


def _read_shell_constant(filename: str, name: str) -> float:
    """Return the number `filename` declares for the shell constant `name`.

    Fail-closed by construction: a renamed, deleted, or non-numeric constant
    raises rather than yielding a fallback. A silent fallback would leave the
    budgets below frozen at values that no longer describe the runner's cadence,
    which is exactly the stale hand-copied number this reader exists to retire.
    """
    token = _declared_shell_constant_text(filename, name)
    try:
        return float(token)
    except ValueError as error:
        raise AssertionError(f"{filename} declares {name}={token!r}, which is not a number") from error


# The wrapper-readiness window, derived from the two shell constants that define
# it rather than hand-copied: the runner sleeps `FAST_POLL_INTERVAL_SECONDS`
# between at most `WRAPPER_READY_ATTEMPTS` polls. Evaluated at import so renaming
# either constant reds collection of every module that derives a budget from it,
# not just the test that reads the constants directly.
_READY_WINDOW_SECONDS = _read_shell_constant(
    "detached_runner_launch_lib.sh", "WRAPPER_READY_ATTEMPTS"
) * _read_shell_constant("detached_runner_ownership_lib.sh", "FAST_POLL_INTERVAL_SECONDS")
# `attempts x interval` counts only the sleeps, so it is a *lower* bound on the
# window's wall time -- each poll also runs its predicate. The 100-poll window was
# measured at ~5.6s wall against its 5.0s nominal value, a ratio of 1.12; 1.2
# carries that with headroom for shared-host load. Budgets that must sit *below*
# the window take a fraction of the nominal value directly, because a lower bound
# is already the conservative side for them.
_READY_WINDOW_WALL_OVERHEAD = 1.2
# Single owner of the wall estimate every *upper* budget starts from, so changing
# the form of that estimate is one edit here rather than one per call site.
_READY_WINDOW_WALL_SECONDS = _READY_WINDOW_SECONDS * _READY_WINDOW_WALL_OVERHEAD


def _assert_ready_window_budget_ordering(subprocess_timeout: float, readiness_delay: float | None = None) -> float:
    """Assert a derived budget preserves the readiness-window ordering, then return it.

        readiness_delay < ready_window(nominal) <= ready_window(wall) < subprocess_timeout

    A retune of the 0.7 lower fraction, the 1.2 wall overhead, or the additive
    allowances that breaks this ordering reds here, naming the invariant, instead
    of surfacing later as a subprocess-timeout flake or a readiness test that no
    longer exercises delayed acceptance. Returns `subprocess_timeout` so it can
    wrap a budget expression inline at its single definition site.
    """
    # Split rather than chained: this module is not a pytest-rewritten test
    # module, so the only diagnostic a failure produces is the message string. A
    # chained condition would report the wall-vs-timeout half for a wall-vs-nominal
    # break too, printing a claim that is true of the numbers it names.
    assert _READY_WINDOW_SECONDS <= _READY_WINDOW_WALL_SECONDS, (
        f"wall window {_READY_WINDOW_WALL_SECONDS} must not sit below the nominal window {_READY_WINDOW_SECONDS}"
    )
    assert _READY_WINDOW_WALL_SECONDS < subprocess_timeout, (
        f"subprocess timeout {subprocess_timeout} must sit above the wall window {_READY_WINDOW_WALL_SECONDS}"
    )
    if readiness_delay is not None:
        assert readiness_delay < _READY_WINDOW_SECONDS, (
            f"readiness delay {readiness_delay} must sit below the nominal window {_READY_WINDOW_SECONDS}"
        )
    return subprocess_timeout
