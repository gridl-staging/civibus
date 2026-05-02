"""Pre-startup canary for the API container.

Mechanical guard against the Apr 30 wrong-volume-bootstrap incident class:
the API container refuses to start if production tables are below their
content floors (or if the DB is unreachable past a deadline). The
container then never reaches uvicorn against an empty/wrong DB, so the
orchestrator's container-restart loop and external uptime probes both
notice the outage.

Skip via ``CIVIBUS_STARTUP_CANARY=skip`` for legitimate fresh-DB cases
(initial bootstrap, dev, ephemeral CI). Skip is *explicit* because
defaults must be safe — we never want a future operator to accidentally
relax the gate by leaving the env var blank.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

from api.health_content import evaluate_content_health, floors_from_env
from core.db import get_connection


_LOGGER = logging.getLogger("civibus.api.canary")


def _should_skip(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return source.get("CIVIBUS_STARTUP_CANARY", "").strip().lower() == "skip"


def _deadline_seconds() -> float:
    # Compose's ``depends_on: condition: service_healthy`` already gates the
    # API on a healthy DB, so the timeout only handles brief flapping at
    # boot. Keep it short so real outages fail fast instead of stalling
    # the orchestrator.
    raw = os.getenv("CIVIBUS_STARTUP_CANARY_TIMEOUT_SECONDS", "30")
    try:
        return float(raw)
    except ValueError:
        return 30.0


def main() -> int:
    """Return process exit code: 0 = healthy, 1 = refuse to start."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if _should_skip():
        _LOGGER.warning("startup canary SKIPPED via CIVIBUS_STARTUP_CANARY=skip")
        return 0

    floors = floors_from_env()
    deadline = time.monotonic() + _deadline_seconds()
    last_error: BaseException | None = None
    failures = None

    while True:
        try:
            connection = get_connection()
        except Exception as exc:  # noqa: BLE001 - canary must catch broadly.
            last_error = exc
            if time.monotonic() >= deadline:
                _LOGGER.error("startup canary: DB unreachable within deadline: %s", last_error)
                return 1
            time.sleep(1.0)
            continue

        try:
            failures = evaluate_content_health(connection, floors=floors)
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup.
                pass
        break

    if failures:
        _LOGGER.error(
            "startup canary REFUSING to start API; failed checks: %s",
            json.dumps([{"check": f.check, "actual": f.actual, "floor": f.floor} for f in failures]),
        )
        return 1

    _LOGGER.info("startup canary: all %d content floors satisfied", len(floors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
