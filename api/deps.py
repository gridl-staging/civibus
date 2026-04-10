from __future__ import annotations

from collections.abc import Generator
from contextlib import ExitStack

import psycopg
from fastapi import HTTPException, Request
from psycopg_pool import PoolTimeout


def get_db(request: Request) -> Generator[psycopg.Connection, None, None]:
    with ExitStack() as stack:
        try:
            connection = stack.enter_context(request.app.state.db_pool.connection())
        except (psycopg.Error, PoolTimeout) as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        yield connection
