# AGENTS.md

Rules for any coding agent (OpenCode or otherwise) working in this repository.

- **`SPEC.md` defines *what* to build. This file defines *how* to build it.**
- If the two conflict, or the spec is silent on something that matters, **stop and ask**. Do not guess or silently deviate.
- Rules marked **MUST** are hard requirements.
- Everything else is a strong default. If you depart from a default, say why in your summary.

---

## 0. Environment (MUST)

This project runs on **Linux only**. Plain does not support native Windows. The standard setup on this project's Windows machine:

| Where | What runs there |
|---|---|
| **WSL (Ubuntu)** | The repository (`~/code/docs-to-ui`), this agent, `git`, `gh`, `uv`, `plain`, `pytest`, Playwright, `docker compose` |
| **Windows** | The browser (the app is reached at `http://127.0.0.1:<port>` through WSL's localhost forwarding), Docker Desktop (WSL2 backend), and the OpenDesign app with its own Windows OpenCode install. That Windows OpenCode is for design work only and is never pointed at this repository. |

- **Verify the location first.** Before doing anything, confirm that the repository is on the Linux filesystem: its path starts with `/home/`, not `/mnt/c/` or another `/mnt/<drive>/`. If it doesn't, **stop and report**. Don't work around it.
- **Linux commands only.**
  - Never invoke Windows executables (`*.exe`, `powershell`, `cmd`, `wsl.exe`).
  - Never create a Windows virtual environment.
  - Never add `.bat`/`.ps1` scripts, `sys.platform == "win32"` branches, or Windows path handling.
- **Paths.** Files in the repo use POSIX paths relative to the repo root. Never write absolute machine paths (`/home/<user>/…`, `C:\…`, `\\wsl.localhost\…`) into code, config, tests, or docs.
- **Line endings.** LF only. `.gitattributes` enforces `* text=auto eol=lf`. Set executable bits through git: `git update-index --chmod=+x`.
- **Git.** WSL's `git` and `gh` are the only Git tools used on this checkout. Don't suggest Windows Git clients.
- **Network binding.** The app binds to `127.0.0.1`. **Never** change it to `0.0.0.0` to "fix" access from Windows. Report the problem instead.
- **Docker.** Services (Postgres) run through Docker Desktop's WSL integration. If `docker` is not found, report it. Don't try to install Docker inside WSL.
- **Playwright** runs headless in WSL. Install browsers with `uv run playwright install --with-deps chromium`.
- **The design system is an input, not agent work.**
  - `design/docs-to-ui/` (including `reference/`) is produced by the human in the OpenDesign app on Windows and copied into the repo.
  - Never run `od`, install OpenDesign, or edit `design/docs-to-ui/` by hand. The only exception is `scripts/sync_design.py` reading it.
  - If tokens or mockups are missing or inconsistent, report what's needed.

## 1. Commands

All commands below run in the WSL (Ubuntu) shell, from the repository root.

| Task | Command |
|---|---|
| Install dependencies | `uv sync` |
| Add a runtime dependency | `uv add <pkg>` |
| Add a dev-only dependency | `uv add --group dev <pkg>` |
| Run the app (web + worker, loads `.env`) | `uv run plain dev` |
| Auto-fix lint and format | `uv run plain fix` |
| Lint, format, and type check without changing files | `uv run plain code check` |
| Unit + integration tests (the default suite) | `uv run pytest` |
| E2E tests | `uv run pytest -m e2e` |
| Full containerized suite (same as CI) | `docker compose -f docker-compose.test.yml up --abort-on-container-exit` |
| Framework docs for a package | `uv run plain docs <package>` (e.g. `plain docs jobs`) |
| Sync Plain's own agent rules | `uv run plain agent install` (writes to `.claude/rules/` and `.claude/skills/`) |
| Sync design tokens | `uv run python scripts/sync_design.py` |

**Dependency rules**
- Never use `pip`.
- Never edit `uv.lock` by hand.
- Never add a dependency without stating why an existing one won't do.

## 2. Workflow

1. **Read before writing.** Read the `SPEC.md` sections for the milestone you're on. Before touching an area that has a matching file in `.claude/rules/` (for example `plain-jobs.md` before editing `jobs.py`), read that file.
2. **Plain is not Django.** Plain is a Django fork, and its APIs differ. **MUST NOT** write Django imports or idioms from memory. Check `uv run plain docs <package>` first.
3. **Stay in scope.**
   - Implement the current milestone only.
   - Do not refactor unrelated code.
   - Do not add features, settings, or abstractions the spec doesn't call for.
4. **Test first where practical.** For bugs, this is mandatory (§8.6).
5. **Finish every change with the Definition of Done (§10).**
6. **Keep the spec and the code in sync.**
   - If the code needs to differ from `SPEC.md`, stop and propose a spec change.
   - Do not change decisions marked **[Decided]**.
   - When you add a setting, add it to `.env.example` and to the configuration table in `SPEC.md`.

## 3. Architecture Invariants (MUST)

These come from `SPEC.md` and are easy to break by accident.

- **The LLM never produces markup.** LLM outputs are Pydantic models (`app/llm/schemas.py`). Rendering happens only in templates and elements.
- **`app/llm/` never imports `plain`.** It receives configuration as arguments, so `dspy_pipeline/` can use it without booting the app.
- **Schemas and DSPy signatures are defined once, in `app/llm/`.**
  - Do not redefine them elsewhere, including in `dspy_pipeline/`.
  - Use `dspy.Predict` / `dspy.ChainOfThought` with Pydantic-typed fields. **Never** use `TypedPredictor`.
- **No sampling parameters for Gemini.** Do not pass `temperature`, `top_p`, or `top_k`. Use `thinking_level`.
- **Business code never imports a telemetry backend.**
  - Views, jobs, and `app/llm` use OpenTelemetry APIs and `app/telemetry/api.py` only.
  - Only `app/telemetry/` knows about `native` or `langfuse`.
- **Doc pages use no HTMX.** HTMX is for the app shell and trace viewer. `doc.*` elements must work in a static exported file.
- **Styles use tokens only.** CSS uses `var(--…)` semantic tokens only; no raw color literals. `app/assets/css/tokens.css` is generated. Never edit it by hand.
- **Jobs are idempotent.** `GenerateDocJob.run()` must be safe to run twice (spec §9).

## 4. Plain Conventions

- **Package layout.** Code lives in local packages under `app/<package>/`, created with `uv run plain create <name>` and listed in `INSTALLED_PACKAGES`. No generic `core`, `utils`, or `common` packages.
- **Settings.**
  - Settings live in each package's `default_settings.py` and are prefixed with the package name (`GENERATIONS_…`, `SOURCES_…`).
  - Every setting has a type annotation. Required settings have no default.
  - Read settings with `from plain.runtime import settings`, never `os.environ`, except inside `app/settings.py`.
  - Mark sensitive settings with `plain.runtime.Secret[str]` so they are masked in output.
- **Environment variables and `.env`.**
  - Plain reads `PLAIN_`-prefixed environment variables. `plain dev` loads `.env` in development.
  - Docker and CI inject real environment variables.
  - **MUST NOT** call `load_dotenv()` or add `python-dotenv`.
  - Standalone scripts that need env vars run as `uv run --env-file .env python …`.
- **Models** use `plain.postgres`. Change the schema only through its workflow (see `uv run plain docs postgres`).
- **Background work** goes in `jobs.py` as `plain.jobs` `Job` subclasses. Never use threads for request-triggered work.
- **Templates and elements**
  - Elements live in `templates/elements/`, one component per file, following the namespaces in spec §11.2.
  - Keep logic out of templates. Compute values in views or in small helper functions.

## 5. Python Standards

### 5.1 Language and style
- Target the Python version in `pyproject.toml` (`requires-python`). Use modern syntax, and don't write compatibility shims for older versions.
- All code **MUST** pass `uv run plain code check`, which runs ruff (lint and format) and ty (type checking).
  - Don't hand-format. Run `uv run plain fix`.
  - PEP 8 is enforced through ruff; there is nothing extra to do.
- Use absolute imports. No wildcard imports.
- **No side effects at import time.** No network calls, database queries, or file I/O at module level. One-time setup belongs in `PackageConfig.ready()`.
- Prefer small functions that return early.
- Keep pure logic (parsing, batching, merging, ID generation) separate from I/O, so it can be unit-tested without the database or network.
- Comments explain *why*. Code explains *what*.

### 5.2 Typing
- **MUST** annotate every function signature in `app/`, `dspy_pipeline/`, and `scripts/`.
- Use built-in generics and unions: `list[str]`, `dict[str, int]`, `X | None`.
- Use `typing.Protocol` for pluggable interfaces (`LanguageAdapter`, `TraceBackend`).
- Use `enum.StrEnum` for closed sets of values: statuses, error codes, stages.
- `Any` requires a comment explaining why. `# type: ignore` requires the specific error code and a reason.

### 5.3 Data modeling
- Use **Pydantic v2** for anything that crosses a boundary: LLM input and output, stored JSON (`doc_json`, `input_manifest`), and external data.
  - Use `model_validate()` / `model_dump()`.
  - Use `ConfigDict(frozen=True)` for value objects.
- For purely internal structures, use `@dataclass(frozen=True, slots=True)`.
- Never pass raw `dict`s between modules when a model exists.
- No mutable default arguments. Use `None`, or `Field(default_factory=…)` / `field(default_factory=…)`.

### 5.4 Strings, paths, time, resources
- Prefer f-strings, **except in logging calls** (§5.5).
- Use `pathlib.Path` for filesystem paths.
  - Paths *inside a zip bundle* are strings normalized to `/` separators, per spec §8.
  - Never turn a bundle path into a real filesystem path.
- Datetimes are timezone-aware UTC: `datetime.now(UTC)`. Never use naive datetimes.
- Use `with` for files, database connections, HTTP clients, and zip archives.

### 5.5 Logging
- Use `logger = logging.getLogger(__name__)` at module level. **Never** use `print()` in `app/`.
- Use lazy formatting, `logger.info("Generation %s finished", generation_id)`, not f-strings. The message is only built if the log level is enabled, and log aggregation sees stable message templates.
- Use `logger.exception(...)` inside `except` blocks so the traceback is kept.
- Logs are for operators. Record per-generation diagnostic data as span attributes or events instead.

## 6. Error Handling

- Catch **specific** exceptions. **Never** use bare `except:`.
- Each package defines its own exceptions in `exceptions.py`, deriving from one package base class. Examples: `SourcesError` → `InputError(path, line, message)` and `ArchiveLimitError`.
- When translating an exception, use `raise NewError(...) from exc` so the cause is kept.
- Never swallow an exception silently. Every `except` either re-raises, records the failure (a status or error code on the `Generation`, or a span status), or logs it with context.
- Don't use exceptions for expected control flow. Return a value or a result type instead.
- **Broad `except Exception` is allowed only at these boundaries**, and each one must log the error and record it:

  | Boundary | Why it may catch broadly |
  |---|---|
  | `GenerateDocJob.run()` top level | Converts any failure into `status="failed"` with an error code, then re-raises only if the spec requires it |
  | Per-batch LLM calls in the generator | A failed batch must not abort the whole generation (spec §6.1) |
  | `PostgresSpanExporter.export()` | Telemetry must never affect a generation (spec §10.3) |
  | `TraceBackend.record_feedback()` implementations | Same reason |

  Any other broad catch needs explicit approval.

## 7. Security

- **Secrets**
  - Never commit `.env`. `.gitignore` must include `.env`, `.plain/`, and `artifacts/**/*.tmp`.
  - Never log, print, or raise with secrets or credentials in the message.
  - **Never put secrets in span attributes.** Traces store prompts and inputs, and may be sent to Langfuse.
  - Commit `.env.example` with every variable, using placeholder values.
- **User input is untrusted.** This covers uploaded code, zip archives, OpenAPI documents, and LLM output.
  - **MUST NOT** `exec`, `eval`, `compile`, `import`, or `pickle` user-supplied content. Python input is analyzed with `ast.parse` only.
  - YAML: `yaml.safe_load` only.
  - Zip files: follow spec §8 exactly.
    - Read in memory and never extract to disk.
    - Count bytes as they are read.
    - Reject absolute paths, `..`, and symlinks.
    - Enforce every limit through settings.
  - No network access while processing input, including OpenAPI `$ref`s to remote URLs.
  - Sanitize LLM Markdown with `nh3` after rendering it. Never mark LLM output as safe in templates.
- **SQL.** Use parameterized queries only; this matters especially in the raw-`psycopg` span exporter. Never build SQL with f-strings.
- **Subprocesses.** `subprocess` only with argument lists, never `shell=True`.

## 8. Testing

### 8.1 Layout
```
tests/
├── conftest.py
├── fixtures/{openapi,python,zips}/     # input files + DummyLM responses
├── unit/<mirror of app/>               # e.g. tests/unit/sources/adapters/test_python.py
├── integration/                        # real Postgres, DummyLM, jobs, exporter
└── e2e/                                # Playwright; marked @pytest.mark.e2e
```
Unit tests mirror the `app/` structure. Integration and E2E tests are grouped by feature.

### 8.2 Running
- `uv run pytest` runs unit and integration tests. E2E tests are excluded by default and run with `-m e2e`.
- `pyproject.toml` sets `addopts = "-m 'not e2e' --strict-markers"` and registers every marker.
- Use Plain's `plain.pytest` fixtures for the database and settings. Don't create your own database setup.

### 8.3 No real LLMs, no internet
- Tests **MUST** use `LLM_MODEL=fake`, which uses DSPy's `DummyLM` with fixtures from `tests/fixtures/`.
- Tests **MUST NOT** reach the internet. Enforce this with `pytest-socket`, allowing only the database host.
- Real-model evaluation lives in `dspy_pipeline/` and runs only through `evals.yml`.

### 8.4 Style
- Tests are plain `pytest` functions. No `unittest.TestCase`.
- Name tests by behavior: `test_zip_reader_rejects_parent_directory_paths`.
- Use `@pytest.fixture` for setup. Shared fixtures go in the nearest `conftest.py`.
- Use `@pytest.mark.parametrize` for input variations instead of copying tests.
- Use raw `assert`. Use `pytest.raises(ErrorType, match=…)` for exceptions.
- Use `tmp_path` for files, never hard-coded paths.
- Tests must be deterministic.
  - No `time.sleep`. Poll with a timeout, or control time directly.
  - Don't rely on test ordering.
  - Freeze or inject clocks where time matters.
- Test through public interfaces. Don't assert on private attributes.

### 8.5 What to test
- Every new module gets tests in the same change.
- Each spec contract gets a test: every `LanguageAdapter` goes through the adapter contract suite, and every zip limit, every job state transition, and every telemetry backend is covered.
- **MUST NOT** delete, skip, `xfail`, or weaken an existing test to make a change pass. If a test is wrong, say so and explain why.

### 8.6 Bugs
Every bug fix starts with a regression test that fails for the reported reason. Then apply the fix, and confirm the test passes.

### 8.7 No throwaway files
- Never create scratch or verification files (`test.py`, `verify.py`, `scratch.ipynb`).
- Quick read-only exploration in a terminal (`uv run python -c …`) is fine, but anything worth verifying ends up as a real test.
- `scripts/` holds only the scripts the spec names.

## 9. Documentation

- Public modules, classes, and functions in `app/`, `dspy_pipeline/`, and `scripts/` get **Google-style docstrings**.
  - Include `Args:`, `Returns:`, and `Raises:` where applicable.
  - Don't repeat type information already in the annotations.
- Private helpers (`_name`) and tests don't need docstrings. A clear test name is the documentation.
- A docstring describes behavior and constraints, not implementation history.

## 10. Definition of Done

A task is finished only when all of these are true. Report the result of each in your summary.

- [ ] `uv run plain fix` has been run, and `uv run plain code check` passes with no errors.
- [ ] `uv run pytest` passes. Also run `-m e2e` if templates, elements, views, or JS changed. All runs happen in Linux/WSL (§0).
- [ ] New or changed behavior has tests. Bug fixes have a regression test.
- [ ] No architecture invariant (§3) or security rule (§7) is violated.
- [ ] New settings appear in `default_settings.py`, `.env.example`, and the configuration table in `SPEC.md`.
- [ ] No stray files, debug prints, commented-out code, or unrelated changes.
- [ ] The summary lists what changed, what was tested, and any deviation from the spec or from this file.
