# syntax=docker/dockerfile:1

# base: the workspace (shared library and both apps) and runtime dependencies.
FROM python:3.14-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY docs_app/pyproject.toml docs_app/pyproject.toml
COPY tuning_app/pyproject.toml tuning_app/pyproject.toml
RUN uv sync --frozen --no-dev --all-packages --no-install-workspace
COPY . .
RUN uv sync --frozen --no-dev --all-packages

# test: dev dependencies plus headless Chromium, for the full suite.
FROM base AS test
RUN uv sync --frozen --all-packages \
    && playwright install --with-deps chromium
ENV PLAIN_DEBUG=true \
    PLAIN_SECRET_KEY=testing
CMD ["sh", "-c", "python scripts/sync_design.py --check && cd docs_app && pytest && pytest -m e2e && cd ../tuning_app && pytest"]

# prod: the Docs app with compiled assets; run the web server and a worker
# from this image. The server binds to 0.0.0.0 inside the container only, so
# Docker can forward to it. Always publish the port on the host's loopback,
# never on all interfaces: docker run -p 127.0.0.1:8000:8000 ...
FROM base AS prod
WORKDIR /repo/docs_app
RUN PLAIN_POSTGRES_URL=none PLAIN_SECRET_KEY=build-only PLAIN_TELEMETRY_BACKENDS='[]' \
    plain assets compile
EXPOSE 8000
CMD ["plain", "server", "--bind", "0.0.0.0:8000"]
