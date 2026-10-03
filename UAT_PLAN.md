# Docs-to-UI: User Acceptance Test Plan

**Based on:** `SPEC.md` v7
**Execution:** Manual
**Tester:** ______________
**Build / commit:** ______________
**Dates:** ______________

---

## 1. Purpose and Scope

This plan confirms that Docs-to-UI does what `SPEC.md` promises, from the point of view of the person using it. It covers both apps.

**Docs app**
- input handling and zip safety
- generation with the active model and prompt
- the doc page, export and feedback

**Tuning app**
- models, prompt versions and runtime settings
- gold sets, eval runs, metrics and run comparison
- DSPy optimization and promotion

**Docs app JSON API**
- submitting, waiting and fetching pages through `/api/v1/`, its errors, and the client script

**Both**
- tracing (native and Langfuse, chosen in the UI)
- containers
- design tokens

It does not repeat the automated test suite. Where a behavior is hard to trigger by hand, the case says how to force it through configuration or the Tuning app.

**Out of scope:** multi-user access, authentication, hosting, and mixed-language zips (spec §2 non-goals).

## 2. Entry and Exit Criteria

**Entry**
- [ ] The automated suites pass: `uv run --directory docs_app pytest`, `uv run --directory tuning_app pytest`, and both with `-m e2e`.
- [ ] The three code checks pass (`AGENTS.md` §1).
- [ ] The test-data kit (§4) has been prepared.
- [ ] A Gemini API key (generation) and an Anthropic API key (the default judge) with enough quota are available, set in both `docs_app/.env` and `tuning_app/.env`.
- [ ] For section K only: a Langfuse project, with its public key, secret key, base URL and project ID.
- [ ] For section R only: Docker Desktop with WSL integration.

**Exit**
- Every **Critical** and **High** case passes.
- Any **Medium** or **Low** failure is either fixed or logged with an agreed decision.
- The results summary (§7) is complete and signed off.

## 3. Severity and Result Codes

| Severity | Meaning |
|---|---|
| **Critical** | Core loop broken, data or security exposure, or an app won't start |
| **High** | A spec'd feature doesn't work, or gives wrong output |
| **Medium** | The feature works, but with a notable defect or poor feedback to the user |
| **Low** | Cosmetic issue or minor inconvenience |

**Results:** **P** = Pass, **F** = Fail, **B** = Blocked (couldn't run), **N/A** = not applicable.

For every **F**, record: the steps to reproduce, expected vs. actual behavior, the generation, eval run or optimization run ID and the trace ID if any, and a screenshot.

## 4. Test-Data Kit

Prepare these files in a `uat-data/` folder outside the repository before starting. Appendix A has one-line commands for the files that are hard to make by hand.

| ID | File | Contents |
|---|---|---|
| D01 | `petstore-3.0.json` | Small OpenAPI 3.0 JSON spec: about 5 operations, 2 tags, some operations with descriptions and some without |
| D02 | `service-3.1.yaml` | OpenAPI 3.1 YAML spec: about 10 operations |
| D03 | `openapi-multifile.zip` | Root `openapi.yaml` with relative `$ref`s to `schemas/*.yaml` and `paths/*.yaml` |
| D04 | `remote-ref.yaml` | OpenAPI spec with a `$ref: "https://example.com/schema.yaml"` |
| D05 | `broken.yaml` | Invalid OpenAPI (for example, broken YAML indentation on a known line) |
| D06 | `single_module.py` | One Python module with 3 public functions (with docstrings and type hints), 1 public class with 2 methods, and 1 `_private` function |
| D07 | `pkg-src-layout.zip` | A `src/acme/` package: `__init__.py` re-exports `Client` from `client.py` and lists it in `__all__`, plus `utils.py`, a `tests/` folder, a `.venv/` folder, and a `__pycache__/` folder |
| D08 | `github-style.zip` | Any Python package zipped inside a single top-level folder `acme-main/` |
| D09 | `syntax_error.py` | Python file with a syntax error on a known line (for example, line 12) |
| D10 | `xss_docstring.py` | Python function whose docstring contains `<script>alert('x')</script>` and `<img src=x onerror=alert(1)>` |
| D11 | `large-openapi.json` | OpenAPI spec of about **900 KB** with a few hundred operations |
| D12 | `too-large.json` | Any valid file of about **1.2 MB** |
| D13 | `zip-slip.zip` | An entry whose path is `../../evil.py` |
| D14 | `zip-symlink.zip` | An entry that is a symlink |
| D15 | `zip-bomb.zip` | Compresses to under 1 MB but expands to more than 50 MB |
| D16 | `zip-many.zip` | More than 5,000 tiny entries (still under 1 MB) |
| D17 | `zip-mixed-junk.zip` | Valid Python package plus a non-UTF-8 `.py` file, a nested `inner.zip`, and a `.png` |
| D18 | `mixed-lang.zip` | Python package plus an `openapi.yaml` |
| D19 | `two-entries.zip` | Two independent OpenAPI documents, `v1/openapi.yaml` and `v2/openapi.yaml` |
| D20 | `prompt-v2.json` | A prompt version export (made in M05) with its `version` changed to `imported` |
| D21 | `emoji-escaped.json` | Small OpenAPI 3.1 JSON spec whose title and a summary contain emoji, written as `\uXXXX` escapes (how `json.dumps` writes them) |
| D22 | `emoji-broken.json` | D21 with a JSON syntax error added near the end, on a known line |

---

## 5. Test Cases

Each case lists its spec reference, severity, steps, and expected result, followed by a line for the result and notes. **Default settings** means the seeded registry (Gemini 3.8 Flash active, Claude Sonnet 4.5 as default judge, `baseline` prompts active), native tracing selected on the Settings page, and all other settings at their spec defaults. "Docs app" is `https://localhost:8443`; "Tuning app" is `https://localhost:8444/tuning`.

### A. Setup and Configuration

**UAT-A01: Both apps and both workers start** (§14, §15) · Critical
1. Copy each app's `.env.example` to `.env` and fill in `DATABASE_URL` and the provider keys.
2. Run `uv run --directory tuning_app plain postgres sync`.
3. Start both apps with the `plain dev` commands from the README.

**Expected:** Each app's web server and job worker start with no errors. The Docs app's home page and the Tuning app's dashboard load.

Result: ___ Notes: ______________________

**UAT-A02: `.env.example` files are complete** (§16) · Medium
1. Compare `docs_app/.env.example` and `tuning_app/.env.example` with the configuration table in spec §16.

**Expected:** Every variable the app uses appears, with a placeholder value. No real secrets are present. `PLAIN_TELEMETRY_BACKENDS` appears nowhere.

Result: ___ Notes: ______________________

**UAT-A03: Local-only binding** (§2) · High
1. With both apps running, try to open each from another device on the same network, using the machine's LAN IP.

**Expected:** The connection is refused. Both apps are reachable only through `localhost` / `127.0.0.1`.

Result: ___ Notes: ______________________

**UAT-A04: Each worker serves only its own queue** (§14) · High
1. Stop the Tuning app (and so its worker), leaving the Docs app running.
2. In the Docs app, generate D01. Then start the Tuning app and run **Test connection** on any model.

**Expected:** The generation completes while the Tuning app is down. The connection test stays pending until the Tuning app's worker is running, and then completes. Neither worker logs an unknown-job error.

Result: ___ Notes: ______________________

**UAT-A05: `.env` files are ignored by git** (AGENTS §7) · High
1. Run `git status` and `git check-ignore docs_app/.env tuning_app/.env`.

**Expected:** Both files are ignored and never show up as changes.

Result: ___ Notes: ______________________

**UAT-A06: Docs app preflight on the shared database** (§13) · Low
1. Run `uv run --directory docs_app plain preflight`.

**Expected:** It passes, and doesn't suggest dropping the Tuning app's tables.

Result: ___ Notes: ______________________

### B. Input Handling (Docs app)

**UAT-B01: Paste OpenAPI JSON** (§4) · Critical
1. Paste the contents of D01 into the paste box.
2. Set the language to OpenAPI and submit.

**Expected:** A status fragment appears straight away and begins polling. The generation succeeds.

Result: ___ Notes: ______________________

**UAT-B02: Upload an OpenAPI YAML file** (§4) · Critical
1. Upload D02 without setting a language.

**Expected:** The language is detected as OpenAPI automatically, and the generation succeeds.

Result: ___ Notes: ______________________

**UAT-B03: Upload a single Python module** (§4) · Critical
1. Upload D06 without setting a language.

**Expected:** The language is detected as Python, and the generation succeeds.

Result: ___ Notes: ______________________

**UAT-B04: Multi-file OpenAPI zip** (§4, §10) · High
1. Upload D03.

**Expected:** The relative `$ref`s resolve. Operations and schemas from the referenced files appear on the doc page.

Result: ___ Notes: ______________________

**UAT-B05: Remote `$ref` is rejected** (§10, AGENTS §7) · High
1. Upload D04.

**Expected:** The generation fails with an input error that names the remote reference. No network request is made to `example.com`.

Result: ___ Notes: ______________________

**UAT-B06: Broken input fails before any model call** (§4) · High
1. Upload D05, then D09.

**Expected:** Each fails with `input_error`, showing the file and the correct line. The generation records no tokens or cost, and its trace has no LLM span.

Result: ___ Notes: ______________________

**UAT-B07: Python package zip in src layout** (§4, §10) · Critical
1. Upload D07.

**Expected:** Module paths start at `acme` (not `src.acme`). The generation succeeds.

Result: ___ Notes: ______________________

**UAT-B08: Default excludes** (§10) · High
1. On the D07 generation page, open the file manifest.

**Expected:** Files under `tests/`, `.venv/` and `__pycache__/` are listed as **skipped**, each with a reason. No operations from them appear on the doc page.

Result: ___ Notes: ______________________

**UAT-B09: GitHub-style root folder is stripped** (§10) · Medium
1. Upload D08.

**Expected:** Module paths do not include `acme-main`.

Result: ___ Notes: ______________________

**UAT-B10: Manifest counts** (§10) · Medium
1. On any zip generation, compare the "Files read (N included, M skipped)" line with the archive's contents.

**Expected:** The counts match. Every skipped file shows a reason.

Result: ___ Notes: ______________________

**UAT-B11: Language override** (§4) · Medium
1. Upload D18 with no override. Note which adapter is chosen.
2. Upload D18 again, choosing the other language explicitly.

**Expected:** In both runs one adapter is used, and the other language's files are listed as skipped. The override is respected.

Result: ___ Notes: ______________________

**UAT-B12: OpenAPI entry file** (§4) · High
1. Upload D19 with no entry file.
2. Upload it again with the entry file `v2/openapi.yaml`.

**Expected:** The first fails with `input_error` asking for an entry file. The second documents only the v2 API.

Result: ___ Notes: ______________________

**UAT-B13: Size cap, just under** (§3 D8) · High
1. Upload D11 (about 900 KB).

**Expected:** The upload is accepted and a generation is created.

Result: ___ Notes: ______________________

**UAT-B14: Size cap, over** (§3 D8, §10) · High
1. Upload D12 (about 1.2 MB).
2. Paste more than 1 MB of text.

**Expected:** Both are rejected at the form with a clear size message. No generation is created; the history list is unchanged.

Result: ___ Notes: ______________________

**UAT-B15: JSON with escaped emoji** (§10) · High
1. Upload D21 without setting a language.
2. Paste the contents of D21 and submit.

**Expected:** Both are detected as OpenAPI and succeed, with one operation, `POST /reactions`. (Before R7 both failed with *Invalid YAML/JSON: found invalid Unicode character escape code*.)

Result: ___ Notes: ______________________

**UAT-B16: Broken JSON with escaped emoji** (§10) · Medium
1. Upload D22.

**Expected:** The generation fails with **Input error**, an **Invalid JSON** message, and the line where the JSON actually breaks, not the line of the first emoji.

Result: ___ Notes: ______________________

### C. Zip Safety

For each case below, confirm afterwards that **no files were written anywhere on disk** outside the app's normal temp paths. Checking the repo folder for new files is enough.

**UAT-C01: Zip-slip path** (§10) · Critical
1. Upload D13.

**Expected:** `input_error` naming the unsafe path. No file is created outside the bundle.

Result: ___ Notes: ______________________

**UAT-C02: Symlink entry** (§10) · Critical
1. Upload D14.

**Expected:** The upload is rejected, with a message about the symlink.

Result: ___ Notes: ______________________

**UAT-C03: Zip bomb** (§10) · Critical
1. Upload D15.

**Expected:** It fails quickly with a limit error. The app stays responsive, and memory doesn't spike to the full expanded size.

Result: ___ Notes: ______________________

**UAT-C04: Too many entries** (§10) · High
1. Upload D16.

**Expected:** It fails with an entry-limit error.

Result: ___ Notes: ______________________

**UAT-C05: Junk entries are skipped, not fatal** (§10) · High
1. Upload D17.

**Expected:** The generation succeeds. The non-UTF-8 file, the nested zip and the image appear as skipped in the manifest, each with a reason.

Result: ___ Notes: ______________________

### D. Generation Job and Status UI (Docs app)

**UAT-D01: Status progression** (§4, §6.6) · High
1. Submit D02 and watch the status fragment.

**Expected:** The stage updates about every 2 seconds (bundle, generate, merge). On success, the browser moves to the doc page by itself.

Result: ___ Notes: ______________________

**UAT-D02: Large input is split into parts** (§6.4) · High · *Needs a Tuning app change*
1. In the Tuning app, edit the active model and set **Max input tokens** to 20000.
2. Submit D11 in the Docs app.

**Expected:** The status shows "Generated N of M parts", and the count rises. The page merges all parts, with one overview for the whole API. Record the duration. Restore the model's setting afterwards.

Result: ___ Notes: ______________________ Duration: ______

**UAT-D03: Polling stops on failure** (§6.6) · Medium
1. Submit D05 with the browser's network tab open.

**Expected:** An error fragment with a **Retry** button appears. The status requests stop after the failure response.

Result: ___ Notes: ______________________

**UAT-D04: Retry and regenerate** (§6.6) · High
1. On a succeeded generation, click **Regenerate**. On a failed one, click **Retry**.

**Expected:** Each creates a **new** generation from the stored input, using the current active model and prompt. The originals remain in the history list, unchanged.

Result: ___ Notes: ______________________

**UAT-D05: Soft timeout** (§6.6) · Medium · *Needs a configuration change*
1. Set `PLAIN_GENERATIONS_TIMEOUT_S=10` in `docs_app/.env` and restart the Docs app.
2. Submit D11 with the split from D02.

**Expected:** The generation fails with `timeout`, and the UI says so clearly. Reset the setting afterwards.

Result: ___ Notes: ______________________

**UAT-D06: Worker killed mid-run** (§6.6) · High · *Needs process control*
1. Submit D11 (split as in D02).
2. While it is generating, kill the Docs app's worker process.
3. Restart it and wait at least 5 minutes, which is the heartbeat timeout.

**Expected:** The generation ends as `failed` with `worker_lost`. It does not stay "running" forever.

Result: ___ Notes: ______________________

**UAT-D07: Generation history and records** (§13) · Medium
1. Open the history list and a finished generation.

**Expected:** Every generation from this session appears. A generation's page shows its strategy, model, prompt version, tokens and cost.

Result: ___ Notes: ______________________

**UAT-D08: Active choices shown read-only** (§6.5, §11.2) · Medium
1. Look at the hint under the Docs app's generation form.

**Expected:** It names the active model, the active prompt versions and the selected trace backends, and says they are chosen in the Tuning app. The Docs app offers no way to change them.

Result: ___ Notes: ______________________

**UAT-D09: Hybrid strategy option** (§6.3) · Low · *Needs a configuration change*
1. Set `PLAIN_GENERATIONS_ENABLE_HYBRID=true` in `docs_app/.env` and restart.
2. Generate D01 with the **Hybrid** strategy.

**Expected:** The form offers the strategy; the page is built from the parser's structure with model-written descriptions, and records `hybrid`. Reset the setting afterwards.

Result: ___ Notes: ______________________

### E. Doc Page Content

Use the D01 and D07 generations unless the case says otherwise.

**UAT-E01: Complete coverage** (§9.5 coverage) · Critical
1. Count the operations in D01, then the operation cards on the page.

**Expected:** Every operation appears exactly once.

Result: ___ Notes: ______________________

**UAT-E02: No invented content** (§9.5 faithfulness) · Critical
1. Compare the operations and parameters on the page against the source.

**Expected:** No operation or parameter appears that doesn't exist in the input.

Result: ___ Notes: ______________________

**UAT-E03: Existing descriptions respected** (§5) · High
1. For operations in D01 that already have descriptions, compare the page text with the source.

**Expected:** The page expands on the source description without contradicting it.

Result: ___ Notes: ______________________

**UAT-E04: Parameter tables** (§12) · High
1. Open 3 operations and check each parameter table.

**Expected:** Each parameter shows its name, location, type, required flag, default (if any) and a description.

Result: ___ Notes: ______________________

**UAT-E05: Examples are sensible** (§9.5 example validity) · High
1. Check the examples on 3 operations.

**Expected:** The JSON parses; the curl paths match real endpoints; the Python examples are valid and use real names.

Result: ___ Notes: ______________________

**UAT-E06: Stable IDs** (§5, D4) · High
1. Generate D01 twice (Regenerate) and compare the operation anchors (`#…`) in the page URL when clicking sidebar entries.

**Expected:** Operation IDs are `METHOD /path` for HTTP and qualified names for Python, identical across generations.

Result: ___ Notes: ______________________

**UAT-E07: Python public API rules** (§4) · High
1. On the D07 page, look for the `_private` function and for `Client`.

**Expected:** The `_private` function is absent. `Client` appears once, under `acme.Client`, with its source location pointing to `acme/client.py`.

Result: ___ Notes: ______________________

**UAT-E08: Source locations** (§5) · Medium
1. On the D06 page, check each operation's file and line against the source.

**Expected:** Every shown file path and line number is correct; none point outside the input.

Result: ___ Notes: ______________________

**UAT-E09: Overview and navigation groups** (§6.2) · High
1. Read the overview and check the sidebar groups.

**Expected:** The overview accurately summarizes the API. Every operation appears in the navigation, in sensible groups.

Result: ___ Notes: ______________________

**UAT-E10: Script injection is neutralized** (§5, AGENTS §7) · Critical
1. Generate docs from D10. View the page, then the HTML export.

**Expected:** No alert box appears in either. The `<script>` and `onerror` content is shown as text or removed, never executed.

Result: ___ Notes: ______________________

### F. Doc Page Interactivity and Styling

**UAT-F01: Sidebar navigation** (§12) · High
1. Click several sidebar entries.

**Expected:** The page scrolls to the right operation. The active group is shown as selected.

Result: ___ Notes: ______________________

**UAT-F02: Collapsible sections** (§12) · Medium
1. Collapse and expand several operation cards and groups.

**Expected:** Each works smoothly, with no page reload.

Result: ___ Notes: ______________________

**UAT-F03: Example language tabs and copy** (§12) · Medium
1. Switch between example tabs on an operation, then copy an example into an editor.

**Expected:** The content switches with no reload; the exact example text is pasted.

Result: ___ Notes: ______________________

**UAT-F04: No server calls from the doc page** (§12) · High
1. With the network tab open, use navigation, collapsing, tabs and copy on the doc page.

**Expected:** No network requests are triggered by these interactions.

Result: ___ Notes: ______________________

**UAT-F05: Themes** (§12) · Low
1. Click **Toggle theme** in either app, and reload.

**Expected:** The theme switches and is remembered. Every page stays legible in both themes.

Result: ___ Notes: ______________________

### G. Export

**UAT-G01: HTML export downloads** (§12) · Critical
1. On a succeeded generation, click **Export HTML**.

**Expected:** A single `.html` file downloads.

Result: ___ Notes: ______________________

**UAT-G02: Export works fully offline** (§12) · Critical
1. Stop the apps and open the exported file directly from disk.

**Expected:** The page renders with full styling. Navigation, collapsing, tabs and copy all work.

Result: ___ Notes: ______________________

**UAT-G03: Export is self-contained** (§12) · High
1. Open the export with the network tab open, and search the file for `hx-`.

**Expected:** No requests to external hosts or to the app. No feedback buttons, app links or HTMX attributes.

Result: ___ Notes: ______________________

**UAT-G04: JSON export** (§12) · Medium
1. Click **Export JSON**.

**Expected:** Valid JSON with `schema_version` 2, `strategy`, `surface`, `overview` and `operations`, matching the page.

Result: ___ Notes: ______________________

### H. Feedback

**UAT-H01: Page-level feedback** (§11.2) · High
1. Click 👍 on the whole page. Then click 👎 with a comment.

**Expected:** The feedback is saved and acknowledged, and still shown after a reload.

Result: ___ Notes: ______________________

**UAT-H02: Operation-level feedback** (§11.2) · High
1. Click 👎 on one operation card with a correction comment.

**Expected:** The feedback is saved against that specific operation. (Section N imports it into a gold set.)

Result: ___ Notes: ______________________

### J. Native Tracing

**UAT-J01: Trace link from a generation** (§11.4) · High
1. On a succeeded generation, click **View trace**.

**Expected:** The native trace page for that generation opens.

Result: ___ Notes: ______________________

**UAT-J02: One connected trace** (§11.1) · Critical
1. In that trace, inspect the waterfall.

**Expected:** The request, the job, each stage span and each LLM call all appear in **one** trace, as a correct parent/child tree.

Result: ___ Notes: ______________________

**UAT-J03: LLM call detail** (§11.4) · High
1. Open an LLM span.

**Expected:** It shows the model, the input and output messages, and token counts. The span carries `docs.model` and `docs.prompt_version`.

Result: ___ Notes: ______________________

**UAT-J04: Trace list and filters in both apps** (§11.4) · Medium
1. Open the trace list in the Docs app (`/traces`) and the Tuning app (`/tuning/traces`).
2. Filter by a generation, by error status, and (Tuning app) by an eval run from section P.

**Expected:** The same traces appear in both apps. The filters work. The list says which backends traces go to, and in the Tuning app links to Settings.

Result: ___ Notes: ______________________

**UAT-J05: No secrets in traces** (AGENTS §7) · Critical
1. Search several traces' attributes, and the spans table (`… WHERE attributes::text LIKE '%<first 8 chars of each key>%'`), for your Gemini and Anthropic keys.

**Expected:** No matches.

Result: ___ Notes: ______________________

**UAT-J06: Telemetry failure doesn't break generation** (§11.3) · High · *Developer-assisted*
1. Ask a developer to make the native exporter fail (for example, revoke its insert permission on the spans table).
2. Run a generation.

**Expected:** The generation still succeeds. A throttled warning appears in the logs; the UI shows no error.

Result: ___ Notes: ______________________

**UAT-J07: Retention pruning** (§11.3) · Low · *Needs a configuration change*
1. Set `PLAIN_TRACES_RETENTION_DAYS=0` in `docs_app/.env` and trigger the prune job.

**Expected:** Old spans are removed and generations are unaffected. Reset the setting afterwards.

Result: ___ Notes: ______________________

### K. Choosing Trace Backends (Tuning app Settings)

**UAT-K01: Langfuse can't be chosen without credentials** (§11.2) · High
1. With the `LANGFUSE_*` variables empty, open the Tuning app's **Settings** page.

**Expected:** Langfuse is greyed out, and the page names the missing variables. Neither app fails to start.

Result: ___ Notes: ______________________

**UAT-K02: Switching without a restart** (§11.2) · Critical
1. Untick **Native** and save. Wait 10 seconds and generate D01.
2. Tick **Native** again and save. Wait 10 seconds and generate D01 again.

**Expected:** The first generation's trace never appears in the trace list and it shows no **View trace** link; the second one's does. Neither app was restarted. The Docs app's form shows each selection read-only.

Result: ___ Notes: ______________________

Precondition for K03–K06: fill in the `LANGFUSE_*` variables in both apps' `.env` files and restart both apps once.

**UAT-K03: Langfuse only** (§11.2, §11.3) · High
1. Select only **Langfuse** and generate D01.

**Expected:** The trace appears in Langfuse with the same structure as in J02. **View trace** opens the Langfuse trace page. No new rows appear in the native trace list.

Result: ___ Notes: ______________________

**UAT-K04: Feedback mirrored as a score** (§11.2) · High
1. Give 👎 with a comment on the K03 generation.

**Expected:** A `user_feedback` score with the comment appears on the Langfuse trace. The feedback is also saved locally.

Result: ___ Notes: ______________________

**UAT-K05: Both backends** (§11.2) · Medium
1. Select **Native** and **Langfuse** and run a generation.

**Expected:** The trace appears in both places. **View trace** links to the native viewer.

Result: ___ Notes: ______________________

**UAT-K06: Langfuse unreachable** (§11.3) · High
1. Set `LANGFUSE_BASE_URL` to an unreachable host in both `.env` files, restart, and run a generation with Langfuse selected.

**Expected:** The generation succeeds normally, with no errors or slowdown visible to the user. Restore the setting afterwards.

Result: ___ Notes: ______________________

### L. Models and Runtime Settings (Tuning app)

**UAT-L01: Adding a model offers only supported parameters** (§7) · High
1. On **Models**, click **Add model** and type `anthropic/claude-sonnet-4-5`, then change it to `gemini/gemini-3.8-flash`.

**Expected:** The parameter inputs change with the model string. Gemini 3 offers **Reasoning effort** but never temperature, top p or top k. Saving stores the values typed and range-checked.

Result: ___ Notes: ______________________

**UAT-L02: Test connection** (§7) · High
1. Run **Test connection** on the seeded Gemini model, then on a model whose key variable isn't set.

**Expected:** The first shows success with a latency. The second fails and names the missing variable. No key value appears anywhere.

Result: ___ Notes: ______________________

**UAT-L03: Activate for the Docs app** (§6.5, §7) · Critical
1. Activate Claude Sonnet 4.5 for the Docs app, then generate D01 in the Docs app.

**Expected:** The Docs app's form shows the new model, and the generation records it. Activate Gemini again afterwards.

Result: ___ Notes: ______________________

**UAT-L04: Invalid API key** (§6.6) · High
1. Set `GEMINI_API_KEY` to an invalid value in `docs_app/.env`, restart the Docs app and run D01.

**Expected:** The generation fails with `provider_error` and a clear message. The key is never shown in the UI, logs or traces. Restore the key afterwards.

Result: ___ Notes: ______________________

**UAT-L05: Default judge** (§9.1, D16) · Medium
1. On **Settings**, set the default judge to the Docs app's active model.

**Expected:** The page warns that evals of that model would grade themselves. Only models enabled for judging are offered. Restore Claude Sonnet 4.5 afterwards.

Result: ___ Notes: ______________________

### M. Prompt Versions (Tuning app)

**UAT-M01: Create and edit a draft** (§8) · High
1. On **Prompts**, copy `openapi/llm/baseline` to a draft `v2`. Edit its instructions, add one few-shot example as JSON and save.

**Expected:** The draft saves. Invalid JSON, or an example that doesn't match the schema, is rejected with a message and nothing saved. Active versions can't be edited.

Result: ___ Notes: ______________________

**UAT-M02: Diff between versions** (§9.1) · Medium
1. On `v2`, use **Compare with** against `baseline`.

**Expected:** Added and removed lines of the instructions and examples are marked.

Result: ___ Notes: ______________________

**UAT-M03: Promote, and the Docs app uses it** (§8, D12) · Critical
1. Promote `v2`. Generate D01 in the Docs app.

**Expected:** `v2` is active and `baseline` a candidate. The Docs app's form shows `openapi/llm/v2`, and the generation records it.

Result: ___ Notes: ______________________

**UAT-M04: Roll back in one click** (§8) · High
1. On **Prompts**, click **Roll back to baseline**.

**Expected:** `baseline` is active again and the Docs app uses it for its next generation. The promotion history lists the promotion and the rollback.

Result: ___ Notes: ______________________

**UAT-M05: Export and import** (§8) · Low
1. Click **Download JSON** on `v2`. Change its `version` to `imported` (D20) and import it.

**Expected:** It imports as a draft with source `imported`. Importing a malformed file is refused with a message.

Result: ___ Notes: ______________________

### N. Gold Sets (Tuning app)

**UAT-N01: Starter sets** (§9.2) · Medium
1. On **Gold sets**, click **Load starter examples** twice.

**Expected:** One draft set per language appears, once; each example has a parser-seeded page.

Result: ___ Notes: ______________________

**UAT-N02: Add examples three ways** (§9.2) · High
1. Create a set "UAT OpenAPI". Add D01 (paste) seeded from the parser, D03 (zip) started empty, and D02 seeded from Gemini 3.8 Flash.

**Expected:** The input is read exactly as the Docs app reads it (the zip shows only its OpenAPI files). The model-seeded example shows progress and fills in its page when the worker finishes.

Result: ___ Notes: ______________________

**UAT-N03: Form editor** (§9.2) · High
1. On the D01 example, change a summary, add a parameter, add an example, remove an operation, then save. Then enter a 250-character summary and save.

**Expected:** Add and remove don't save until **Save expected page**. Operation IDs are derived (never typed) and shown as you edit. The long summary is rejected next to its field without saving. Each save appears in the history.

Result: ___ Notes: ______________________

**UAT-N04: Review, approve and split** (§9.2) · High
1. Try to approve the empty D03 example. Approve D01. Select two examples and **Assign split** → dev.

**Expected:** The empty example can't be approved. The set page counts approved examples per split and shows a content hash that changes when approved examples change.

Result: ___ Notes: ______________________

**UAT-N05: Import a generation and feedback** (§9.2) · High
1. On the set page, import a finished D01 generation. Then import the 👎 feedback from H02.

**Expected:** Each becomes a draft with the generation's input and page. The feedback example's notes hold the correction and the operation it was about. Imported items are marked as imported.

Result: ___ Notes: ______________________

**UAT-N06: Import a gold-set file** (§9.2) · Low
1. Import a valid gold-set JSON file, then one naming a disabled language.

**Expected:** The first creates the set with its examples; the second is refused with a message.

Result: ___ Notes: ______________________

### P. Evals and Metrics (Tuning app)

**UAT-P01: Run an eval** (§9.3, D13) · Critical
1. Approve at least 3 dev examples in "UAT OpenAPI". Start an eval run: `llm`, Gemini 3.8 Flash, the active prompt, Claude Sonnet 4.5 as judge.

**Expected:** The run shows progress and then a summary: the total and every metric with a 95% interval, component accuracy by component, tokens, generation and judge cost. It records the gold-set hash and metric version.

Result: ___ Notes: ______________________

**UAT-P02: Example detail** (§9.3) · High
1. Open an example of the run.

**Expected:** Expected and generated pages side by side, with missing and invented operations and wrong fields marked; the judge's claims (unsupported ones marked) and prose rating; links to the gold example and the trace.

Result: ___ Notes: ______________________

**UAT-P03: Parser baseline and comparison** (§9.3) · High
1. Run the same set with the `parser` strategy. Tick both runs and **Compare selected**.

**Expected:** The oldest run is the baseline. Every metric and component shows its change, and each example is marked better, worse or the same.

Result: ___ Notes: ______________________

**UAT-P04: Failures don't stop a run** (§9.3) · High
1. Unset `ANTHROPIC_API_KEY` in `tuning_app/.env`, restart the Tuning app, and run an eval with Claude Sonnet 4.5 as judge.

**Expected:** The run finishes. Each example shows a judge error, with faithfulness's judge half and prose quality at zero. Restore the key afterwards.

Result: ___ Notes: ______________________

**UAT-P05: Self-judging warning** (D16) · Medium
1. Start an eval whose judge is also the generation model (enable judging on it first).

**Expected:** The form and the run page warn that the model grades its own output.

Result: ___ Notes: ______________________

**UAT-P06: Metric weights** (§9.5) · Medium
1. On **Metrics**, set the prose quality weight to 0 and save. Start another eval.

**Expected:** A new metric version is created and recorded on the new run; earlier runs keep theirs. Setting every weight to 0 is refused.

Result: ___ Notes: ______________________

**UAT-P07: Dashboard** (§9.1) · Medium
1. Open the Tuning app's dashboard.

**Expected:** It shows the Docs app's model, the default judge, the active prompts, the latest scores per language and recent runs.

Result: ___ Notes: ______________________

### Q. Optimization (Tuning app)

**UAT-Q01: Optimize, evaluate and promote** (§9.4, D13) · High
1. Approve at least 3 train and 2 dev examples. Start an optimization run: base `openapi/llm/baseline`, BootstrapFewShot with defaults, Gemini 3.8 Flash as task model, Claude Sonnet 4.5 as judge.

**Expected:** The run shows its stage, then a trial log, a candidate `opt-<run>` with a diff against its base, and a dev-split eval run. When the eval finishes, **Promote** makes the candidate active with the eval's scores. Record the duration and cost.

Result: ___ Notes: ______________________ Duration / cost: ______

**UAT-Q02: Optimizer rules** (§9.4) · Medium
1. Try COPRO with Gemini 3.8 Flash as task model. Try MIPROv2 in a development environment without the `optimize` group.

**Expected:** COPRO is refused because the model doesn't accept a temperature. MIPROv2 is refused with the command that installs optuna.

Result: ___ Notes: ______________________

**UAT-Q03: A failing optimization** (§9.4) · Medium
1. Unset the task model's key and start a run.

**Expected:** The run fails with an error naming the missing variable. No candidate is created. Restore the key afterwards.

Result: ___ Notes: ______________________

### R. Containers

**UAT-R01: Images build with the right contents** (§15) · High
1. Build both images: `docker build --target docs …` and `--target tuning …`.
2. In each, check which packages import: `docker run --rm <image> python -c "import dspy"`.

**Expected:** Both build. The Docs image has no DSPy (its build fails if it does); the Tuning image has DSPy and optuna.

Result: ___ Notes: ______________________

**UAT-R02: Four containers, loopback only** (§15, AGENTS §0) · Critical
1. Follow the README: sync the schema from the Tuning image, then start both web servers and both workers.
2. Run `docker port` on both web containers, and try to reach them from another device on the network.

**Expected:** Both apps load at `http://127.0.0.1:8000` and `http://127.0.0.1:8001/tuning`. A generation and a Test connection complete. Ports are published on `127.0.0.1` only and unreachable from other devices.

Result: ___ Notes: ______________________

### S. Design System Sync

**UAT-S01: Design tokens applied** (§12) · Medium
1. Change one color token in `design/docs-to-ui/tokens.css`, run `uv run python scripts/sync_design.py`, and reload pages in both apps.

**Expected:** The change appears everywhere that token is used, in both apps. Revert the change afterwards.

Result: ___ Notes: ______________________

**UAT-S02: Stale token check** (§17) · Low
1. Edit `design/docs-to-ui/tokens.css` without running the sync script, then run `uv run python scripts/sync_design.py --check`.

**Expected:** The check fails and names the stale file. Revert the edit afterwards.

Result: ___ Notes: ______________________

### T. JSON API (Docs app)

Run these from the WSL shell, with the Docs app and its worker running (`uv run --directory docs_app plain dev --hostname localhost --port 8443`). `-k` skips the check of the dev server's local certificate. `python3 -m json.tool` pretty-prints a response. `<id>` is the `id` from the response to the submission.

**UAT-T01: Upload a file, wait, save the page** (§12.1) · Critical
1. `curl -k -i -F file=@uat-data/petstore-3.0.json https://localhost:8443/api/v1/generations`
2. `curl -k "https://localhost:8443/api/v1/generations/<id>/page?wait=60" -o page.json`
3. Open the generation in the browser using the `links.ui` path from step 1.

**Expected:** Step 1 answers `202` at once, with a `Location` header and a body with `"status": "pending"` and `links`; the body never contains the uploaded text. Step 2 writes valid JSON with `schema_version`, `surface`, `overview` and `operations`, the same content as **Export JSON** on the page from step 3.

Result: ___ Notes: ______________________

**UAT-T02: Submit pasted text as JSON** (§12.1) · High
1. `python3 -c "import json; print(json.dumps({'text': open('uat-data/service-3.1.yaml').read()}))" > body.json`
2. `curl -k -H 'Content-Type: application/json' --data @body.json https://localhost:8443/api/v1/generations`
3. Fetch its page with `wait=60`.

**Expected:** `202`, `"origin": "paste"`, and the page arrives.

Result: ___ Notes: ______________________

**UAT-T03: Zip with an entry file** (§12.1, §10) · High
1. Submit D19 with `-F file=@uat-data/two-entries.zip` and no entry, and wait for its page.
2. Submit it again with `-F entry=v2/openapi.yaml` added, and wait for its page.

**Expected:** The first page request answers `422 generation_failed`, and its `generation.error` asks for an entry file. The second succeeds and documents only `v2`.

Result: ___ Notes: ______________________

**UAT-T04: Invalid submissions** (§12.1) · High
1. POST with no file and no text: `curl -k -X POST -F language= https://localhost:8443/api/v1/generations`.
2. POST both a file and `-F text=x`.
3. POST D12 (over 1 MB).
4. POST D01 with `-F language=cobol`.

**Expected:** Each answers `400` with `"code": "invalid_input"`, a clear `message`, and `fields` naming the problem field where there is one. No generation is created; `GET /api/v1/generations` is unchanged.

Result: ___ Notes: ______________________

**UAT-T05: Pending and failed pages** (§12.1) · High
1. Submit D02 and immediately request its page **without** `wait`.
2. Submit D05 and request its page with `wait=60`.

**Expected:** Step 1 answers `409` with `"code": "not_ready"` and the generation's current status. Step 2 answers `422` with `"code": "generation_failed"`; `generation.error` has `input_error`, the file name and the line.

Result: ___ Notes: ______________________

**UAT-T06: The wait is capped** (§12.1, §16) · Medium
1. Set `PLAIN_API_MAX_WAIT_S=5` in `docs_app/.env` and restart the Docs app.
2. Submit D11 (the slow, large spec) and time `curl -k -o /dev/null -w '%{http_code}\n' ".../generations/<id>/page?wait=60"`.
3. Remove the setting and restart afterwards.

**Expected:** The request returns after about 5 seconds with `409`, not 60. `wait=abc` and `wait=-1` answer `400`.

Result: ___ Notes: ______________________

**UAT-T07: HTML through the API** (§12.1, §12) · Medium
1. `curl -k https://localhost:8443/api/v1/generations/<id>/page.html -o page.html` for a succeeded generation.
2. Stop the apps and open `page.html` from disk in the Windows browser (`\\wsl.localhost\Ubuntu\…`).

**Expected:** The same self-contained page as **Export HTML** (cases G02–G03). For a pending or unknown id the request answers `404` in JSON.

Result: ___ Notes: ______________________

**UAT-T08: List and filter** (§12.1) · Medium
1. `GET /api/v1/generations`, then `?status=failed`, then `?limit=1`.
2. Try `?status=done` and `?limit=500`.

**Expected:** Newest first; the filter returns only failed generations; `limit=1` returns one. The bad values answer `400` with `"code": "bad_request"`.

Result: ___ Notes: ______________________

**UAT-T09: Regenerate and feedback** (§12.1, §11.2) · Medium
1. `curl -k -X POST https://localhost:8443/api/v1/generations/<id>/regenerate`
2. On a succeeded generation: `curl -k -H 'Content-Type: application/json' -d '{"operation_id": "<an operation id from surface.operations>", "score": -1, "comment": "Wrong example"}' .../generations/<id>/feedback`
3. Send `{"score": 0}`, then an unknown `operation_id`.
4. Reload that generation's page in the browser.

**Expected:** Step 1 answers `202` with a new id and the same `input.sha256`. Step 2 answers `201`. Step 3 answers `400 invalid_input` and `404 not_found`. The page shows the 👎 on that operation, and it can be imported into a gold set like UI feedback (section N).

Result: ___ Notes: ______________________

**UAT-T10: The API documents itself** (§12.1) · Medium
1. `curl -k https://localhost:8443/api/v1/openapi.json -o d2u-api.json`
2. Upload `d2u-api.json` to the Docs app in the browser.

**Expected:** Valid OpenAPI 3.1 listing all eight operations. The generated page documents them, including the 👍 / 👎 wording, with emoji intact.

Result: ___ Notes: ______________________

**UAT-T11: Client script** (§12.1) · High
1. `uv run python scripts/d2u_client.py generate uat-data/petstore-3.0.json --out page.json --html page.html --insecure; echo $?`
2. The same with `uat-data/broken.yaml` (D05).
3. The same with `--timeout 1` on D11.
4. The same with the Docs app stopped.

**Expected:** Step 1 exits `0` and writes both files. Step 2 exits `1` and prints `input_error (broken.yaml:<line>)`. Step 3 exits `3` with a timeout message. Step 4 exits `1` with "Could not reach the Docs app". None of them leaves a partial `page.json` behind on failure.

Result: ___ Notes: ______________________

**UAT-T12: Local only, and refused from web pages** (§2, §12.1, AGENTS §0) · Critical
1. `ss -ltnp | grep 8443` in WSL.
2. `curl -k -i -H 'Sec-Fetch-Site: cross-site' -H 'Content-Type: application/json' -d '{"text": "x"}' https://localhost:8443/api/v1/generations`

**Expected:** The server listens on `127.0.0.1` only. Step 2 is refused with `400` and creates no generation, as a browser page on another site would be.

Result: ___ Notes: ______________________

---

## 6. Suggested Execution Order

| Session | Sections | Approx. time |
|---|---|---|
| 1 | A, B, C | 2 h |
| 2 | D, E, F, G, H | 2.5 h (D02 and D05 runs take a while) |
| 3 | J, K, L | 2 h |
| 4 | M, N | 2 h |
| 5 | P, Q | 2–3 h (depends on eval and optimization run times) |
| 6 | R, S | 1 h |
| 7 | T | 1.5 h |

Run **A01, B01, D01, E01, G02, J02, L03, P01 and T01** first as a smoke test. If any of them fails, stop and report before continuing.

## 7. Results Summary

| Section | Cases | Pass | Fail | Blocked | N/A |
|---|---|---|---|---|---|
| A. Setup and Configuration | 6 | | | | |
| B. Input Handling | 16 | | | | |
| C. Zip Safety | 5 | | | | |
| D. Generation Job and Status UI | 9 | | | | |
| E. Doc Page Content | 10 | | | | |
| F. Interactivity and Styling | 5 | | | | |
| G. Export | 4 | | | | |
| H. Feedback | 2 | | | | |
| J. Native Tracing | 7 | | | | |
| K. Choosing Trace Backends | 6 | | | | |
| L. Models and Runtime Settings | 5 | | | | |
| M. Prompt Versions | 5 | | | | |
| N. Gold Sets | 6 | | | | |
| P. Evals and Metrics | 7 | | | | |
| Q. Optimization | 3 | | | | |
| R. Containers | 2 | | | | |
| S. Design System Sync | 2 | | | | |
| T. JSON API | 12 | | | | |
| **Total** | **112** | | | | |

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
python3 -c "import zipfile; z=zipfile.ZipFile('zip-slip.zip','w'); z.writestr('../../evil.py','x = 1\n'); z.close()"

# D14: symlink entry (Unix permission bits mark it as a link)
python3 -c "import zipfile; i=zipfile.ZipInfo('link.py'); i.external_attr=(0o120777<<16); z=zipfile.ZipFile('zip-symlink.zip','w'); z.writestr(i,'/etc/passwd'); z.close()"

# D15: ~60 MB of zeros, compresses to well under 1 MB
python3 -c "import zipfile; z=zipfile.ZipFile('zip-bomb.zip','w',zipfile.ZIP_DEFLATED); z.writestr('big.py', b'#'*60_000_000); z.close()"

# D16: 5,001 tiny entries
python3 -c "import zipfile; z=zipfile.ZipFile('zip-many.zip','w',zipfile.ZIP_DEFLATED); [z.writestr(f'm{i}.py','x=1\n') for i in range(5001)]; z.close()"

# D12: ~1.2 MB file
python3 -c "open('too-large.json','w').write('{\"pad\":\"' + 'a'*1_250_000 + '\"}')"

# Non-UTF-8 Python file for D17
python3 -c "open('latin1.py','wb').write('# caf\xe9\nx = 1\n'.encode('latin-1'))"

# D21: emoji written as \uXXXX escapes, as json.dumps does by default
python3 -c "import json; open('emoji-escaped.json','w').write(json.dumps({'openapi':'3.1.0','info':{'title':'Reactions \U0001F44D API','version':'1'},'paths':{'/reactions':{'post':{'summary':'Add a \U0001F389 reaction'}}}}, indent=2))"

# D22: D21 with a stray ",]" on the line before the last
python3 -c "l=open('emoji-escaped.json').read().splitlines(); open('emoji-broken.json','w').write('\n'.join(l[:-1]+['  ,]',l[-1]]))"
```

For **D11** (large OpenAPI), generate a spec with a few hundred operations and long descriptions, or trim a large real public spec, so the file is between 850 and 1,000 KB. For **D19**, zip two small, unrelated OpenAPI documents under `v1/` and `v2/`.
