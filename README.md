# Docs-to-UI

A single-user, local developer tool that turns an OpenAPI document or a Python codebase into a readable, navigable documentation page. You paste text or upload a file or `.zip`. The Docs app sends the source to an LLM in one direct call (through LiteLLM, so Gemini, Claude and other providers work), gets back the page's content as validated Pydantic types, and renders a styled page you can read in the app or export as a standalone HTML file. Every generation is traced end to end, and a second app, the Tuning app, evaluates and tunes the Docs app.

## About This Project

Docs-to-UI is built from two documents in this repository:

- [`SPEC.md`](SPEC.md) defines what to build: the architecture, contracts, settings and milestones.
- [`AGENTS.md`](AGENTS.md) defines how to build it: the rules every coding agent and contributor follows.

The visual design comes from an [OpenDesign](https://github.com/nexu-io/open-design) design-system package in `design/docs-to-ui/`, produced from [`DESIGN_BRIEF.md`](DESIGN_BRIEF.md). The apps consume only its `tokens.css`.

### Two apps, one database (SPEC v7, in progress)

The project is being reworked into two Plain apps that share one Postgres database and a common library:

| App | Role |
| --- | --- |
| **Docs app** (`docs_app/`) | Generates and shows documentation pages. This is everything described in [Features](#features). |
| **Tuning app** (`tuning_app/`) | Evaluates and tunes the Docs app through a web UI. Today it has model management, gold sets, eval runs with every metric, the Settings page (trace backends and the default judge) and the shared trace viewer; run comparison arrives later in R4 and optimization in R5. |

The shared `d2u` library (`shared/`) holds the contracts, parsers, telemetry, trace store and design system. The apps may later merge into one app with a Tuning section.

| Milestone | Scope | Status |
| --- | --- | --- |
| v6 **M1–M5** | Single-app version: OpenAPI and Python input, DSPy enrichment, jobs, tracing, feedback, optimization pipeline, containers | Done |
| **R1** | Restructure into a uv workspace (`shared`, `docs_app`, `tuning_app`) with no behavior change | Done |
| **R2** | Direct LiteLLM generation in the Docs app, model and prompt registry, 1 MB input cap, DSPy removed from the Docs app | Done |
| **R3** | Trace backend selectable in the UI | Done |
| **R4** | Tuning app: models, gold sets, evals and metrics, run comparison | In progress (R4a models, R4b gold sets, R4c evals: done) |
| **R5** | Tuning app: DSPy optimization and prompt promotion | Planned |
| **R6** | Containers for both apps, CI, docs | Planned |

Models are managed in the Tuning app; prompt versions keep their seeded defaults until R5 (see [Models and prompt versions](#models-and-prompt-versions)). Where the code differs from the spec, see [Development Status](#development-status).

## Features

### Generating documentation

- Paste text, or upload a single file or a `.zip` archive (up to 1 MB)
- **OpenAPI** 3.0 and 3.1, in JSON or YAML, as one file or many files linked by relative `$ref`s
- **Python** source, parsed with `ast` only: user code is never imported or run
- The language is detected automatically, or you can choose it
- For a zip with several OpenAPI entry files, choose one with the **Entry file** field
- Generation runs in a background job with one direct LLM call. The page shows a live stage stepper (Bundle → Generate → Merge) and, for large inputs split into parts, part progress
- Broken input (a YAML syntax error, a Python syntax error, an unsupported OpenAPI version) fails before any model call, with the file and line
- Three strategies: **`llm`** (the default: the model reads the source and writes the whole page), **`hybrid`** (a parser extracts the structure and the model writes the descriptions) and **`parser`** (no model, used as an eval baseline). The Docs app offers `hybrid` only when `PLAIN_GENERATIONS_ENABLE_HYBRID` is on
- Invalid input fails with an error that names the file and line, for example `src/acme/client.py:12`
- **Retry** and **Regenerate** start a fresh generation from the stored input
- A history of recent generations with their status

### The doc page

- An overview and sidebar groups written by the LLM, validated against the extracted operations
- One card per operation: method badge or signature, summary, description, parameter table, code examples, return value and source location (`acme/client.py:42`)
- Operation and parameter IDs are derived in code (`GET /pets`, `acme.Client.get`), never invented by the model, so pages from every strategy line up
- With the `hybrid` strategy, operations whose batch failed still render from the source's own descriptions, marked "Not enriched"
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

- Every request, job stage and LLM call is an OpenTelemetry span. Spans from the request, the job and the LLM calls share one trace ID
- **Native backend:** spans stored in Postgres and shown in the in-app trace viewer (trace list, waterfall timeline, span details and a dedicated LLM call view with messages and token counts)
- **Langfuse backend:** spans sent over OTLP and feedback sent as scores. Both backends can be active at once
- A summary strip on each generation page: LLM calls, total tokens, wall time and a **View trace** link
- Spans older than 30 days are pruned daily

### Models and prompts

- A shared registry of models (any LiteLLM model string, with its call parameters and the name of the environment variable holding its key) and prompt versions (instructions plus few-shot examples)
- The Docs app always uses the active model and the active prompt version for the input's language; both are chosen in the Tuning app, and the generation page records which were used, with tokens and cost
- Seeded defaults: Gemini 3.8 Flash as the generation model, Claude Sonnet 4.5 as the default judge, and a `baseline` prompt for each language and strategy

## Tech Stack

- **Web framework:** [Plain](https://plainframework.com/) (a Django fork) with Jinja2 templates, `plain.elements` components and `plain.htmx`
- **Database and jobs:** Postgres through `plain.postgres`, with `plain.jobs` for background work
- **LLM:** [LiteLLM](https://docs.litellm.ai/) for every call, with Pydantic models as structured-output schemas; [DSPy](https://dspy.ai/) only in the Tuning app
- **Data models:** Pydantic v2 for every structure that crosses a boundary
- **Parsing:** PyYAML (`safe_load` semantics) for OpenAPI, Python's `ast` for Python, `zipfile` in memory for archives
- **Rendering:** markdown-it-py with output sanitized by nh3
- **Styling and scripts:** plain CSS with design-system custom properties (no Tailwind) and vanilla JavaScript
- **Observability:** OpenTelemetry SDK, `openinference-instrumentation-litellm`, a raw-psycopg span exporter, and the Langfuse SDK and OTLP exporter
- **Tooling:** a uv workspace, ruff and ty (through `plain code`), pytest, Playwright, Docker, GitHub Actions

## Requirements

- Linux or WSL (Ubuntu). Native Windows is not supported; see `AGENTS.md` §0.
- Python 3.14 (uv installs it for you)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker with Docker Compose, for Postgres. On Windows, use Docker Desktop with the WSL2 backend.
- A [Gemini API key](https://aistudio.google.com/apikey) for the seeded generation model, and an [Anthropic API key](https://console.anthropic.com/) for the seeded judge once evals arrive. Without keys you can still try the app with the fake model (see [Configuration](#configuration)).

The repository must live on the Linux filesystem (a path under `/home/`), not on a Windows drive such as `/mnt/c/`.

## Installation

Clone the repository:

```bash
git clone https://github.com/dgeyzel/docs-to-ui.git
cd docs-to-ui
```

Run the install script. It copies each app's `.env.example` to `.env` (in `docs_app/` and `tuning_app/`) if you don't have one, and installs every workspace member with `uv sync --all-packages`:

```bash
./scripts/install
```

Start Postgres and create the schema. Both apps share the database; the Tuning app installs every shared package plus its own tables, so syncing from it creates everything:

```bash
docker compose up -d --wait
uv run --directory tuning_app plain postgres sync
```

Put your provider keys in `docs_app/.env` (and in `tuning_app/.env` for evaluations):

```bash
GEMINI_API_KEY=your-gemini-api-key
```

## Configuration

Settings are read from `PLAIN_`-prefixed environment variables. Each app has its own files in its directory: `plain dev` loads that app's `.env`, and its test suite loads the committed `.env.test` first, then `.env`. `.env` files are never committed; each `.env.example` lists every variable that app reads.

### docs_app/.env

```bash
PLAIN_DEBUG=true
PLAIN_SECRET_KEY=dev_secret_key
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/docs_to_ui
GEMINI_API_KEY=your-gemini-api-key
```

To try the app without a provider key, point the fake model at the test fixtures and make it active (see [Models and prompt versions](#models-and-prompt-versions)). It answers from fixtures written for the test inputs, so other inputs fail with a validation error:

```bash
PLAIN_GENERATIONS_FAKE_RESPONSES=tests/fixtures/llm/fake.json
```

### Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | required | Postgres connection. The default matches `docker-compose.yml`. |
| `PLAIN_SECRET_KEY` | required | Plain's secret key. Use any long random string locally. |
| `PLAIN_DEBUG` | `false` | `true` for development: serves assets from source. |
| `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, … | — | Provider keys, read by LiteLLM. Each registered model names the variable holding its key; the seeded models use these two. |
| `PLAIN_GENERATIONS_MAX_INPUT_BYTES` | `1048576` | Largest upload or paste (1 MB). |
| `PLAIN_GENERATIONS_TIMEOUT_S` | `900` | Soft time limit, checked between LLM calls. |
| `PLAIN_GENERATIONS_MAX_CONCURRENCY` | `4` | Parallel calls when an input is split, or for `hybrid` batches. |
| `PLAIN_GENERATIONS_ENABLE_HYBRID` | `false` | Offer the `hybrid` strategy in the Docs app's form. |
| `PLAIN_GENERATIONS_FAKE_RESPONSES` | `""` | Fixture file for the fake model (tests), relative to the repository root. |
| `PLAIN_SOURCES_ENABLED_ADAPTERS` | `["openapi","python"]` | Enabled language adapters. |
| `PLAIN_SOURCES_ZIP_MAX_UNCOMPRESSED_BYTES` | `52428800` | Total bytes a zip may expand to (50 MB). |
| `PLAIN_SOURCES_ZIP_MAX_FILE_BYTES` | `5242880` | Largest file inside a zip (5 MB). |
| `PLAIN_SOURCES_ZIP_MAX_ENTRIES` | `5000` | Most entries a zip may have. |
| `PLAIN_TELEMETRY_SERVICE_NAME` | `docs-to-ui` | Service name on traces. |
| `PLAIN_TELEMETRY_NATIVE_MAX_ATTRIBUTE_BYTES` | `262144` | Longer span attributes are truncated. |
| `PLAIN_TELEMETRY_SETTINGS_TTL_S` | `10` | How long each process caches the trace backends chosen in the Tuning app. |
| `PLAIN_TELEMETRY_EXPORT_ENABLED` | `true` | `false` attaches no trace backend at all, whatever is chosen. The test suites and the image build turn it off. |
| `PLAIN_TRACES_RETENTION_DAYS` | `30` | Native spans older than this are pruned daily. |
| `PLAIN_GOLDSETS_MAX_IMPORT_BYTES` | `10485760` | Largest gold-set JSON file the Tuning app imports (10 MB). |
| `PLAIN_TUNING_MAX_EVAL_CONCURRENCY` | `4` | Most examples an eval run evaluates at once. |
| `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PROJECT_ID` | — | Needed before Langfuse can be chosen. Set them in both apps' `.env` files. |

Which trace backends receive spans (native, Langfuse, both or none) isn't an environment variable: it is chosen on the Tuning app's **Settings** page and applies to both apps within `PLAIN_TELEMETRY_SETTINGS_TTL_S` seconds, with no restart.

### The design system

`design/docs-to-ui/` is the OpenDesign package, copied into the repository by hand. Nothing in the apps edits it. `shared/src/d2u/ui/assets/css/tokens.css` is a generated copy of its `tokens.css`, served to both apps. After the design package changes, validate it and refresh the copy:

```bash
uv run python scripts/sync_design.py
```

The script checks the manifest and all 87 required tokens (light values plus both dark-theme blocks), and rejects `url()` values that point to the network. CI runs it with `--check` and fails if the copy is stale.

### Models and prompt versions

Models, prompt versions and the active choices live in the shared database (the `d2u.registry` package) rather than in settings. Models are managed on the Tuning app's **Models** page; prompt versions get their UI in R5. The seeded defaults:

| Seeded entry | Value |
| --- | --- |
| Active generation model | `Gemini 3.8 Flash` (`gemini/gemini-3.8-flash`, key in `GEMINI_API_KEY`, `reasoning_effort: medium`) |
| Default judge | `Claude Sonnet 4.5` (`anthropic/claude-sonnet-4-5`, key in `ANTHROPIC_API_KEY`) |
| Active prompts | `baseline` for OpenAPI and Python, for both the `llm` and `hybrid` strategies, from `shared/src/d2u/prompts/` |

On the **Models** page (`https://localhost:8444/tuning/models`) you can add and edit models, run **Test connection** (a minimal structured-output call, run by the Tuning app's worker, showing latency or the error) and **Activate for the Docs app**. The form offers only the call parameters LiteLLM reports as supported for the model string. The default judge is chosen on the **Settings** page among models enabled for judging.

A model's parameters are passed to LiteLLM as given, except that Gemini 3 models never receive `temperature`, `top_p` or `top_k`, and keys the client sets itself (such as `api_key`) are refused. API keys are never stored; a model only names the environment variable that holds its key.

## Building the Application

With `PLAIN_DEBUG=true` there is no build step: assets are served straight from `shared/src/d2u/ui/assets/`.

The `Dockerfile` has three stages:

| Stage | Contents |
| --- | --- |
| `base` | The app and its runtime dependencies |
| `test` | Dev dependencies and headless Chromium; runs the full suite |
| `prod` | The Docs app alone, with only its own dependencies (the build fails if DSPy is importable) and compiled assets; runs `plain server` (a Tuning app image arrives in R6) |

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
  docs-to-ui:prod plain jobs worker --queue docs
```

## Running the Application

### Development servers

Run each app in its own terminal:

```bash
uv run --directory docs_app plain dev --hostname localhost --port 8443
uv run --directory tuning_app plain dev --hostname localhost --port 8444
```

Each command loads that app's `.env`, runs preflight checks and starts its web server with auto-reload, plus that app's background job worker (configured in `[tool.plain.dev.run]` in each `pyproject.toml`). The two apps share the job tables, so each worker serves only its own queue: `docs` for the Docs app, `tuning` for the Tuning app. Open the Docs app at `https://localhost:8443` and the Tuning app at `https://localhost:8444/tuning`; on Windows, WSL forwards localhost automatically. `--hostname localhost` avoids `plain dev` editing `/etc/hosts`, which needs `sudo`.

The workers are required: without the Docs app's, generations stay in "Waiting for a worker…"; without the Tuning app's, Test connection never finishes.

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

The generation page shows the stage stepper and, for a large input split into parts, "Generated N of M parts". It refreshes itself every two seconds and switches to the finished page when the job is done.

### 4. Read the page

The top card shows the status, strategy, model, prompt version, tokens and cost, **Files read (N included, M skipped)** (expand it to see every file and why any were skipped) and the trace summary strip. Below it is the doc page. Use the sidebar to jump to an operation, click a group name to collapse it, and click an operation's header to collapse its card.

### 5. Fix failures

If generation fails, the page shows the error type and, for input errors, the file and line. Fix your input and generate again, or click **Retry** to rerun the same input (useful after a provider error or timeout). **Regenerate** on a finished page reruns it with the current active model and prompt version.

### 6. Give feedback

At the end of every operation card, and at the end of the page, answer **Was this helpful?** with **Yes** or **No**. To add a correction, open **Add a correction**, type it, then click **Yes** or **No**. Your latest answer is shown on the page.

### 7. Export

Click **Export HTML** to download a standalone page you can open from disk, email or host anywhere. Click **Export JSON** to download the page's data.

### 8. Inspect traces

Click **View trace** on a generation, or **Traces** in the header for the list, filterable by generation and status. The waterfall shows every span, colored by type (request, job, stage, LLM, database), with errors labeled. Click a span to see its attributes and events; LLM spans also show the model, the messages and token counts. Spans arrive in batches every few seconds, so reload to see the newest ones.

### 9. Choose trace backends and use Langfuse

Open the Tuning app's **Settings** page (`https://localhost:8444/tuning/settings`) and tick **Native**, **Langfuse**, both or neither, then click **Save settings**. Both apps, web servers and workers alike, use the new choice within 10 seconds; nothing needs a restart. The Docs app shows the current choice, read-only, on its generation form and trace list.

Langfuse stays greyed out until its four `LANGFUSE_*` variables are set; the page names the missing ones. Set them in both `docs_app/.env` and `tuning_app/.env` and restart both apps once. With Langfuse chosen, traces appear in your Langfuse project, feedback appears as `user_feedback` scores, and **View trace** links to the first chosen backend with a viewer (native, if chosen). The in-app trace list shows native traces only.

### 10. Curate gold sets

A gold set is a named collection of examples for one language: an input, exactly as the Docs app would read it, and the reference page it should produce. Only approved examples are used by eval runs.

1. Open **Gold sets** in the Tuning app. Create a set, import a gold-set JSON file, or click **Load starter examples** for a draft set per language built from the shipped inputs.
2. In a set, click **Add example**, paste or upload source (a file or a `.zip`, up to 1 MB), and choose how to fill the expected page: start empty, seed from the parser, or seed from a model (the `llm` strategy with the active prompt, run by the Tuning app's worker; the page reloads when it's done).
3. Edit the expected page in the form editor: operations, parameters (name, location, type, required, default, description), summaries, descriptions and code examples. **Add** and **Remove** buttons change rows without saving; **Save expected page** validates everything. Operation and parameter IDs are derived from the method and path, or the qualified name, never typed in.
4. Set the split (train, dev or test) and reviewer notes, then **Approve**. Every change is kept in the example's history. On the set page, select examples and use **Assign split** to move many at once.
5. **Import a Docs app generation** copies a finished generation's input and page as a draft example.

The set page shows a content hash of its approved examples; eval runs record it, so results can be tied to the exact examples they were measured on.

### 11. Run evals

1. Open **Evals** and click **New eval run**. Choose a gold set and split, a strategy (`llm`, `hybrid`, or `parser` as the no-model baseline), the generation model, a prompt version (empty means the active one), the judge and how many examples run at once. The form preselects the Docs app's model and the default judge, and warns when the judge is also the model being evaluated.
2. The Tuning app's worker generates every approved example of the split through the same code as the Docs app, asks the judge to grade each page, and scores it. The run page shows progress, then the summary: the total and every metric with a 95% confidence interval, component accuracy by component, tokens, generation and judge cost, and each example's scores and errors. **Traces** opens the trace list filtered to the run.
3. A failing example scores zero and shows its error; the run carries on. A failing judge call leaves faithfulness's judge half and prose quality at zero.

The **Metrics** page defines each metric and edits the weights; saving creates a new metric version, which new runs record. Run comparison arrives later in R4; DSPy optimization and prompt promotion in R5.

### 12. Switch themes

Click **Toggle theme** in the header. The choice is remembered in your browser. Exported pages follow the reader's system setting.

## Project Structure

```
docs-to-ui/
├── pyproject.toml               uv workspace root: members and shared dev tooling
├── shared/                      The d2u library (workspace member)
│   └── src/d2u/
│       ├── schemas/             Pydantic contracts: ApiSurface, Operation, DocPage, gold inputs, ...
│       ├── generation/          Plain-free: LiteLLM client, prompts, splitting, ID derivation,
│       │                        strategies (llm, hybrid, parser), batching and merging,
│       │                        running a strategy on a bundle (evals, seeding), parameter offers
│       ├── prompts/             Baseline prompt files per language and strategy, overview prompt
│       ├── registry/            Plain package: ModelConfig, PromptVersion, RuntimeSettings, seeds
│       ├── sources/             Bundles, input intake, the safe zip reader, adapters, registry
│       ├── generations/         Plain package: Generation and Feedback, input and fake-model helpers
│       ├── telemetry/           Plain package: tracer provider, backends, routing processor, api,
│       │                        MirrorFeedbackJob
│       ├── traces/              Plain package: TraceSpan, exporter, viewer, PruneTracesJob
│       └── ui/                  Plain package: tokens, component CSS, JS, shared elements
├── docs_app/                    The Docs app (Plain project "docs")
│   ├── pyproject.toml           Dependencies, dev worker, test paths
│   ├── .env.example, .env.test
│   └── app/
│       ├── settings.py, urls.py
│       ├── templates/           App shell and app-specific elements
│       └── generate/            Form, pipeline, GenerateDocJob, views, export, presentation
├── tuning_app/                  The Tuning app (Plain project "tuning")
│   ├── pyproject.toml           Dependencies (DSPy), optional optimize group, test paths
│   ├── .env.example, .env.test
│   ├── app/
│   │   ├── settings.py, urls.py Every route under /tuning/
│   │   ├── templates/           App shell
│   │   ├── dashboard/           Placeholder dashboard (R4 builds the real UI)
│   │   ├── models_ui/           Model registry: list, add, edit, Test connection, activate
│   │   ├── goldsets/            Gold sets: examples, form editor, seeding, imports, starter inputs
│   │   ├── evals/               Eval runs, metrics (Plain-free), metric versions, EvalRunJob
│   │   └── settings_ui/         Settings page: trace backends, default judge
├── design/docs-to-ui/           OpenDesign package: manifest, DESIGN.md, tokens, reference mockups
├── scripts/
│   ├── install                  First-time setup
│   └── sync_design.py           Validates the design package and copies its tokens
├── tests/
│   ├── fixtures/                OpenAPI and Python inputs, fake-model responses, adapter contracts
│   ├── shared/                  Mirrors d2u (run by the Docs app's test suite)
│   ├── docs_app/                Docs app unit and integration tests
│   ├── tuning_app/              Tuning app and pipeline tests
│   └── e2e/                     Playwright journeys: docs/ (Docs app), tuning/ (Tuning app, cross-app)
├── .github/workflows/           ci.yml (every push; evals.yml returns in R5)
├── Dockerfile                   base, test and prod stages
├── docker-compose.yml           Postgres for development
├── docker-compose.test.yml      The containerized suite
├── SPEC.md, AGENTS.md           What to build, and how
├── DESIGN_BRIEF.md              Input for OpenDesign
├── UAT_PLAN.md                  User acceptance test plan
└── LICENSE.md                   BSD 2-Clause License
```

## How It Works

### Request flow

The form posts to `/generations`. The view stores the raw input bytes on a new `Generation`, records the request's trace context, queues `GenerateDocJob` and redirects to `/generations/<id>`. That page polls `/generations/<id>/status` over HTMX every two seconds. When the job finishes, the status endpoint answers with `HX-Redirect` and the finished page loads; on failure it returns the error with **Retry** and HTTP 286, which stops polling.

### The job

`GenerateDocJob` first claims the generation with a single `pending → running` update, so running it twice never processes anything twice. It records the active model at that moment. Then:

1. **Bundle.** The input becomes a `SourceBundle`. A zip is read in memory (see below) and filtered to the chosen language's files; the manifest of included and skipped files is saved.
2. **Detect.** Each adapter scores the bundle, and the highest score wins unless you chose a language.
3. **Check.** For the `llm` strategy, the input is parsed only to check its syntax, so broken input fails with its file and line before any model call.
4. **Generate.** The active prompt version is rendered into messages (instructions, few-shot examples, then the files, naming the OpenAPI entry file) and sent to the active model with `GeneratedPage` as the structured-output schema. An answer that doesn't validate is retried once with the validation error. An input too large for the model is split into parts, keeping directories together; parts run in parallel and one more call writes the overview.
5. **Merge.** IDs are derived in code, source locations that don't exist in the input are dropped, and the `DocPage` is stored with the tokens, cost and latency.

The `hybrid` strategy instead extracts the structure with a parser, sends batches of operations for descriptions (a failed batch shows its operations "Not enriched" unless more than 10% fail), and writes the overview. The `parser` strategy calls no model. The soft time limit is checked between calls. A worker that dies mid-job marks the generation `worker_lost`, and an unexpected error `internal_error`.

### Stable IDs

Every operation and parameter gets an ID derived only from the input: `GET /pets` and `GET /pets#limit` for HTTP, and `acme.Client.get` and `acme.Client.get#timeout` for Python. LLM output is matched back to the source by these IDs.

### OpenAPI handling

Documents are parsed with a safe YAML loader that keeps node positions, so every error and operation has a line number. Internal `$ref`s and relative file refs are followed within the bundle only. Remote refs, absolute paths and refs that climb above the bundle root are rejected, and nothing is ever fetched. Cycles are caught, and walking a document is protected against YAML alias bombs.

### Python handling

The package root is a `src/` layout if present, otherwise the parent of the shallowest folders containing `__init__.py`; folders without one are namespace packages. Public functions, classes and methods are documented with their signatures, annotations, defaults and docstrings. `__all__` is respected, and names starting with `_` are skipped. A name a package re-exports and lists in `__all__` is documented once, under its public path (`acme.Client`), with its source location still at the definition.

### Zip safety

Archives are read with `zipfile` from the stored bytes and never extracted to disk. Bytes are counted while reading rather than trusted from headers, and exceeding the total, per-file or entry limit fails the generation, which stops zip bombs. Absolute paths, `..` segments, drive letters and symlinks reject the archive. Nested archives, binary files, encrypted entries and files that aren't UTF-8 are skipped and listed in the manifest with the reason.

### Tracing

All instrumentation is OpenTelemetry: Plain's request, database and job spans, OpenInference spans for every LiteLLM call, and the job's own stage spans. At startup `d2u.telemetry` attaches to an existing tracer provider or installs one, adds a baggage processor that copies `docs.generation_id`, `docs.model` and `docs.prompt_version` onto every span, and attaches a processor for every backend it could use: native always, Langfuse when its variables are set. A routing processor in front of them forwards each finished span only to the backends chosen on the Tuning app's Settings page. It reads that choice from `RuntimeSettings` with its own short-lived psycopg connection (outside Plain's query instrumentation and any request transaction) and caches it for `PLAIN_TELEMETRY_SETTINGS_TTL_S` seconds; if the database can't be read, it keeps the last choice and tries again after the TTL. The job starts its root span as a child of the stored request context, so request, job and LLM spans share one trace ID; an integration test enforces this. The native exporter writes batches with its own psycopg connection in one parameterized statement, truncates long attributes and never raises. Only `d2u.telemetry` knows which backends exist.

### Untrusted text

Everything taken from the input and everything the LLM writes is treated as untrusted. Plain text is escaped by the templates. Markdown is rendered with raw HTML disabled and then cleaned with nh3: only a small set of tags is allowed, links may only use `http`, `https` or `mailto`, and images are removed so an exported page can never make a network request. Example code is displayed, never run.

### Styles and themes

Component CSS uses only `var(--…)` tokens from `tokens.css`, with no raw colors and no theme-specific rules; a unit test enforces both. Light values live in `:root`. Dark values override the same tokens under `[data-theme="dark"]`, and under `prefers-color-scheme: dark` when no theme is forced.

### Evaluation and tuning (Tuning app)

Evals always run the production code path (`d2u.generation`): each example goes through the same strategy functions as a Docs app generation, including the syntax check and ID derivation, and every score comes from that output (SPEC D13). Judges are ordinary registry models called through the same LiteLLM client, with a Pydantic verdict (per-claim faithfulness and a 1–5 prose rating). The metric code in `tuning_app/app/evals/metrics/` is Plain-free:

- **Faithfulness** = 0.5 × deterministic (share of generated operations, parameters and types found in the gold page or the parser's surface) + 0.5 × judge (share of supported claims).
- **Component accuracy**: operation F1 by derived ID, then parameter names, locations, types, required flags, defaults, returns, signatures and groups of matched operations, as a weighted mean.
- **Coverage**, **example validity** and **prose quality** as in SPEC §9.5. An output that fails or doesn't validate scores 0 on everything.

Examples run in worker threads that do no database work; the job's thread stores each result. Every span of a run carries `docs.eval_run_id`, which the native store indexes and the trace list filters on. DSPy will only search for better prompts (R5), which reach the Docs app as plain prompt versions.

## Code Quality

Both apps' packages are named `app`, so checks run in three parts: the root run covers the shared library, scripts, the shared and E2E tests and all CSS/JS, and each app is checked from its own directory.

Auto-fix lint and formatting:

```bash
uv run plain-code fix
uv run --directory docs_app plain fix --skip-oxc . ../tests/docs_app
uv run --directory tuning_app plain fix --skip-oxc . ../tests/tuning_app
```

Check lint, formatting, types and annotation coverage without changing files: run the same three commands with `check` (`plain-code check`, `plain code check`) in place of `fix`.

Run Plain's preflight checks:

```bash
uv run --directory docs_app plain preflight
uv run --directory tuning_app plain preflight
```

The design package, the generated `tokens.css`, the Markdown docs and test fixtures are excluded from formatting (see `[tool.plain.code]` in each `pyproject.toml` and `.prettierignore`).

## Testing

### Installing test dependencies

The unit and integration tests need only `uv sync --all-packages` and a running Postgres. The end-to-end tests also need a Playwright browser and its system libraries (this step uses `sudo`):

```bash
uv run playwright install --with-deps chromium
```

### Running tests

Unit and integration tests (the default suite). Tests run from an app directory because `plain.pytest` boots that app; the Docs app's suite also runs the shared library's tests:

```bash
uv run --directory docs_app pytest
uv run --directory tuning_app pytest
```

End-to-end tests. Each test starts real servers and job workers against an isolated database and drives headless Chromium. Docs app journeys (`tests/e2e/docs/`) run from the Docs app; Tuning app and cross-app journeys (`tests/e2e/tuning/`) run from the Tuning app, whose test database also has the Tuning-only tables:

```bash
uv run --directory docs_app pytest -m e2e
uv run --directory tuning_app pytest -m e2e
```

The full containerized suite, the same checks CI runs, with nothing installed locally except Docker:

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

Tests never call a real LLM: database tests make a fake model active, which answers through LiteLLM's mock responses from `tests/fixtures/llm/fake.json`, and E2E servers and workers run without any provider keys or Langfuse credentials. Unit and integration tests export no traces (`PLAIN_TELEMETRY_EXPORT_ENABLED=false` in `.env.test`); E2E servers turn tracing on and use the native store in their isolated database. Tests can't reach the internet either: `pytest-socket` blocks every connection except localhost.

### Test structure

```
tests/shared/              The d2u library: adapters (including the contract suite), zip safety,
                           input intake, LiteLLM client, prompts, splitting, ID derivation and its
                           inverse, strategies and the bundle runner, parameter offers, registry,
                           exporter mapping, trace viewer logic, backend availability, routing
                           processor and selection cache, design sync, CSS rule
tests/docs_app/            Docs app: presentation, sanitizer, job states and failures, strategies, zips,
                           the no-DSPy guard,
                           feedback and mirroring, native export and trace viewer, telemetry
                           wiring (one trace ID), runtime backend switching, read-only selection
tests/tuning_app/          Tuning app skeleton, Settings page, model registry and Test connection,
                           job queues, gold sets and the expected-page editor, every metric,
                           summaries, eval runs (states, failures, judge errors, spans), metric versions
tests/e2e/                 Paste, zip upload, progress, failure and retry, trace viewer,
                           example tabs and copy, feedback, exports opened from disk (docs/);
                           switching trace backends, adding and testing a model, curating
                           and seeding gold examples, running an eval (tuning/)
tests/fixtures/            OpenAPI (single and multi-file), a Python package, fake-model responses,
                           and each adapter's contract.json
```

## Development Status

v6 (milestones M1–M5) is complete, and v7 is in progress on the `redesign/v7` branch: R1 (the workspace restructure), R2 (direct LLM generation and the registry) and R3 (trace backends chosen in the UI) are done; R4 is in progress (R4a models, R4b gold sets and R4c eval runs are done; R4d, results and comparison, is next); R5–R6 are planned. See the milestone table in [About This Project](#about-this-project) and `SPEC.md` §18.

Known gaps and deliberate differences from `SPEC.md`:

- **No prompt version UI yet.** Prompt versions keep their seeded baselines until R5; models and the default judge are managed in the Tuning app.
- **`PLAIN_TUNING_MAX_EVAL_CONCURRENCY` keeps its SPEC §16 name**, although it's defined by the `app.evals` package, whose other settings would be prefixed `EVALS_`.
- **The faithfulness formula** (0.5 × deterministic + 0.5 × judge) and the default component weights inside component accuracy were chosen in review; SPEC §9.5 gives neither.
- **Gold examples store the model seed's state.** Seeding from a model runs as `SeedGoldExampleJob` (added to `SPEC.md` §14), and the example records whether it is pending, running or failed.
- **Connection test results are stored** in a Tuning-only `ModelTest` table (added to `SPEC.md` §13), so the model page can show the latest result after its job finishes.
- **An extra telemetry setting.** `PLAIN_TELEMETRY_EXPORT_ENABLED` (not in v7's first draft) lets the test suites and the image build turn tracing off now that `PLAIN_TELEMETRY_BACKENDS` is gone; `SPEC.md` §16 lists it.
- **Langfuse credentials are per process.** Each app reads the `LANGFUSE_*` variables from its own environment, so the Settings page can only check the Tuning app's. An app without them skips Langfuse even when it's chosen, and says so on its pages.
- **One shared development environment.** The uv workspace installs every member's dependencies into one `.venv`, so DSPy is installed there for the Tuning app. The Docs app never imports it (a test checks), and its production image contains only its own dependencies.
- **`optuna` is opt-in.** It's in the Tuning app's `optimize` group: optuna brings numpy into the shared environment, and a half-imported numpy races with psycopg's numpy adapters when the Docs app's worker starts. Install it with `uv sync --all-packages --group optimize`.
- **No pre-commit hook.** Plain's hook runs `plain` from the repository root, where there is no app. Run the checks in [Code Quality](#code-quality) instead.
- **No `plain.toolbar`.** It depends on `plain-tailwind`, whose build hooks break `plain assets compile` and conflict with the decided "no Tailwind" rule.
- **Whole-page feedback** stores an empty `operation_id` instead of NULL, following Plain's rule against nullable text columns.
- **URLs** follow Plain's default of no trailing slash (`/generations/1`, `/traces/<id>`).

## Troubleshooting

### `connection refused` or database errors

Postgres isn't running, or `DATABASE_URL` is missing from the app's `.env`. Start it and apply the schema:

```bash
docker compose up -d --wait
uv run --directory tuning_app plain postgres sync
```

If `docker` isn't found in WSL, turn on WSL integration for your distribution in Docker Desktop's settings.

### A generation stays at "Waiting for a worker…"

No job worker is running. The Docs app's `plain dev` starts one; otherwise run `uv run --directory docs_app plain jobs worker --queue docs` in another terminal.

### Generations fail with "Model provider error"

Check that the active model's key (for the seeded model, `GEMINI_API_KEY`) is set in `docs_app/.env` and valid, then click **Retry**. To try the app without a key, use the fake model described in [Configuration](#configuration).

### Langfuse is greyed out on the Settings page

Some `LANGFUSE_*` variables are missing from the Tuning app's environment; the page names them. Set them in both apps' `.env` files and restart both apps. If the Docs app's form says "Langfuse (not configured in this app)", the Docs app's `.env` is the one missing them.

### No new traces appear

Check the Tuning app's **Settings** page: if **Native** isn't ticked, nothing is written to the in-app trace store. A change takes up to 10 seconds to reach every process. `PLAIN_TELEMETRY_EXPORT_ENABLED=false` turns tracing off entirely. An old `PLAIN_TELEMETRY_BACKENDS` line in a `.env` file no longer does anything (preflight reports it as unused); delete it.

### A trace page says "Waiting for spans…" or is missing spans

Spans are exported in batches every few seconds, from both the web server and the worker. The page checks again on its own while empty; reload it to see spans that arrived later.

### Can't reach the production container

Check that the container publishes its port with `docker port docs-to-ui-web`; it should show `8000/tcp -> 127.0.0.1:8000`. If the page redirects to `https://`, add `-e PLAIN_HTTPS_REDIRECT_ENABLED=false`. If the container logs show database connection errors, point `DATABASE_URL` at `host.docker.internal` rather than `127.0.0.1`, which inside a container means the container itself.

### Playwright can't start Chromium

Errors such as `Executable doesn't exist at .../ms-playwright/...` or `error while loading shared libraries: libnss3.so` mean the browser or its system libraries are missing:

```bash
uv run playwright install --with-deps chromium
```

### `plain` says "No such command" or can't find the app

Plain looks for `./app`, so app commands must run inside an app directory: use `uv run --directory docs_app …` or `uv run --directory tuning_app …`. Only `plain-code`, `plain docs` and `plain agent install` work from the repository root.

### CI fails with "stale: shared/src/d2u/ui/assets/css/tokens.css"

The design package changed but the app's copy wasn't refreshed. Run `uv run python scripts/sync_design.py` and commit the result.

### Files show as changed after copying from Windows

Files copied from Windows may have CRLF line endings. `.gitattributes` normalizes them to LF on commit, so `git status` may list them as changed once.

## License

Docs-to-UI is licensed under the BSD 2-Clause License. See [LICENSE.md](LICENSE.md).
