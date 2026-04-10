FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY api ./api
COPY core ./core
COPY domains ./domains

RUN uv sync --locked --extra api \
    && groupadd --system --gid 10001 civibus \
    && useradd --system --uid 10001 --gid civibus --create-home --home-dir /home/civibus --shell /usr/sbin/nologin civibus \
    && chown -R civibus:civibus /app

USER civibus

EXPOSE 8000

CMD ["uv", "run", "--extra", "api", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
