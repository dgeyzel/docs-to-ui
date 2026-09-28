# Docs-to-UI

A single-user, local developer tool that turns an OpenAPI document or a Python codebase into a readable, navigable documentation page. You paste text or upload a file or `.zip`. The tool extracts the API structure with a real parser, asks an LLM (Gemini, through DSPy) to write summaries, descriptions and examples, and renders a styled page you can read in the app or export as a standalone HTML file. Every generation is traced end to end, and your 👍 / 👎 feedback feeds an offline optimization pipeline.

## About This Project

Docs-to-UI is built from two documents in this repository:

- [`SPEC.md`](SPEC.md) defines what to build: the architecture, contracts, settings and milestones.
- [`AGENTS.md`](AGENTS.md) defines how to build it: the rules every coding agent and contributor follows.

The visual design comes from an [OpenDesign](https://github.com/nexu-io/open-design) design-system package in `design/docs-to-ui/`, produced from [`DESIGN_BRIEF.md`](DESIGN_BRIEF.md). The app consumes only its `tokens.css`.

| Milestone | Scope | Status |
| --- | --- | --- |
| **M1** | OpenAPI adapter, rendering, HTML and JSON export, design-token sync, test harness | Done |
| **M2** | LLM enrichment and batching, background jobs with live progress, OpenTelemetry tracing, native trace viewer | Done |
| **M3** | Safe `.zip` input, Python adapter, multi-file OpenAPI `$ref`s, adapter contract suite | Done |
| **M4** | Feedback, evaluation datasets and metrics, `optimize.py`, `evals.yml` | Done, except the first promoted artifact (needs a real Gemini run) |
| **M5** | Langfuse tracing backend and feedback mirroring, containers, CI | Done |

Where the code differs from the spec, see [Development Status](#development-status).

## Features

### Generating documentation

- Paste text, or upload a single file or a `.zip` archive (up to 5 MB)
- **OpenAPI** 3.0 and 3.1, in JSON or YAML, as one file or many files linked by relative `$ref`s
- **Python** source, parsed with `ast` only: user code is never imported or run
- The language is detected automatically, or you can choose it
- For a zip with several OpenAPI entry files, choose one with the **Entry file** field
- Generation runs in a background job. The page shows a live stage stepper (Bundle → Extract → Enrich → Overview → Merge) and batch progress
- Invalid input fails with an error that names the file and line, for example `src/acme/client.py:12`
- **Retry** and **Regenerate** start a fresh generation from the stored input
- A history of recent generations with their status

### The doc page

- An overview and sidebar groups written by the LLM, validated against the extracted operations
- One card per operation: method badge or signature, summary, description, parameter table, code examples, return value and source location (`acme/client.py:42`)
- Operations whose LLM batch failed still render from the source's own descriptions, marked "Not enriched"
- Collapsible groups and cards, example tabs, copy buttons, active-section highlighting
- Light and dark themes: the app has a toggle, and exports follow the reader's system setting
- A print stylesheet that hides the sidebar and controls and wraps long code lines

### Export

- **HTML:** one self-contained file with every style and script inlined. It makes no network requests and works when opened straight from disk. It has no feedback controls, theme toggle or app links.
- **JSON:** the raw `DocPage` data behind the page.

### Feedback

- 👍 / 👎 on the whole page or on any single operation, with an optional correction comment
- Stored in the database, and mirrored to Langfuse as a score when that backend is active
- `optimize.py export-feedback` turns 👎 feedback with comments into dataset candidates for review

### Tracing

- Every request, job stage and LLM call is an OpenTelemetry span. Spans from the request, the job and DSPy share one trace ID
- **Native backend:** spans stored in Postgres and shown in the in-app trace viewer (trace list, waterfall timeline, span details and a dedicated LLM call view with messages and token counts)
- **Langfuse backend:** spans sent over OTLP and feedback sent as scores. Both backends can be active at once
- A summary strip on each generation page: LLM calls, total tokens, wall time and a **View trace** link
- Spans older than 30 days are pruned daily

### Quality measurement

- Versioned program artifacts in `artifacts/programs/`, selected with `LLM_PROGRAM_VERSION`
- Train and dev datasets for both languages, including multi-file zip inputs
- A metric with a schema gate, coverage, fidelity, judge-rated consistency, example validity and judge-rated prose quality
- `optimize.py` to evaluate a version or optimize a new one, and a manual `evals.yml` workflow

## Tech Stack

- **Web framework:** [Plain](https://plainframework.com/) (a Django fork) with Jinja2 templates, `plain.elements` components and `plain.htmx`
- **Database and jobs:** Postgres through `plain.postgres`, with `plain.jobs` for background work
- **LLM:** [DSPy](https://dspy.ai/) programs with Pydantic-typed signatures, calling Gemini through LiteLLM
- **Data models:** Pydantic v2 for every structure that crosses a boundary
- **Parsing:** PyYAML (`safe_load` semantics) for OpenAPI, Python's `ast` for Python, `zipfile` in memory for archives
- **Rendering:** markdown-it-py with output sanitized by nh3
- **Styling and scripts:** plain CSS with design-system custom properties (no Tailwind) and vanilla JavaScript
- **Observability:** OpenTelemetry SDK, `openinference-instrumentation-dspy`, a raw-psycopg span exporter, and the Langfuse SDK and OTLP exporter
- **Tooling:** uv, ruff and ty (through `plain code`), pytest, Playwright, Docker, GitHub Actions

## Requirements

- Linux or WSL (Ubuntu). Native Windows is not supported; see `AGENTS.md` §0.
- Python 3.14 (uv installs it for you)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker with Docker Compose, for Postgres. On Windows, use Docker Desktop with the WSL2 backend.
- A [Gemini API key](https://aistudio.google.com/apikey) to generate real documentation. Without one you can still run the app with the built-in fake model (see [Configuration](#configuration)).

The repository must live on the Linux filesystem (a path under `/home/`), not on a Windows drive such as `/mnt/c/`.

## Installation

Clone the repository:

```bash
git clone https://github.com/dgeyzel/docs-to-ui.git
cd docs-to-ui
```

Run the install script. It copies `.env.example` to `.env` if you don't have one, installs dependencies with `uv sync`, and installs Plain's pre-commit hook:

```bash
./scripts/install
```

Start Postgres and create the schema:

```bash
docker compose up -d --wait
uv run plain postgres sync
```

Put your Gemini key in `.env`:

```bash
GEMINI_API_KEY=your-gemini-api-key
```

## Configuration

Settings are read from `PLAIN_`-prefixed environment variables. `uv run plain dev` loads them from `.env`. The test suite loads the committed `.env.test` first, then `.env`. `.env` is never committed; `.env.example` lists every variable.

### .env

```bash
PLAIN_DEBUG=true
PLAIN_SECRET_KEY=dev_secret_key
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/docs_to_ui
GEMINI_API_KEY=your-gemini-api-key
```

To try the app without a Gemini key, use the fake model. It answers from a fixture written for the petstore example, so other inputs come out mostly "Not enriched":

```bash
PLAIN_LLM_MODEL=fake
PLAIN_LLM_FAKE_RESPONSES=tests/fixtures/llm/petstore.json
```

### Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | required | Postgres connection. The default matches `docker-compose.yml`. |
| `PLAIN_SECRET_KEY` | required | Plain's secret key. Use any long random string locally. |
| `PLAIN_DEBUG` | `false` | `true` for development: serves assets from source. |
| `GEMINI_API_KEY` | — | Gemini authentication, read by LiteLLM. |
| `PLAIN_LLM_MODEL` | `gemini/gemini-3.8-flash` | LiteLLM model string, or `fake`. |
| `PLAIN_LLM_THINKING_LEVEL` | `medium` | `low`, `medium` or `high`. No sampling parameters are ever sent. |
| `PLAIN_LLM_JUDGE_MODEL` | `gemini/gemini-3.8-flash` | Judge model for evaluations. |
| `PLAIN_LLM_JUDGE_THINKING_LEVEL` | `high` | Thinking level for the judge. |
| `PLAIN_LLM_PROGRAM_VERSION` | `baseline` | Which program artifact to load. |
| `PLAIN_LLM_BATCH_TOKEN_BUDGET` | `60000` | Estimated tokens per LLM batch. |
| `PLAIN_LLM_BATCH_MAX_OPERATIONS` | `25` | Operations per batch. |
| `PLAIN_LLM_MAX_CONCURRENCY` | `4` | Batches sent in parallel. |
| `PLAIN_LLM_FAKE_RESPONSES` | `""` | DummyLM fixture file for `LLM_MODEL=fake`. |
| `PLAIN_GENERATIONS_MAX_INPUT_BYTES` | `5242880` | Largest upload or paste (5 MB). |
| `PLAIN_GENERATIONS_TIMEOUT_S` | `900` | Soft time limit, checked between batches. |
| `PLAIN_SOURCES_ENABLED_ADAPTERS` | `["openapi","python"]` | Enabled language adapters. |
| `PLAIN_SOURCES_ZIP_MAX_UNCOMPRESSED_BYTES` | `52428800` | Total bytes a zip may expand to (50 MB). |
| `PLAIN_SOURCES_ZIP_MAX_FILE_BYTES` | `5242880` | Largest file inside a zip (5 MB). |
| `PLAIN_SOURCES_ZIP_MAX_ENTRIES` | `5000` | Most entries a zip may have. |
| `PLAIN_TELEMETRY_BACKENDS` | `["native"]` | Trace backends: `native`, `langfuse`, both, or `[]`. |
| `PLAIN_TELEMETRY_SERVICE_NAME` | `docs-to-ui` | Service name on traces. |
| `PLAIN_TELEMETRY_NATIVE_MAX_ATTRIBUTE_BYTES` | `262144` | Longer span attributes are truncated. |
| `PLAIN_TRACES_RETENTION_DAYS` | `30` | Native spans older than this are pruned daily. |
| `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PROJECT_ID` | — | Required when `langfuse` is active; missing values stop startup with an error naming them. |

Changing `PLAIN_TELEMETRY_BACKENDS` takes effect when you restart both the web server and the worker.

### The design system

`design/docs-to-ui/` is the OpenDesign package, copied into the repository by hand. Nothing in the app edits it. `app/assets/css/tokens.css` is a generated copy of its `tokens.css`. After the design package changes, validate it and refresh the copy:

```bash
uv run python scripts/sync_design.py
```

The script checks the manifest and all 87 required tokens (light values plus both dark-theme blocks), and rejects `url()` values that point to the network. CI runs it with `--check` and fails if the copy is stale.

### Program artifacts

`artifacts/programs/<program>/<version>.json` holds saved DSPy program state, next to a `.meta.json` recording the dataset hash, scores, model, thinking level, DSPy version and date. The committed `baseline` version is the unoptimized programs. `optimize.py` writes new versions; select one with `PLAIN_LLM_PROGRAM_VERSION`.

## Building the Application

With `PLAIN_DEBUG=true` there is no build step: assets are served straight from `app/assets/`.

The `Dockerfile` has three stages:

| Stage | Contents |
| --- | --- |
| `base` | The app and its runtime dependencies |
| `test` | Dev dependencies and headless Chromium; runs the full suite |
| `prod` | Compiled, fingerprinted assets; runs `plain server` |

```bash
docker build --target prod -t docs-to-ui:prod .
```

Run the production image with its port published on your machine's loopback only, so nothing outside your machine can reach it. Inside the container the server listens on all interfaces, which is the only way Docker can forward to it; this is the one approved exception to the project's `127.0.0.1` rule (`AGENTS.md` §0). Always publish with `127.0.0.1:`, never plain `-p 8000:8000`:

```bash
docker run -d --name docs-to-ui-web -p 127.0.0.1:8000:8000 \
  -e PLAIN_SECRET_KEY=change-me \
  -e PLAIN_HTTPS_REDIRECT_ENABLED=false \
  -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/docs_to_ui \
  -e GEMINI_API_KEY=your-gemini-api-key \
  docs-to-ui:prod
```

The app is then at `http://127.0.0.1:8000`. `host.docker.internal` reaches the Postgres from `docker-compose.yml`; on Linux without Docker Desktop, add `--add-host=host.docker.internal:host-gateway`. `PLAIN_HTTPS_REDIRECT_ENABLED=false` is needed because the local server speaks plain HTTP.

Run the job worker from the same image, with the same environment variables and no published port:

```bash
docker run -d --name docs-to-ui-worker \
  -e PLAIN_SECRET_KEY=change-me \
  -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/docs_to_ui \
  -e GEMINI_API_KEY=your-gemini-api-key \
  docs-to-ui:prod plain jobs worker
```

## Running the Application

### Development server

```bash
uv run plain dev
```

This loads `.env`, runs preflight checks, starts the web server with auto-reload, and starts the background job worker alongside it (configured in `[tool.plain.dev.run]` in `pyproject.toml`). The server prints its address, which is `https://app.localhost:8443` by default. Open it in your browser; on Windows, WSL forwards localhost automatically.

The worker is required: without it, generations stay in "Waiting for a worker…".

### Stopping

Press `Ctrl+C`. Postgres keeps running in Docker; stop it with:

```bash
docker compose down
```

Your data lives in the `postgres-data` Docker volume and survives restarts.

## Usage Guide

### 1. Generate from pasted text

Open the home page, select the **Paste** tab, paste an OpenAPI document or Python code, and click **Generate documentation**. Leave **Language** on **Auto-detect**, or choose one.

### 2. Generate from a file or a zip

Select **Upload file** and choose a `.yaml`, `.yml`, `.json` or `.py` file, or a `.zip` of a project (for example a GitHub "Download ZIP"). A single top-level folder is stripped automatically. For a Python package, tests, virtualenvs, `build/` and `dist/` are skipped. If the zip contains several OpenAPI documents, type the one to use in **Entry file**, for example `api/openapi.yaml`.

### 3. Follow progress

The generation page shows the stage stepper and "Enriched N of M batches". It refreshes itself every two seconds and switches to the finished page when the job is done.

### 4. Read the page

The top card shows the status, model and program version, **Files read (N included, M skipped)** (expand it to see every file and why any were skipped) and the trace summary strip. Below it is the doc page. Use the sidebar to jump to an operation, click a group name to collapse it, and click an operation's header to collapse its card.

### 5. Fix failures

If generation fails, the page shows the error type and, for input errors, the file and line. Fix your input and generate again, or click **Retry** to rerun the same input (useful after a provider error or timeout). **Regenerate** on a finished page reruns it with the current model and program version.

### 6. Give feedback

At the end of every operation card, and at the end of the page, answer **Was this helpful?** with **Yes** or **No**. To add a correction, open **Add a correction**, type it, then click **Yes** or **No**. Your latest answer is shown on the page.

### 7. Export

Click **Export HTML** to download a standalone page you can open from disk, email or host anywhere. Click **Export JSON** to download the page's data.

### 8. Inspect traces

Click **View trace** on a generation, or **Traces** in the header for the list, filterable by generation and status. The waterfall shows every span, colored by type (request, job, stage, LLM, database), with errors labeled. Click a span to see its attributes and events; LLM spans also show the model, the messages and token counts. Spans arrive in batches every few seconds, so reload to see the newest ones.

### 9. Use Langfuse

Set the four `LANGFUSE_*` variables and `PLAIN_TELEMETRY_BACKENDS=["native","langfuse"]` (or just `["langfuse"]`), then restart `plain dev`. Traces appear in your Langfuse project, feedback appears as `user_feedback` scores, and **View trace** links to the first backend with a viewer (native, if active).

### 10. Evaluate and optimize the programs

These commands call the real model and read `GEMINI_API_KEY` from `.env`:

```bash
# Score a program version on the dev set
uv run --env-file .env python -m dspy_pipeline.optimize evaluate --version baseline

# Optimize EnrichOperations on the train set and save a new version
uv run --group optimize --env-file .env python -m dspy_pipeline.optimize optimize --version v1

# Turn 👎 feedback with comments into dataset candidates to review by hand
uv run --env-file .env python -m dspy_pipeline.optimize export-feedback --output candidates.jsonl
```

Each prints a JSON report. To promote a version, commit its files in `artifacts/programs/` and set `PLAIN_LLM_PROGRAM_VERSION`. The same commands run on GitHub from the **evals** workflow (Actions → evals → Run workflow), which needs a `GEMINI_API_KEY` repository secret.

### 11. Switch themes

Click **Toggle theme** in the header. The choice is remembered in your browser. Exported pages follow the reader's system setting.

## Project Structure

```
docs-to-ui/
├── app/
│   ├── settings.py              Installed packages, middleware, job schedule, Langfuse env mapping
│   ├── urls.py                  Root router: assets, generations, traces, home
│   ├── llm/                     Plain-free: importable by the optimization pipeline
│   │   ├── schemas.py           Pydantic contracts: ApiSurface, Operation, DocPage, ...
│   │   ├── signatures.py        DSPy signatures (EnrichOperations, WriteOverview, judge, ...)
│   │   ├── batching.py          Packing operations into batches under a token budget
│   │   ├── generator.py         Concurrent enrichment, retries, partial failure, overview, merge
│   │   ├── merge.py             Dropping IDs the LLM invented
│   │   ├── docpage.py           Pages and overviews without the LLM
│   │   ├── lm.py                Gemini or DummyLM
│   │   └── artifacts.py         Saving and loading versioned programs
│   ├── sources/                 Plain package: turning input into an ApiSurface
│   │   ├── bundle.py            SourceFile, SourceBundle, file manifest
│   │   ├── archive.py           The safe in-memory zip reader
│   │   ├── registry.py          Enabled adapters, detection, per-adapter file selection
│   │   └── adapters/            base.py (protocol), openapi.py, python.py
│   ├── generations/             Plain package: the product loop
│   │   ├── models.py            Generation and Feedback
│   │   ├── pipeline.py          Create, enqueue, claim and run generations
│   │   ├── jobs.py              GenerateDocJob, MirrorFeedbackJob
│   │   ├── forms.py             Source and feedback forms
│   │   ├── presentation.py      View models for pages, status and errors
│   │   ├── markdown.py          Markdown rendering and nh3 sanitizing
│   │   ├── export.py            Self-contained HTML export
│   │   └── views.py, urls.py    Home, detail, status, regenerate, feedback, exports
│   ├── telemetry/               Plain package: the only code that knows trace backends
│   │   ├── config.py            ready(): tracer provider, baggage, backends, DSPy instrumentation
│   │   ├── api.py               What business code uses: trace context, spans, trace_url, feedback
│   │   ├── otlp.py              Langfuse OTLP endpoint and auth
│   │   └── backends/            base.py (protocol), native.py, langfuse.py
│   ├── traces/                  Plain package: native span store and viewer
│   │   ├── models.py            TraceSpan
│   │   ├── exporter.py          PostgresSpanExporter (raw psycopg, never raises)
│   │   ├── queries.py           Trace list and trace spans
│   │   ├── presentation.py      Waterfall, span types, LLM call view
│   │   ├── jobs.py              PruneTracesJob
│   │   └── views.py, urls.py    /traces pages and the span panel
│   ├── templates/
│   │   ├── base.html            App shell
│   │   └── elements/            doc.*, traces.* and app-shell components, one per file
│   └── assets/
│       ├── css/tokens.css       Generated from the design package; never edit by hand
│       ├── css/components.css   Component styles (tokens only)
│       ├── js/docpage.js        Doc-page interactivity, also inlined into exports
│       └── js/app.js            Theme toggle and source form
├── artifacts/programs/          Versioned program artifacts (baseline committed)
├── dspy_pipeline/
│   ├── datasets/{openapi,python}/{train,dev}.jsonl
│   ├── metrics/                 enrich.py (the SPEC §13 metric), extract.py
│   └── optimize.py              optimize | evaluate | export-feedback
├── design/docs-to-ui/           OpenDesign package: manifest, DESIGN.md, tokens, reference mockups
├── scripts/
│   ├── install                  First-time setup
│   └── sync_design.py           Validates the design package and copies its tokens
├── tests/
│   ├── fixtures/                OpenAPI, Python and DummyLM fixtures, adapter contracts
│   ├── unit/                    Mirrors app/, plus dspy_pipeline, scripts and CSS checks
│   ├── integration/             Real Postgres: views, jobs, zips, feedback, traces, telemetry wiring
│   └── e2e/                     Playwright journeys with a real server and worker
├── .github/workflows/           ci.yml (every push), evals.yml (manual)
├── Dockerfile                   base, test and prod stages
├── docker-compose.yml           Postgres for development
├── docker-compose.test.yml      The containerized suite
├── .env.test                    Test settings: fake LLM, no trace export
├── SPEC.md, AGENTS.md           What to build, and how
├── DESIGN_BRIEF.md              Input for OpenDesign
└── UAT_PLAN.md                  User acceptance test plan
```

## How It Works

### Request flow

The form posts to `/generations`. The view stores the raw input bytes on a new `Generation`, records the request's trace context, queues `GenerateDocJob` and redirects to `/generations/<id>`. That page polls `/generations/<id>/status` over HTMX every two seconds. When the job finishes, the status endpoint answers with `HX-Redirect` and the finished page loads; on failure it returns the error with **Retry** and HTTP 286, which stops polling.

### The job

`GenerateDocJob` first claims the generation with a single `pending → running` update, so running it twice never processes anything twice. Then:

1. **Bundle.** The input becomes a `SourceBundle`. A zip is read in memory (see below) and filtered to the chosen adapter's files; the manifest of included and skipped files is saved.
2. **Detect.** Each adapter scores the bundle, and the highest score wins unless you chose a language.
3. **Extract.** The adapter produces an `ApiSurface` with a real parser. No LLM is involved.
4. **Enrich.** Operations are grouped (by tag or path for OpenAPI, by module or class for Python) and packed into batches under the token budget. Up to `LLM_MAX_CONCURRENCY` batches run in parallel, each with one retry on invalid output. If 10% of batches or fewer fail, those operations render from their source descriptions; more than 10% fails the generation with `validation_error`, or `provider_error` when the model provider was at fault.
5. **Overview.** `WriteOverview` writes the overview and sidebar groups. If it fails, a deterministic overview is used.
6. **Merge.** Operation, parameter and group IDs the LLM invented are dropped and recorded as span events, and the `DocPage` is stored.

The soft time limit is checked between batches. A worker that dies mid-job marks the generation `worker_lost`.

### Stable IDs

Every operation and parameter gets an ID derived only from the input: `GET /pets` and `GET /pets#limit` for HTTP, and `acme.Client.get` and `acme.Client.get#timeout` for Python. LLM output is matched back to the source by these IDs.

### OpenAPI handling

Documents are parsed with a safe YAML loader that keeps node positions, so every error and operation has a line number. Internal `$ref`s and relative file refs are followed within the bundle only. Remote refs, absolute paths and refs that climb above the bundle root are rejected, and nothing is ever fetched. Cycles are caught, and walking a document is protected against YAML alias bombs.

### Python handling

The package root is a `src/` layout if present, otherwise the parent of the shallowest folders containing `__init__.py`; folders without one are namespace packages. Public functions, classes and methods are documented with their signatures, annotations, defaults and docstrings. `__all__` is respected, and names starting with `_` are skipped. A name a package re-exports and lists in `__all__` is documented once, under its public path (`acme.Client`), with its source location still at the definition.

### Zip safety

Archives are read with `zipfile` from the stored bytes and never extracted to disk. Bytes are counted while reading rather than trusted from headers, and exceeding the total, per-file or entry limit fails the generation, which stops zip bombs. Absolute paths, `..` segments, drive letters and symlinks reject the archive. Nested archives, binary files, encrypted entries and files that aren't UTF-8 are skipped and listed in the manifest with the reason.

### Tracing

All instrumentation is OpenTelemetry: Plain's request, database and job spans, OpenInference spans for DSPy, and the job's own stage spans. At startup `app.telemetry` attaches to an existing tracer provider or installs one, adds a baggage processor that copies `docs.generation_id` and `docs.program_version` onto every span, and adds one processor per backend. The job starts its root span as a child of the stored request context, so request, job and LLM spans share one trace ID; an integration test enforces this. The native exporter writes batches with its own psycopg connection in one parameterized statement, truncates long attributes and never raises. Only `app/telemetry/` knows which backends exist.

### Untrusted text

Everything taken from the input and everything the LLM writes is treated as untrusted. Plain text is escaped by the templates. Markdown is rendered with raw HTML disabled and then cleaned with nh3: only a small set of tags is allowed, links may only use `http`, `https` or `mailto`, and images are removed so an exported page can never make a network request. Example code is displayed, never run.

### Styles and themes

Component CSS uses only `var(--…)` tokens from `tokens.css`, with no raw colors and no theme-specific rules; a unit test enforces both. Light values live in `:root`. Dark values override the same tokens under `[data-theme="dark"]`, and under `prefers-color-scheme: dark` when no theme is forced.

### The optimization pipeline

`dspy_pipeline/optimize.py` builds examples from the datasets exactly as the app would (the same adapters and batching), runs a program version, and scores each batch with the SPEC §13 metric:

| Component | What it checks | Weight |
| --- | --- | --- |
| Schema validity | Output parses as `BatchEnrichment` | Gate: 0 if invalid |
| Coverage | Share of operations documented | 0.25 |
| Fidelity | No invented operations or parameters | 0.25 |
| Consistency | Doesn't contradict the source (judge) | 0.15 |
| Example validity | JSON and Python parse; curl URLs match a real path | 0.15 |
| Prose quality | Judge rubric, 1–5 | 0.20 |

`optimize` runs DSPy's BootstrapFewShot (or MIPROv2 with `--optimizer miprov2`), scores the result on the dev set and saves a new artifact version with its metadata.

## Code Quality

Auto-fix lint and formatting:

```bash
uv run plain fix
```

Check lint, formatting, types and annotation coverage without changing files:

```bash
uv run plain code check
```

Run Plain's preflight checks:

```bash
uv run plain preflight
```

The design package, the generated `tokens.css`, the Markdown docs and test fixtures are excluded from formatting (see `[tool.plain.code]` in `pyproject.toml` and `.prettierignore`).

## Testing

### Installing test dependencies

The unit and integration tests need only `uv sync` and a running Postgres. The end-to-end tests also need a Playwright browser and its system libraries (this step uses `sudo`):

```bash
uv run playwright install --with-deps chromium
```

### Running tests

Unit and integration tests (the default suite):

```bash
uv run pytest
```

End-to-end tests. Each test starts a real server and job worker against an isolated database and drives headless Chromium:

```bash
uv run pytest -m e2e
```

The full containerized suite, the same checks CI runs, with nothing installed locally except Docker:

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

Tests never call a real LLM (`.env.test` sets `LLM_MODEL=fake` with DummyLM fixtures) and can't reach the internet: `pytest-socket` blocks every connection except localhost.

### Test structure

```
tests/unit/                Adapters (including the contract suite), zip safety, batching, merge,
                           generator, artifacts round-trip, metrics, sanitizer, exporter mapping,
                           trace viewer logic, backend factory, design sync, CSS token rule
tests/integration/         Job states and failures, zips, feedback and mirroring, native export
                           and trace viewer, telemetry wiring (one trace ID), feedback export
tests/e2e/                 Paste, zip upload, progress, failure and retry, trace viewer,
                           example tabs and copy, feedback, exports opened from disk
tests/fixtures/            OpenAPI (single and multi-file), a Python package, DummyLM responses,
                           and each adapter's contract.json
```

## Development Status

All five milestones are implemented and covered by tests. Remaining work, and where the code knowingly differs from `SPEC.md`:

- **First promoted artifact (M4).** Only the unoptimized `baseline` is committed. Producing and promoting `v1` needs a real Gemini run: `optimize --version v1`, then commit the artifact.
- **No `plain.toolbar`.** It depends on `plain-tailwind`, whose build hooks run even when Tailwind isn't used, which breaks `plain assets compile` and conflicts with the decided "no Tailwind" rule (D5).
- **Extra model fields.** `Generation.trace_span_id` (so the job continues the request's trace) and `Generation.input_entry` with `SourceBundle.entry` (the chosen OpenAPI entry file).
- **Whole-page feedback** stores an empty `operation_id` instead of NULL, following Plain's rule against nullable text columns.
- **URLs** follow Plain's default of no trailing slash (`/generations/1`, `/traces/<id>`).
- **Unexpected job errors** are recorded as `validation_error`; the spec's error codes have no separate "internal error".
- **`docker-compose.test.yml`** runs Postgres and one test container; the E2E tests start their own web server and worker instead of separate services.
- **`ApiSurface`** has no description field, so an API's own description text isn't passed to the overview writer.

## Troubleshooting

### `connection refused` or database errors

Postgres isn't running, or `DATABASE_URL` is missing from `.env`. Start it and apply the schema:

```bash
docker compose up -d --wait
uv run plain postgres sync
```

If `docker` isn't found in WSL, turn on WSL integration for your distribution in Docker Desktop's settings.

### A generation stays at "Waiting for a worker…"

No job worker is running. `uv run plain dev` starts one; otherwise run `uv run plain jobs worker` in another terminal.

### Generations fail with "Model provider error"

Check that `GEMINI_API_KEY` is set in `.env` and valid, then click **Retry**. To try the app without a key, use the fake model described in [Configuration](#configuration).

### The app won't start: "The langfuse telemetry backend needs …"

`langfuse` is in `PLAIN_TELEMETRY_BACKENDS` but some `LANGFUSE_*` variables are missing. Set the ones named in the message, or remove `langfuse` from the list.

### A trace page says "Waiting for spans…" or is missing spans

Spans are exported in batches every few seconds, from both the web server and the worker. The page checks again on its own while empty; reload it to see spans that arrived later.

### Can't reach the production container

Check that the container publishes its port with `docker port docs-to-ui-web`; it should show `8000/tcp -> 127.0.0.1:8000`. If the page redirects to `https://`, add `-e PLAIN_HTTPS_REDIRECT_ENABLED=false`. If the container logs show database connection errors, point `DATABASE_URL` at `host.docker.internal` rather than `127.0.0.1`, which inside a container means the container itself.

### Playwright can't start Chromium

Errors such as `Executable doesn't exist at .../ms-playwright/...` or `error while loading shared libraries: libnss3.so` mean the browser or its system libraries are missing:

```bash
uv run playwright install --with-deps chromium
```

### CI fails with "stale: app/assets/css/tokens.css"

The design package changed but the app's copy wasn't refreshed. Run `uv run python scripts/sync_design.py` and commit the result.

### Files show as changed after copying from Windows

Files copied from Windows may have CRLF line endings. `.gitattributes` normalizes them to LF on commit, so `git status` may list them as changed once.

## License

No license has been chosen yet, so all rights are reserved by the author. Add a `LICENSE` file before distributing the project.
