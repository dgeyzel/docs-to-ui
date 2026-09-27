# Docs-to-UI: User Acceptance Test Plan

**Based on:** `SPEC.md` v6.1
**Execution:** Manual
**Tester:** ______________
**Build / commit:** ______________
**Dates:** ______________

---

## 1. Purpose and Scope

This plan confirms that Docs-to-UI does what `SPEC.md` promises, from the point of view of the person using it. It covers:

- input handling
- generation
- the doc page
- export
- feedback
- tracing (native and Langfuse)
- configuration
- design tokens
- the optimization pipeline

It does not repeat the automated test suite. Where a behavior is hard to trigger by hand, the case says how to force it through configuration.

**Out of scope:** multi-user access, authentication, hosting, and mixed-language zips (spec §2 non-goals).

## 2. Entry and Exit Criteria

**Entry**
- [ ] The automated suite passes: `uv run pytest` and `uv run pytest -m e2e`.
- [ ] `uv run plain code check` passes.
- [ ] The test-data kit (§4) has been prepared.
- [ ] A Gemini API key with enough quota is available.
- [ ] For section K only: a Langfuse project, with its public key, secret key, base URL, and project ID.

**Exit**
- Every **Critical** and **High** case passes.
- Any **Medium** or **Low** failure is either fixed or logged with an agreed decision.
- The results summary (§7) is complete and signed off.

## 3. Severity and Result Codes

| Severity | Meaning |
|---|---|
| **Critical** | Core loop broken, data or security exposure, or the app won't start |
| **High** | A spec'd feature doesn't work, or gives wrong output |
| **Medium** | The feature works, but with a notable defect or poor feedback to the user |
| **Low** | Cosmetic issue or minor inconvenience |

**Results:** **P** = Pass, **F** = Fail, **B** = Blocked (couldn't run), **N/A** = not applicable.

For every **F**, record: the steps to reproduce, expected vs. actual behavior, the generation ID and trace ID if any, and a screenshot.

## 4. Test-Data Kit

Prepare these files in a `uat-data/` folder outside the repository before starting. Appendix A has one-line commands for the files that are hard to make by hand.

| ID | File | Contents |
|---|---|---|
| D01 | `petstore-3.0.json` | Small OpenAPI 3.0 JSON spec: about 5 operations, 2 tags, some operations with descriptions and some without |
| D02 | `service-3.1.yaml` | OpenAPI 3.1 YAML spec: about 10 operations |
| D03 | `openapi-multifile.zip` | Root `openapi.yaml` with relative `$ref`s to `schemas/*.yaml` and `paths/*.yaml` |
| D04 | `remote-ref.yaml` | OpenAPI spec with a `$ref: "https://example.com/schema.yaml"` |
| D05 | `broken.yaml` | Invalid OpenAPI (for example, a missing `paths` key, or broken YAML indentation) |
| D06 | `single_module.py` | One Python module with 3 public functions (with docstrings and type hints), 1 public class with 2 methods, and 1 `_private` function |
| D07 | `pkg-src-layout.zip` | A `src/acme/` package: `__init__.py` re-exports `Client` from `client.py` and lists it in `__all__`, plus `utils.py`, a `tests/` folder, a `.venv/` folder, and a `__pycache__/` folder |
| D08 | `github-style.zip` | Any Python package zipped inside a single top-level folder `acme-main/` |
| D09 | `syntax_error.py` | Python file with a syntax error on a known line (for example, line 12) |
| D10 | `xss_docstring.py` | Python function whose docstring contains `<script>alert('x')</script>` and `<img src=x onerror=alert(1)>` |
| D11 | `large-openapi.json` | OpenAPI spec of about **4.5 MB** with several hundred operations, enough to need many batches |
| D12 | `too-large.json` | Any valid file of about **5.2 MB** |
| D13 | `zip-slip.zip` | An entry whose path is `../../evil.py` |
| D14 | `zip-symlink.zip` | An entry that is a symlink |
| D15 | `zip-bomb.zip` | Compresses to under 5 MB but expands to more than 50 MB |
| D16 | `zip-many.zip` | More than 5,000 tiny entries |
| D17 | `zip-mixed-junk.zip` | Valid Python package plus a non-UTF-8 `.py` file, a nested `inner.zip`, and a `.png` |
| D18 | `mixed-lang.zip` | Python package plus an `openapi.yaml` |

---

## 5. Test Cases

Each case lists its spec reference, severity, steps, and expected result, followed by a line for the result and notes. **Default settings** means `TELEMETRY_BACKENDS=["native"]` and all other settings at their spec defaults.

### A. Setup and Configuration

**UAT-A01: App and worker start** (§9, §14) · Critical
1. Copy `.env.example` to `.env`. Fill in `DATABASE_URL` and `GEMINI_API_KEY`.
2. Run `uv run plain dev`.

**Expected:** The web server and job worker both start with no errors. The home page loads at `http://127.0.0.1:<port>`.

Result: ___ Notes: ______________________

**UAT-A02: `.env.example` is complete** (§15) · Medium
1. Compare `.env.example` with the configuration table in spec §15.

**Expected:** Every variable in the table appears, with a placeholder value. No real secrets are present.

Result: ___ Notes: ______________________

**UAT-A03: Local-only binding** (§2) · High
1. With the app running, try to open it from another device on the same network, using the machine's LAN IP.

**Expected:** The connection is refused. The app is reachable only through `127.0.0.1`.

Result: ___ Notes: ______________________

**UAT-A04: Missing Langfuse credentials are caught at startup** (§10.3, §15) · Medium
1. Set `PLAIN_TELEMETRY_BACKENDS='["langfuse"]'` and leave the `LANGFUSE_*` variables empty.
2. Restart.

**Expected:** Startup fails with a clear message naming the missing variables. It does not start silently without tracing.

Result: ___ Notes: ______________________

**UAT-A05: `.env` is ignored by git** (AGENTS §7) · High
1. Run `git status` and `git check-ignore .env`.

**Expected:** `.env` is ignored and never shows up as a change.

Result: ___ Notes: ______________________

### B. Input Handling

**UAT-B01: Paste OpenAPI JSON** (§4, §8) · Critical
1. Paste the contents of D01 into the paste box.
2. Set the language to OpenAPI and submit.

**Expected:** A status fragment appears straight away and begins polling. The generation succeeds.

Result: ___ Notes: ______________________

**UAT-B02: Upload an OpenAPI YAML file** (§7) · Critical
1. Upload D02 without setting a language.

**Expected:** The language is detected as OpenAPI automatically, and the generation succeeds.

Result: ___ Notes: ______________________

**UAT-B03: Upload a single Python module** (§7) · Critical
1. Upload D06 without setting a language.

**Expected:** The language is detected as Python, and the generation succeeds.

Result: ___ Notes: ______________________

**UAT-B04: Multi-file OpenAPI zip** (§7) · High
1. Upload D03.

**Expected:** The relative `$ref`s resolve. Operations and schemas from the referenced files appear on the doc page.

Result: ___ Notes: ______________________

**UAT-B05: Remote `$ref` is rejected** (§7, AGENTS §7) · High
1. Upload D04.

**Expected:** The generation fails with an input error that names the remote reference. No network request is made to `example.com`.

Result: ___ Notes: ______________________

**UAT-B06: Invalid OpenAPI** (§4 stage 4) · High
1. Upload D05.

**Expected:** The generation fails with `input_error`. The message includes the file and, where possible, the line.

Result: ___ Notes: ______________________

**UAT-B07: Python syntax error** (§4, §7) · High
1. Upload D09.

**Expected:** The generation fails with `input_error`, showing the file path and the correct line number (for example, 12).

Result: ___ Notes: ______________________

**UAT-B08: Python package zip in src layout** (§7, §8) · Critical
1. Upload D07.

**Expected:**
- Module paths start at `acme` (not `src.acme`).
- The generation succeeds.

Result: ___ Notes: ______________________

**UAT-B09: Default excludes** (§7) · High
1. On the D07 generation page, open the file manifest.

**Expected:** Files under `tests/`, `.venv/`, and `__pycache__/` are listed as **skipped**, each with a reason. No operations from them appear on the doc page.

Result: ___ Notes: ______________________

**UAT-B10: GitHub-style root folder is stripped** (§8) · Medium
1. Upload D08.

**Expected:** Module paths do not include `acme-main`.

Result: ___ Notes: ______________________

**UAT-B11: Manifest counts** (§8) · Medium
1. On any zip generation, compare the "Files read (N included, M skipped)" line with the archive's actual contents.

**Expected:** The counts match. Every skipped file shows a reason.

Result: ___ Notes: ______________________

**UAT-B12: Language override** (§4 stage 3) · Medium
1. Upload D18 with no override. Note which adapter is chosen.
2. Upload D18 again, this time choosing the other language explicitly.

**Expected:**
- In both runs, one adapter is used, and the other language's files are listed as skipped (a non-goal in §2).
- The override is respected.

Result: ___ Notes: ______________________

**UAT-B13: Size cap, just under** (§3 D8) · High
1. Upload D11 (about 4.5 MB).

**Expected:** The upload is accepted and a generation is created.

Result: ___ Notes: ______________________

**UAT-B14: Size cap, over** (§3 D8, §12) · High
1. Upload D12 (about 5.2 MB).
2. Paste more than 5 MB of text.

**Expected:** Both are rejected at the form with a clear size message. No `Generation` is created; confirm that the history list is unchanged.

Result: ___ Notes: ______________________

### C. Zip Safety

For each case below, confirm afterwards that **no files were written anywhere on disk** outside the app's normal temp paths. Checking the repo folder and the app's working directory for new files is enough.

**UAT-C01: Zip-slip path** (§8) · Critical
1. Upload D13.

**Expected:** `input_error` naming the unsafe path. No file is created outside the bundle.

Result: ___ Notes: ______________________

**UAT-C02: Symlink entry** (§8) · Critical
1. Upload D14.

**Expected:** The upload is rejected, with a message about the symlink.

Result: ___ Notes: ______________________

**UAT-C03: Zip bomb** (§8) · Critical
1. Upload D15.

**Expected:**
- It fails quickly with a limit error.
- The app stays responsive, and memory doesn't spike to the full expanded size.

Result: ___ Notes: ______________________

**UAT-C04: Too many entries** (§8) · High
1. Upload D16.

**Expected:** It fails with an entry-limit error.

Result: ___ Notes: ______________________

**UAT-C05: Junk entries are skipped, not fatal** (§8) · High
1. Upload D17.

**Expected:**
- The generation succeeds.
- The non-UTF-8 file, the nested zip, and the image appear as skipped in the manifest, each with a reason.

Result: ___ Notes: ______________________

### D. Generation Job and Status UI

**UAT-D01: Status progression** (§9) · High
1. Submit D02 and watch the status fragment.

**Expected:** The stage updates about every 2 seconds, through bundle, extract, enrich, overview, and merge. On success, the browser moves to the doc page by itself.

Result: ___ Notes: ______________________

**UAT-D02: Batch progress on a large input** (§6.4) · High
1. Submit D11.

**Expected:**
- The status shows "batches done / total", and the count rises.
- The generation succeeds within the 15-minute timeout. Record the duration.

Result: ___ Notes: ______________________ Duration: ______

**UAT-D03: Polling stops on failure** (§9) · Medium
1. Submit D05.
2. Open the browser's network tab.

**Expected:** An error fragment with a **Retry** button appears. The status requests stop after the failure response.

Result: ___ Notes: ______________________

**UAT-D04: Retry and regenerate** (§9) · High
1. On a succeeded generation, click **Regenerate**.
2. On a failed generation, click **Retry**.

**Expected:** Each creates a **new** generation from the stored input. The original generations remain in the history list, unchanged.

Result: ___ Notes: ______________________

**UAT-D05: Soft timeout** (§9) · Medium · *Needs a configuration change*
1. Set `PLAIN_GENERATIONS_TIMEOUT_S=10` and restart.
2. Submit D11.

**Expected:** The generation fails with `timeout`, and the UI says so clearly.
Reset the setting afterwards.

Result: ___ Notes: ______________________

**UAT-D06: Worker killed mid-run** (§9) · High · *Needs process control*
1. Submit D11.
2. While it is enriching, kill the worker process (for example, stop `plain dev` or kill the worker PID).
3. Restart it and wait at least 5 minutes, which is the heartbeat timeout.

**Expected:** The generation ends as `failed` with `worker_lost`. It does not stay "running" forever.

Result: ___ Notes: ______________________

**UAT-D07: Generation history** (§12) · Medium
1. Open the generations list.

**Expected:** Every generation from this session appears, with status, language, input name, date, program version, and model.

Result: ___ Notes: ______________________

### E. Doc Page Content

Use the D01 and D07 generations unless the case says otherwise.

**UAT-E01: Complete coverage** (§10 metric: coverage) · Critical
1. Count the operations in D01.
2. Count the operation cards on the page.

**Expected:** Every operation appears exactly once.

Result: ___ Notes: ______________________

**UAT-E02: No invented content** (§4 stage 7) · Critical
1. Compare the operations and parameters on the page against the source.

**Expected:** No operation or parameter appears that doesn't exist in the input.

Result: ___ Notes: ______________________

**UAT-E03: Existing descriptions respected** (§5 rules) · High
1. For operations in D01 that already have descriptions, compare the page text with the source.

**Expected:** The page expands on the source description without contradicting it.

Result: ___ Notes: ______________________

**UAT-E04: Parameter tables** (§11.2) · High
1. Open 3 operations and check each parameter table.

**Expected:** Each parameter shows its name, location, type, required flag, default (if any), and a description.

Result: ___ Notes: ______________________

**UAT-E05: Examples are sensible** (§10 metric: example validity) · High
1. Check the examples on 3 operations.

**Expected:**
- The JSON parses.
- The curl paths match real endpoints.
- The Python examples are syntactically valid and use real names.

Result: ___ Notes: ______________________

**UAT-E06: Python public API rules** (§7) · High
1. On the D07 page, look for the `_private` function and for `Client`.

**Expected:**
- The `_private` function is absent.
- `Client` appears **once**, under `acme.Client` (its public path), not also under `acme.client.Client`.
- Its source location points to `acme/client.py`.

Result: ___ Notes: ______________________

**UAT-E07: Source locations** (§5) · Medium
1. On the D06 page, check each operation's file and line against the source.

**Expected:** Every file path and line number is correct.

Result: ___ Notes: ______________________

**UAT-E08: Overview and navigation groups** (§6.1) · High
1. Read the overview.
2. Check the sidebar groups.

**Expected:**
- The overview accurately summarizes the API.
- The groups follow the OpenAPI tags, or the Python modules and classes.
- Every operation appears in the navigation.

Result: ___ Notes: ______________________

**UAT-E09: Script injection is neutralized** (§5 rules, AGENTS §7) · Critical
1. Generate docs from D10.
2. View the page. Then view the HTML export.

**Expected:**
- No alert box appears in either.
- The `<script>` and `onerror` content is shown as text or removed, never executed.
- The dev tools console shows no errors caused by it.

Result: ___ Notes: ______________________

**UAT-E10: Partial enrichment marker** (§6.1) · Medium · *Developer-assisted*
1. Ask a developer to force one batch to fail, for example with a `DummyLM` fixture that returns invalid output for one batch.
2. Run a multi-batch generation.

**Expected:**
- The page still renders.
- The affected operations show their source descriptions with a visible "not enriched" marker.

Result: ___ Notes: ______________________

### F. Doc Page Interactivity and Styling

**UAT-F01: Sidebar navigation** (§11.3) · High
1. Click several sidebar entries.

**Expected:** The page scrolls to the right operation. The active group is shown as selected.

Result: ___ Notes: ______________________

**UAT-F02: Collapsible sections** (§11.3) · Medium
1. Collapse and expand several operation cards and groups.

**Expected:** Each works smoothly, with no page reload.

Result: ___ Notes: ______________________

**UAT-F03: Example language tabs** (§11.2) · Medium
1. Switch between curl, Python, and JSON tabs on an operation.

**Expected:** The content switches correctly, with no reload.

Result: ___ Notes: ______________________

**UAT-F04: Copy button** (§11.2) · Medium
1. Copy an example.
2. Paste it into an editor.

**Expected:** The exact example text is pasted, with no extra markup.

Result: ___ Notes: ______________________

**UAT-F05: No server calls from the doc page** (§11.3) · High
1. Open the network tab.
2. Use navigation, collapsing, tabs, and copy on the doc page.

**Expected:** No network requests are triggered by these interactions.

Result: ___ Notes: ______________________

**UAT-F06: Design tokens applied** (§11.1) · Medium
1. Change one color token in `design/docs-to-ui/tokens.css`, for example the primary accent.
2. Run `uv run python scripts/sync_design.py` and reload the page.

**Expected:** The change appears everywhere that token is used. Revert the change afterwards.

Result: ___ Notes: ______________________

### G. Export

**UAT-G01: HTML export downloads** (§11.4) · Critical
1. On a succeeded generation, click **Export HTML**.

**Expected:** A single `.html` file downloads.

Result: ___ Notes: ______________________

**UAT-G02: Export works fully offline** (§11.4) · Critical
1. Disconnect from the network, or stop the app.
2. Open the exported file directly from disk.

**Expected:**
- The page renders with full styling.
- Navigation, collapsing, tabs, and copy all work.

Result: ___ Notes: ______________________

**UAT-G03: Export is self-contained** (§11.4) · High
1. Open the export with dev tools' network tab open.

**Expected:**
- There are no requests to external hosts or to the app.
- There are no feedback buttons, app links, or HTMX attributes. To check, search the file for `hx-`.

Result: ___ Notes: ______________________

**UAT-G04: JSON export** (§11.4) · Medium
1. Click **Export JSON**.

**Expected:** The file is valid JSON with `schema_version`, `surface`, `overview`, and `operations`, and its contents match the page.

Result: ___ Notes: ______________________

**UAT-G05: Export of a large generation** (§11.4) · Medium
1. Export the D11 generation and open it.

**Expected:** It opens and stays usable (scrolling and navigation work) in a normal browser.

Result: ___ Notes: ______________________

### H. Feedback

**UAT-H01: Page-level feedback** (§10.5) · High
1. Click 👍 on the whole page.
2. Then click 👎 with a comment.

**Expected:** The feedback is saved and acknowledged in the UI. It is still there after a page reload.

Result: ___ Notes: ______________________

**UAT-H02: Operation-level feedback** (§10.5) · High
1. Click 👎 on one operation card and add a correction comment.

**Expected:** The feedback is saved against that specific operation.

Result: ___ Notes: ______________________

**UAT-H03: Feedback export for the pipeline** (§10.5, §13) · Medium
1. Run `uv run python dspy_pipeline/optimize.py export-feedback`, or the documented equivalent.

**Expected:** Each 👎 with a comment from H01 and H02 appears as a candidate entry, including the input reference, the operation, and the comment.

Result: ___ Notes: ______________________

### J. Native Tracing (default backend)

**UAT-J01: Trace link from a generation** (§10.2, §10.4) · High
1. On a succeeded generation, click **View trace**.

**Expected:** The native trace page for that generation opens.

Result: ___ Notes: ______________________

**UAT-J02: One connected trace** (§10.1, §10.2) · Critical
1. In that trace, inspect the waterfall.

**Expected:** The request, the job, each stage span, and each LLM call all appear in **one** trace, as a correct parent/child tree.

Result: ___ Notes: ______________________

**UAT-J03: LLM call detail** (§10.4) · High
1. Open an LLM span.

**Expected:** It shows the model (`gemini-3.8-flash` by default), the input and output messages, and prompt, completion, and total token counts.

Result: ___ Notes: ______________________

**UAT-J04: Generation summary strip** (§10.4) · Medium
1. Compare the generation page's summary (LLM calls, tokens, wall time) with the trace.

**Expected:** The numbers match.

Result: ___ Notes: ______________________

**UAT-J05: Trace list and filters** (§10.4) · Medium
1. Open `/traces/`.
2. Filter by a generation, then by error status.

**Expected:** The filters work correctly. Failed generations (for example, D05) show as errors.

Result: ___ Notes: ______________________

**UAT-J06: Large prompts truncated safely** (§10.3) · Low
1. Open an LLM span from the D11 generation.

**Expected:** Very large attributes end with a `…[truncated]` marker. The page loads quickly.

Result: ___ Notes: ______________________

**UAT-J07: No secrets in traces** (AGENTS §7) · Critical
1. Search several traces' attributes, and the database table (`SELECT … WHERE attributes::text LIKE '%<first 8 chars of your key>%'`), for your Gemini API key.

**Expected:** No matches.

Result: ___ Notes: ______________________

**UAT-J08: Telemetry failure doesn't break generation** (§10.3) · High · *Developer-assisted*
1. Ask a developer to make the native exporter fail. For example, revoke its database insert permission on the spans table, or point its connection at a wrong port.
2. Run a generation.

**Expected:**
- The generation still succeeds.
- A throttled warning appears in the logs.
- The UI shows no error.

Result: ___ Notes: ______________________

**UAT-J09: Retention pruning** (§10.4) · Low · *Needs a configuration change*
1. Set `PLAIN_TRACES_RETENTION_DAYS=0`.
2. Trigger the prune job, either manually or by waiting for its schedule.

**Expected:** Old spans are removed and generations are unaffected. Reset the setting afterwards.

Result: ___ Notes: ______________________

### K. Langfuse Tracing

Precondition: fill in the `LANGFUSE_*` variables.

**UAT-K01: Langfuse-only backend** (§10.3) · High
1. Set `PLAIN_TELEMETRY_BACKENDS='["langfuse"]'` and restart.
2. Run a D01 generation.

**Expected:**
- The trace appears in Langfuse with the same structure as in J02.
- **View trace** opens the Langfuse trace page.
- No new rows appear in the native trace list.

Result: ___ Notes: ______________________

**UAT-K02: Filterable attributes** (§10.1) · Medium
1. In Langfuse, filter observations by `generation_id` and `program_version`.

**Expected:** The LLM spans (not only the root span) carry these attributes and can be filtered by them.

Result: ___ Notes: ______________________

**UAT-K03: Feedback mirrored as a score** (§10.5) · High
1. Give 👎 with a comment on the K01 generation.

**Expected:**
- A `user_feedback` score with the comment appears on the Langfuse trace.
- The feedback is also saved locally, which is checked in H03.

Result: ___ Notes: ______________________

**UAT-K04: Both backends at once** (§10.3) · Medium
1. Set `PLAIN_TELEMETRY_BACKENDS='["native","langfuse"]'`.
2. Run a generation.

**Expected:** The trace appears in both places. **View trace** links to the first backend listed.

Result: ___ Notes: ______________________

**UAT-K05: Langfuse unreachable** (§10.3) · High
1. Set `LANGFUSE_BASE_URL` to an unreachable host and restart.
2. Run a generation.

**Expected:** The generation succeeds normally, with no errors or slowdown visible to the user. Restore the setting afterwards.

Result: ___ Notes: ______________________

**UAT-K06: No backends** (§10.3) · Low
1. Set `PLAIN_TELEMETRY_BACKENDS='[]'`.
2. Run a generation.

**Expected:** The generation works. No **View trace** link is shown.

Result: ___ Notes: ______________________

### L. Model and Program Versions

**UAT-L01: Default model recorded** (§6.2) · Medium
1. Check any generation's details.

**Expected:** The model is `gemini/gemini-3.8-flash` and the program version is `baseline`.

Result: ___ Notes: ______________________

**UAT-L02: Thinking level setting** (§6.2) · Low
1. Set `PLAIN_LLM_THINKING_LEVEL=low` and run D01.
2. Compare the LLM span with an earlier run.

**Expected:** The span shows the low thinking level, and the output is still valid. Reset afterwards.

Result: ___ Notes: ______________________

**UAT-L03: Invalid API key** (§9 state machine) · High
1. Set `GEMINI_API_KEY` to an invalid value and run D01.

**Expected:** The generation fails with `provider_error` and a clear message. The key itself is never shown in the UI, logs, or traces. Restore the key afterwards.

Result: ___ Notes: ______________________

### M. Optimization Pipeline

**UAT-M01: Evaluate the baseline** (§13) · Medium
1. Run `uv run python dspy_pipeline/optimize.py evaluate --program enrich_operations`, or the documented equivalent.

**Expected:** Per-component scores (coverage, fidelity, and so on) and a total are printed for the dev set. The eval run also appears in the active trace backend.

Result: ___ Notes: ______________________

**UAT-M02: Optimize and produce an artifact** (§6.3) · Medium
1. Run the optimize command.

**Expected:** `artifacts/programs/enrich_operations/<version>.json` and a `.meta.json` are created. The meta file records the dataset hash, scores, model, thinking level, DSPy version, and date.

Result: ___ Notes: ______________________

**UAT-M03: App uses the new artifact** (§6.3) · High
1. Set `PLAIN_LLM_PROGRAM_VERSION=<version>` and restart.
2. Run D01.

**Expected:** The generation records the new program version and succeeds.

Result: ___ Notes: ______________________

**UAT-M04: Unknown program version** (§6.3) · Medium
1. Set `PLAIN_LLM_PROGRAM_VERSION=does-not-exist` and restart.

**Expected:** Startup fails with a clear message listing the available versions. It does not silently fall back to baseline. Reset afterwards.

Result: ___ Notes: ______________________

### N. Design System Sync

**UAT-N01: Stale token check** (§11.1) · Low
1. Edit `design/docs-to-ui/tokens.css` without running the sync script.
2. Run the design sync check the same way CI does.

**Expected:** The check fails and names the stale file. Revert the edit afterwards.

Result: ___ Notes: ______________________

---

## 6. Suggested Execution Order

| Session | Sections | Approx. time |
|---|---|---|
| 1 | A, B, C | 2 h |
| 2 | D, E, F | 2.5 h (D11 runs take a while) |
| 3 | G, H, J | 1.5 h |
| 4 | K, L | 1.5 h |
| 5 | M, N | 1–2 h (depends on how long optimization takes) |

Run **B01, D01, E01, G02, and J02** first as a smoke test. If any of them fails, stop and report before continuing.

## 7. Results Summary

| Section | Cases | Pass | Fail | Blocked | N/A |
|---|---|---|---|---|---|
| A. Setup and Configuration | 5 | | | | |
| B. Input Handling | 14 | | | | |
| C. Zip Safety | 5 | | | | |
| D. Generation Job and Status UI | 7 | | | | |
| E. Doc Page Content | 10 | | | | |
| F. Interactivity and Styling | 6 | | | | |
| G. Export | 5 | | | | |
| H. Feedback | 3 | | | | |
| J. Native Tracing | 9 | | | | |
| K. Langfuse Tracing | 6 | | | | |
| L. Model and Program Versions | 3 | | | | |
| M. Optimization Pipeline | 4 | | | | |
| N. Design System Sync | 1 | | | | |
| **Total** | **78** | | | | |

**Open defects**

| # | Case | Severity | Summary | Status |
|---|---|---|---|---|
| | | | | |

**Sign-off:** ______________ **Date:** ______________ **Decision:** Accept / Accept with conditions / Reject

---

## Appendix A: Creating the Hard-to-Make Test Files

Run each command from inside `uat-data/`. They only create files there.

```bash
# D13: zip-slip entry
python -c "import zipfile; z=zipfile.ZipFile('zip-slip.zip','w'); z.writestr('../../evil.py','x = 1\n'); z.close()"

# D14: symlink entry (Unix permission bits mark it as a link)
python -c "import zipfile; i=zipfile.ZipInfo('link.py'); i.external_attr=(0o120777<<16); z=zipfile.ZipFile('zip-symlink.zip','w'); z.writestr(i,'/etc/passwd'); z.close()"

# D15: ~60 MB of zeros, compresses to well under 5 MB
python -c "import zipfile; z=zipfile.ZipFile('zip-bomb.zip','w',zipfile.ZIP_DEFLATED); z.writestr('big.py', b'#'*60_000_000); z.close()"

# D16: 5,001 tiny entries
python -c "import zipfile; z=zipfile.ZipFile('zip-many.zip','w'); [z.writestr(f'm{i}.py','x=1\n') for i in range(5001)]; z.close()"

# D12: ~5.2 MB file
python -c "open('too-large.json','w').write('{\"pad\":\"' + 'a'*5_450_000 + '\"}')"

# Non-UTF-8 Python file for D17
python -c "open('latin1.py','wb').write('# caf\xe9\nx = 1\n'.encode('latin-1'))"
```

For **D11** (large OpenAPI), generate a spec with a few hundred operations and long descriptions, or use a large real public spec. Check that the file is between 4 and 5 MB.
