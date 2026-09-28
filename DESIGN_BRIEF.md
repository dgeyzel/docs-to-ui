# Docs-to-UI: Design Brief for OpenDesign

**Purpose:** This brief is the input for creating the `docs-to-ui` design system and reference mockups in [OpenDesign](https://github.com/nexu-io/open-design).
**Related:** `SPEC.md` §11 (rendering, design system, export).
**Output location:** `design/docs-to-ui/` in the Docs-to-UI repository.

---

## 0. How to use this brief

1. **Fill in the blanks.** Complete §4 (visual direction) before starting. Everything else is already decided.
2. **Create the design system.** In OpenDesign's **Design System** page:
   - Start from the bundled **`default`** (Neutral Modern) system, or from one developer-tools system you like the look of (see §4).
   - Name the new system **`docs-to-ui`**.
   - Paste §1–§7 of this brief as the instructions.
3. **Make the mockups.** Create a **Prototype** project that uses the `docs-to-ui` design system, and ask for the three mockups in §7, one at a time. Use the sample content in §8.
4. **Review.** Check every item in §9. Iterate in OpenDesign until all of them pass.
5. **Hand off.** Copy the package and mockups into the repo as described in §10.

---

## 1. Product context

Docs-to-UI is a **local, single-user developer tool**. It takes an OpenAPI document or a Python codebase, and produces an **interactive API documentation page**. That page can be viewed in the app, or exported as a single self-contained HTML file.

There are three surfaces:

| Surface | What it is | Who looks at it |
|---|---|---|
| **Doc page** | The generated documentation: sidebar navigation, operation cards, parameter tables, code examples | Developers reading API docs. **This is the main product.** |
| **App shell** | Upload form, generation progress, errors, file list, history | The person running the tool |
| **Trace viewer** | Timeline of a generation's steps and LLM calls, token counts | The person debugging or tuning the tool |

## 2. Design principles

1. **Reference, not marketing.** Dense, scannable, calm. Nothing looks like a landing page: no hero sections, no decorative imagery, no gradients used for their own sake.
2. **Code is a first-class citizen.** Monospace text, code blocks, and parameter tables must be as carefully designed as prose.
3. **Scannability over ornament.** A reader should find an endpoint, see its method and path, and read its parameters in seconds. HTTP method badges and type labels do a lot of the work.
4. **Accent is rare.** Use `--accent` sparingly: at most two visible uses per screen (OpenDesign lints for this). Links and the active nav item are enough.
5. **One system, three densities.**
   - The doc page is comfortable for reading.
   - The app shell is simple.
   - The trace viewer is the densest: it is a tool, not reading material.
6. **Works offline and printed.** The doc page must look right as a standalone file, with no network access (§5).

## 3. Audience

- Developers who read API reference docs daily.
- Expectations are set by good developer-documentation sites.
- Most use both light and dark themes. Many use large monitors; some read on laptops.

## 4. Visual direction (fill in before starting)

| Question | Answer |
|---|---|
| 2–3 documentation sites whose look you like | ______________________ |
| What specifically you like about each | ______________________ |
| 3–5 mood words (for example: *precise, quiet, technical, warm, crisp*) | ______________________ |
| Starting system in OpenDesign (`default`, or a developer-tools system) | ______________________ |
| Accent color preference (a hex value, a hue, or "let OpenDesign propose") | ______________________ |
| Corner style (sharp / slightly rounded / rounded) | ______________________ |
| Anything to avoid | ______________________ |

## 5. Hard constraints

These are not negotiable. The implementation depends on them.

1. **Tokens only.** Every color, font, size, space, radius, shadow, and duration must come from a CSS custom property in `tokens.css`. Component CSS uses `var(--…)` only. The app has **no Tailwind**.
2. **No external resources.**
   - No web fonts from a CDN, no remote images, no icon fonts from a CDN. Exported pages must make zero network requests.
   - **Default fonts:** system font stacks.
   - If you really want a custom font, it must be shipped as `.woff2` files inside the package's `fonts/` folder. Note that this makes every exported page larger.
3. **Light and dark themes.**
   - Light values go in `:root`.
   - Dark values override the *same* token names under `[data-theme="dark"]`.
   - The same dark values also apply under `@media (prefers-color-scheme: dark)` when no `data-theme` is set.
   - Components never contain theme-specific rules.
4. **Accessibility.**
   - Body text contrast ≥ 4.5:1 and large text ≥ 3:1, against the actual background it sits on, in **both** themes.
   - Every interactive element has a visible `:focus-visible` style using `--focus-ring`.
   - Motion respects `prefers-reduced-motion`.
   - Don't rely on color alone. HTTP method badges also show the method name as text; error states also have an icon or label.
5. **No framework assumptions.** Components are server-rendered HTML with a little vanilla JS. Don't design anything that needs React or similar: no virtualized lists, no drag-and-drop.
6. **Print.** The doc page should print legibly. The sidebar hides and code blocks don't overflow the page.

## 6. Token requirements

### 6.1 OpenDesign's shared contract (all required)

`tokens.css` must declare **every** token in OpenDesign's shared token schema, in both themes wherever the value differs.

| Group | Tokens |
|---|---|
| Surface | `--bg`, `--surface`, `--surface-warm` |
| Foreground | `--fg`, `--fg-2`, `--muted`, `--meta` |
| Border | `--border`, `--border-soft` |
| Accent | `--accent`, `--accent-on`, `--accent-hover`, `--accent-active` |
| Semantic | `--success`, `--warn`, `--danger` |
| Fonts | `--font-display`, `--font-body`, `--font-mono` |
| Type scale | `--text-xs`, `--text-sm`, `--text-base`, `--text-lg`, `--text-xl`, `--text-2xl`, `--text-3xl`, `--text-4xl` |
| Leading and tracking | `--leading-body`, `--leading-tight`, `--tracking-display` |
| Spacing | `--space-1`, `--space-2`, `--space-3`, `--space-4`, `--space-5`, `--space-6`, `--space-8`, `--space-12` |
| Section rhythm | `--section-y-desktop`, `--section-y-tablet`, `--section-y-phone` |
| Radius | `--radius-sm`, `--radius-md`, `--radius-lg`, `--radius-pill` |
| Elevation | `--elev-flat`, `--elev-ring`, `--elev-raised` |
| Focus | `--focus-ring` |
| Motion | `--motion-fast`, `--motion-base`, `--ease-standard` |
| Layout | `--container-max`, `--container-gutter-desktop`, `--container-gutter-tablet`, `--container-gutter-phone` |

**Notes**
- The `--surface-warm`, `--fg-2`, `--meta`, and `--border-soft` slots may alias their sibling tokens (for example `--fg-2: var(--fg)`) if the design doesn't need a separate tier.
- `--font-mono` is heavily used in this product. Choose it deliberately. The default fallback stack (`ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Monaco, Consolas, monospace`) is fine if nothing better is available offline.
- The type scale needs a clearly readable `--text-sm`. It is used for parameter tables and trace details.

### 6.2 Docs-to-UI extensions (all prefixed `--d2u-`)

OpenDesign only allows brand-specific tokens as documented extensions, so every extra token uses the **`--d2u-` prefix**.
- Each one must be listed and explained in `DESIGN.md`.
- Each must have light and dark values.
- Where it makes sense, derive them from the shared tokens (for example `--d2u-span-error: var(--danger)`).

| Token | Used for |
|---|---|
| `--d2u-info` | Informational notices and the "running" status. The shared schema has success, warn, and danger, but no info. |
| `--d2u-method-get`, `--d2u-method-post`, `--d2u-method-put`, `--d2u-method-patch`, `--d2u-method-delete`, `--d2u-method-other` | HTTP method badge color (text or border) |
| `--d2u-method-get-bg` … `--d2u-method-other-bg` | Matching subtle badge backgrounds |
| `--d2u-code-bg`, `--d2u-code-fg`, `--d2u-code-border` | Code blocks and inline code |
| `--d2u-syntax-keyword`, `--d2u-syntax-string`, `--d2u-syntax-number`, `--d2u-syntax-comment`, `--d2u-syntax-function`, `--d2u-syntax-type`, `--d2u-syntax-punctuation` | Syntax highlighting in examples (curl, Python, JSON) |
| `--d2u-sidebar-width` | Doc-page sidebar width |
| `--d2u-header-height` | App shell header height |
| `--d2u-span-request`, `--d2u-span-job`, `--d2u-span-llm`, `--d2u-span-db`, `--d2u-span-stage`, `--d2u-span-error` | Trace waterfall bar colors by span type |

The app's design-sync script checks for every token in §6.1 and §6.2. A missing token fails the build.

## 7. Mockups to produce

Produce three separate single-page mockups. Each should be real HTML/CSS that uses only the tokens, and should show **both themes**: either a theme toggle on the page, or two copies of the page.

### 7.1 Doc page (`doc-page.html`), the most important mockup

**Layout:** a left sidebar with navigation groups, and a main content column with a readable line length. Code blocks may be wider than prose.

**Include:**
- **Page header:** API title, source language badge ("OpenAPI" or "Python"), and generation date.
- **Overview:** a short Markdown prose section, with a paragraph, a list, inline code, and a link.
- **Sidebar:**
  - 2–3 groups; one group expanded, one collapsed.
  - Each entry shows a method badge and path (for HTTP), or a monospace name (for Python).
  - The active item is highlighted.
- **Operation card** (at least three), each with:
  - a method badge plus path (or a function signature), with the summary line below;
  - a description in prose;
  - a **parameter table** with columns name (monospace), in/location, type (monospace), required (a badge or marker), default, and description;
  - a **code examples** block with language tabs (curl / Python / JSON), syntax highlighting, and a copy button;
  - a returns / response section;
  - a source location line (for example `acme/client.py:42`), in `--meta`.
- **States to show:**
  - one operation in the **"not enriched"** state: a visible marker plus a short explanation that only the original description is shown;
  - a collapsed operation card;
  - hover and focus states on the nav, tabs, and copy button;
  - "Copied" feedback on the copy button;
  - **feedback buttons** (👍/👎 or equivalent icons with labels) on the page and on one operation card, including the opened comment box.
- **Print:** a print stylesheet sketch with the sidebar hidden.

### 7.2 App shell (`app-shell.html`)

**Include:**
- **Header:** product name, and links to Generations and Traces.
- **Source form:**
  - tabs or a toggle for *Upload file / Upload .zip / Paste*;
  - a language selector (Auto-detect / OpenAPI / Python);
  - a size hint ("Max 5 MB");
  - a submit button.
- **Status panel:**
  - the current stage (Bundle → Extract → Enrich → Overview → Merge) as a stepper;
  - batch progress ("Enriching batch 7 of 18") with a progress bar;
  - an elapsed-time indicator.
- **Error panel:** the error type ("Input error"), the message with file and line (`src/acme/client.py:12`), and a **Retry** button.
- **File manifest:** "Files read (42 included, 7 skipped)", an expandable list, and skip reasons (for example "excluded: tests/", "not UTF-8", "nested archive").
- **Generations list:** a table with status badges (pending, running, succeeded, failed), language, input name, date, model, and program version.
- **Size-limit validation:** the message shown on the form.

### 7.3 Trace viewer (`trace-viewer.html`)

**Include:**
- **Trace list:** a dense table with root name, duration, status, and generation link, plus filter controls.
- **Waterfall:**
  - a tree of spans (request → job → stages → LLM calls), indented by depth;
  - horizontal timing bars colored with the `--d2u-span-*` tokens;
  - durations in `--font-mono`;
  - one span in the error state.
- **Span detail panel:** a key/value attribute list, with long values truncated and a "…[truncated]" marker.
- **LLM call view:** the model name; input and output messages in code-style blocks; and token counts (prompt / completion / total) as small stat tiles.
- **Generation summary strip:** total LLM calls, total tokens, wall time, and a "View trace" link.

## 8. Sample content for the mockups

Use realistic content, not lorem ipsum.

**OpenAPI example: "Petstore Plus API"**
- **Groups:** *Pets*, *Orders*, *Users*.
- **Operations:** `GET /pets`, `POST /pets`, `GET /pets/{petId}`, `DELETE /pets/{petId}`, `PATCH /orders/{orderId}`.
- **Parameters for `GET /pets`:**
  - `limit` (query, integer, optional, default `20`) — "Maximum number of pets to return (1–100)."
  - `status` (query, string, optional) — "Filter by availability: `available`, `pending`, `sold`."
  - `X-Request-Id` (header, string, optional).

**Python example: `acme` SDK**
- `acme.Client(api_key: str, *, timeout: float = 10.0)`
- `acme.Client.list_pets(self, limit: int = 20, status: str | None = None) -> list[Pet]`
- Source location: `acme/client.py:42`.

**Trace example**
- **Spans:**
  - `POST /generations` (120 ms)
    - `GenerateDocJob` (48.2 s)
      - `extract` (0.4 s)
      - `enrich.batch[0]` … `enrich.batch[3]` (8–12 s each)
      - `overview` (6.1 s)
      - `merge` (0.1 s)
- **LLM spans:** model `gemini-3.8-flash`. One LLM span has an error (`provider_error: 429 rate limited`).
- **Totals:** 5 LLM calls, 61,240 tokens.

## 9. Acceptance checklist

**Package**
- [ ] The folder is named `docs-to-ui`, and `manifest.json` has `"id": "docs-to-ui"`.
- [ ] `manifest.json` has `name` "Docs-to-UI", `category` "Developer Tools", a one-sentence `description`, and `source` provenance. It uses the fixed file names `DESIGN.md` and `tokens.css`.
- [ ] `DESIGN.md` has at least seven substantive `##` sections, covering:
  - visual theme and principles;
  - color roles, including both themes and all `--d2u-` extensions;
  - typography, including the monospace choice and the type scale;
  - spacing and layout, including the sidebar and content widths;
  - components and their states;
  - motion and reduced motion;
  - accessibility;
  - anti-patterns ("don'ts").
- [ ] `DESIGN.md` and `tokens.css` agree. Every value named in the prose exists as a token.

**Tokens**
- [ ] Every token in §6.1 and §6.2 is declared in `tokens.css`.
- [ ] Dark-theme overrides exist under both `[data-theme="dark"]` and `prefers-color-scheme: dark`.
- [ ] No token value loads anything from the network (fonts or `url()`).

**Mockups**
- [ ] All three mockups exist and use only `var(--…)` values. Search them for raw colors (`#`, `rgb(`, `hsl(`) outside `tokens.css`.
- [ ] Both themes look right on all three mockups.
- [ ] Contrast has been checked in both themes. This matters especially for `--muted`, `--meta`, syntax colors, and method badges.
- [ ] Keyboard focus is visible on every interactive element.
- [ ] The doc page is readable at a laptop width (about 1280 px) and on a large monitor (about 1920 px).
- [ ] The doc page mockup works when opened directly from disk with the network off.

## 10. Handoff into the repository

The repo lives inside WSL, and OpenDesign runs on Windows, so the handoff is a copy through Windows Explorer.

1. In Explorer, open `\\wsl.localhost\Ubuntu\home\<your-linux-user>\code\docs-to-ui\design\` (use your distro's name from `wsl -l -v` if it isn't `Ubuntu`). Create `docs-to-ui\` there if it doesn't exist.
2. Copy the package into it: `manifest.json`, `DESIGN.md`, `tokens.css`, plus `fonts\` if you used custom fonts.
3. Copy the three mockups into `design\docs-to-ui\reference\`.
4. Commit from the WSL terminal, not from a Windows Git tool:
   - `git add design/`
   - `git commit`
   - `git push`
   Files copied from Windows may arrive with CRLF line endings. `.gitattributes` normalizes them on commit, so `git status` may show them as changed once; that's expected.
5. From then on, the **repo copy is the source of truth**. To edit it in OpenDesign later:
   - re-import the same WSL folder with OpenDesign's local-folder import;
   - make the changes;
   - copy the results back the same way.
6. The coding agent uses `tokens.css` directly (through `scripts/sync_design.py`), and uses the `reference/` mockups as the visual target for the elements in `SPEC.md` §11.2. It never edits this folder.
