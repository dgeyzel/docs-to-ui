# syntax=docker/dockerfile:1

# base: the app and its runtime dependencies.
FROM python:3.14-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev

# test: dev dependencies plus headless Chromium, for the full suite.
FROM base AS test
RUN uv sync --frozen --group dev \
    && playwright install --with-deps chromium
ENV PLAIN_DEBUG=true \
    PLAIN_SECRET_KEY=testing
CMD ["sh", "-c", "python scripts/sync_design.py --check && pytest && pytest -m e2e"]

# prod: compiled assets; run the web server and a worker from this image.
# The server binds to 0.0.0.0 inside the container only, so Docker can forward
# to it. Always publish the port on the host's loopback, never on all
# interfaces: docker run -p 127.0.0.1:8000:8000 ...
FROM base AS prod
RUN PLAIN_POSTGRES_URL=none PLAIN_SECRET_KEY=build-only PLAIN_TELEMETRY_BACKENDS='[]' \
    plain assets compile
EXPOSE 8000
CMD ["plain", "server", "--bind", "0.0.0.0:8000"]
