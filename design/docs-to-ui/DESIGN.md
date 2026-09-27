---
name: "Docs-to-UI"
category: "Developer Tools"
surface: web
colors:
  background: "#ffffff"
  surface: "#f5f5f5"
  foreground: "#111111"
  muted: "#646464"
  meta: "#707070"
  border: "#dedede"
  accent: "#7747e0"
  accent-on: "#ffffff"
  success: "#0a7d38"
  warn: "#874c00"
  danger: "#cf1323"
---

# Docs-to-UI

> Category: Developer Tools

> Surface: web

*Calm, paper-quiet reference design for API documentation: neutral surfaces, one restrained purple accent, and code treated as a first-class citizen.*

Docs-to-UI is a local, single-user developer tool. It turns OpenAPI documents and Python codebases into interactive API documentation. The system serves three surfaces, each at its own density:

- **Doc page:** the generated documentation, and the main product. It is comfortable for reading, and must also work as a standalone exported file.
- **App shell:** upload, generation progress, errors, file manifest and history. It is simple and functional.
- **Trace viewer:** a timeline of a generation's steps and LLM calls. It is the densest surface, because it is a tool rather than reading material.

`tokens.css` is the single source of truth. Every value in this document is copied from it. Components reference tokens with `var(--…)` and never use raw values.

## Principles

1. **Reference, not marketing.** Pages are dense, scannable and calm. There are no hero sections, no decorative imagery, and no gradients used for their own sake.
2. **Code is a first-class citizen.** Monospace text, code blocks and parameter tables get the same care as prose.
3. **Scannability over ornament.** A reader finds an endpoint, sees its method and path, and reads its parameters in seconds. Method badges and type labels do most of that work.
4. **The accent is rare.** `--accent` appears at most twice per screen: typically links and the active navigation item, or a primary button.
5. **Works offline and printed.** The doc page makes no network requests, and prints legibly with the sidebar hidden.

## Color Roles

| Token | Role | Light | Dark |
| --- | --- | --- | --- |
| `--bg` | Page canvas | `#ffffff` | `#141414` |
| `--surface` | Cards, panels, sidebar, code areas | `#f5f5f5` | `#1d1d1d` |
| `--surface-warm` | Subtle third tier (hover rows, zebra stripes) | `#fafafa` | `#272727` |
| `--fg` | Body text and headings | `#111111` | `#dcdcdc` |
| `--fg-2` | Secondary emphasis (table headers, labels) | `#2e2e2e` | `#adadad` |
| `--muted` | Secondary text: descriptions, helper text | `#646464` | `#9c9c9c` |
| `--meta` | Tertiary text: source locations, timestamps, IDs | `#707070` | `#8c8c8c` |
| `--border` | Dividers and container edges | `#dedede` | `#3e3e3e` |
| `--border-soft` | Inner row separators | `#f1f1f1` | `#303030` |
| `--accent` | Links, active nav item, primary button | `#7747e0` | `#9976dc` |
| `--accent-on` | Text on an `--accent` background | `#ffffff` | `#141414` |
| `--accent-hover` | Hover state for accent elements | `#6a3bd1` | `#ab8ce4` |
| `--accent-active` | Pressed state for accent elements | `#5b2fbd` | `#bca3ec` |
| `--success` | Succeeded status, positive states | `#0a7d38` | `#3fb266` |
| `--warn` | Warnings, the "not enriched" marker | `#874c00` | `#dcaa37` |
| `--danger` | Failed status, errors, destructive actions | `#cf1323` | `#e5736f` |

**Rules**
- **Links always use `--accent`.** There is no separate link color.
- **`--muted` is darker than `--meta`** in the light theme and brighter than it in the dark theme. `--muted` is for text people read; `--meta` is for text people glance at.
- **Button text on the accent follows `--accent-on`.** It is white in light and near-black in dark, because white on the dark-theme purple does not meet contrast.

## Typography

| Token | Value |
| --- | --- |
| `--font-display` | `system-ui, -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif` |
| `--font-body` | `system-ui, -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif` |
| `--font-mono` | `ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, Monaco, Consolas, 'Liberation Mono', Courier, monospace` |

System fonts only. No web fonts are loaded, so exported pages stay self-contained and render instantly.

**Type scale**

| Token | Size | Use |
| --- | --- | --- |
| `--text-xs` | 12px | Badges, trace attribute keys, fine print |
| `--text-sm` | 13px | Parameter tables, sidebar entries, trace rows, code |
| `--text-base` | 15px | Body prose |
| `--text-lg` | 18px | Operation titles, H3 |
| `--text-xl` | 22px | Group headings, H2 |
| `--text-2xl` | 26px | Section titles |
| `--text-3xl` | 32px | Page title, H1 |
| `--text-4xl` | 38px | Reserved; rarely used in a reference tool |

- `--leading-body` is `1.5714` for prose; `--leading-tight` is `1.25` for headings.
- `--tracking-display` is `-0.01em`, applied at `--text-xl` and above.
- `--font-mono` is used for: paths, function signatures, parameter names and types, code blocks, inline code, durations and token counts in the trace viewer, and source locations.

## Spacing and Layout

**Spacing.** `--space-N` equals N × 4px:

| Token | Value |
| --- | --- |
| `--space-1` | 4px |
| `--space-2` | 8px |
| `--space-3` | 12px |
| `--space-4` | 16px |
| `--space-5` | 20px |
| `--space-6` | 24px |
| `--space-8` | 32px |
| `--space-12` | 48px |

**Section rhythm.** Vertical padding between major sections: `--section-y-desktop` 96px, `--section-y-tablet` 64px, `--section-y-phone` 48px.

**Containers.** `--container-max` is 1280px. Side gutters are `--container-gutter-desktop` 32px, `--container-gutter-tablet` 24px and `--container-gutter-phone` 16px.

**Page structure**
- **Doc page:** a fixed left sidebar `--d2u-sidebar-width` (280px) wide, then a main column. Prose stays at a readable line length; code blocks may use the full column width.
- **App shell:** a top header `--d2u-header-height` (56px) tall, above a single content column.

**Radius:** `--radius-sm` 4px (badges, inputs, buttons), `--radius-md` 8px (cards, code blocks), `--radius-lg` 12px (panels, dialogs), `--radius-pill` 999px (status pills).

**Elevation:** `--elev-flat` (`none`) is the default. `--elev-ring` (`0 0 0 1px var(--border)`) outlines cards. `--elev-raised` is reserved for popovers and floating panels: `0 2px 8px rgba(0, 0, 0, 0.1)` in light, `0 2px 8px rgba(0, 0, 0, 0.5)` in dark. Prefer whitespace and borders to shadows.

## Components and States

**Sidebar navigation (doc page)**
- Groups are collapsible headings in `--fg-2`.
- HTTP entries show a method badge and the path in `--font-mono` at `--text-sm`. Python entries show the name in `--font-mono`.
- The active item uses `--accent` text on `--surface-warm`. Hover uses `--surface-warm` with no color change.

**Operation card**
- **Header:** a method badge plus the path, or a function signature, in `--font-mono`. The summary follows in `--muted`.
- **Body sections:** description in prose, then the parameter table, code examples, and returns / response.
- **Source location:** in `--meta` and `--font-mono`, for example `acme/client.py:42`.
- **Frame:** `--bg` background, `--elev-ring` edge, `--radius-md` corners.
- **Collapsed state:** only the header row is shown.
- **"Not enriched" state:** a `--warn` label reading "Not enriched", plus one line in `--muted` explaining that only the original description is shown. The label always includes the text, never color alone.

**Parameter table**
- **Columns:** name (`--font-mono`), in, type (`--font-mono`), required, default, description.
- **Header row:** `--fg-2` on `--surface`. Rows are separated by `--border-soft`.
- **Required marker:** a text label "required" in `--danger`, not just an asterisk.

**Code block**
- **Colors:** `--d2u-code-bg` background, `--d2u-code-fg` text, `--d2u-code-border` edge, `--radius-md` corners.
- **Language tabs** (curl / Python / JSON): the active tab is underlined in `--accent`; inactive tabs use `--muted`.
- **Copy button:** after copying, it shows a "Copied" label for about 2 seconds.

**Method badges.** The method name in uppercase `--font-mono` at `--text-xs`, colored with `--d2u-method-*` text on its `--d2u-method-*-bg` background, `--radius-sm` corners.

**Status pills (app shell):** pending in `--meta`, running in `--d2u-info`, succeeded in `--success`, failed in `--danger`. Each always includes its text label.

**Status and error panels**
- The status panel shows the stage stepper (Bundle → Extract → Enrich → Overview → Merge). Batch progress is a bar filled with `--accent`.
- The error panel puts the error type in `--danger`, and the message with the file and line in `--font-mono`. The Retry button is a primary accent button.

**Trace waterfall**
- **Rows:** one row per span, indented by depth, with durations in `--font-mono`.
- **Bars:** colored with the `--d2u-span-*` tokens, on `--surface`.
- **Errors:** error spans use `--d2u-span-error` and also carry an "error" label.

**Buttons**
- **Primary:** `--accent` background with `--accent-on` text. Hover uses `--accent-hover`; pressed uses `--accent-active`.
- **Secondary:** `--bg` background with an `--elev-ring` edge and `--fg` text.

**Focus.** Every interactive element shows `--focus-ring` on `:focus-visible`: `0 0 0 3px rgba(119, 71, 224, 0.2)` in light, `0 0 0 3px rgba(153, 118, 220, 0.3)` in dark.

## Dark Theme

- **Where the values live:** light values in `:root`. Dark values override the same token names under `[data-theme="dark"]`, and under `@media (prefers-color-scheme: dark)` for `:root:not([data-theme="light"])`.
- **Which theme applies:** exported pages follow the reader's system setting. The app can force a theme with `data-theme`.
- **No theme rules in components.** Components contain no theme-specific CSS; switching themes only changes token values.
- **What stays the same:** layout, spacing, type and radius tokens are identical in both themes. Only colors, `--elev-raised` and `--focus-ring` change.
- **Surface order in dark:** the canvas `--bg` (`#141414`) is the darkest layer, and `--surface` (`#1d1d1d`) and `--surface-warm` (`#272727`) step progressively lighter.

## Docs-to-UI Extensions

These `--d2u-` tokens are specific to this product. Generic components shared across brands must not reference them.

**Info**

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--d2u-info` | `#7747e0` | `#9976dc` | Informational notices and the "running" status |

**HTTP method badges**

| Method | Text (light) | Background (light) | Text (dark) | Background (dark) |
| --- | --- | --- | --- | --- |
| GET — `--d2u-method-get` | `#0a7d38` | `#f6ffed` | `#3fb266` | `#132419` |
| POST — `--d2u-method-post` | `#0958d9` | `#e6f7ff` | `#4096ff` | `#111d2c` |
| PUT — `--d2u-method-put` | `#874c00` | `#fffbe6` | `#dcaa37` | `#312512` |
| PATCH — `--d2u-method-patch` | `#722ed1` | `#f9f0ff` | `#b37feb` | `#1d1126` |
| DELETE — `--d2u-method-delete` | `#cf1323` | `#fff2f0` | `#e5736f` | `#32191a` |
| Other — `--d2u-method-other` | `#646464` | `#fafafa` | `#adadad` | `#1d1d1d` |

Each background token is the text token's name with `-bg` appended.

**Code blocks**

| Token | Light | Dark |
| --- | --- | --- |
| `--d2u-code-bg` | `#f5f5f5` | `#1d1d1d` |
| `--d2u-code-fg` | `#2e2e2e` | `#dcdcdc` |
| `--d2u-code-border` | `#dedede` | `#3e3e3e` |

**Syntax highlighting** (for curl, Python and JSON examples)

| Token | Light | Dark |
| --- | --- | --- |
| `--d2u-syntax-keyword` | `#b31d28` | `#ff7b72` |
| `--d2u-syntax-string` | `#1a7431` | `#a5d6a7` |
| `--d2u-syntax-number` | `#005cc5` | `#79c0ff` |
| `--d2u-syntax-comment` | `#5c636b` | `#8b949e` |
| `--d2u-syntax-function` | `#6f42c1` | `#d2a8ff` |
| `--d2u-syntax-type` | `#005cc5` | `#79c0ff` |
| `--d2u-syntax-punctuation` | `#24292e` | `#c9d1d9` |

**Layout dimensions**

| Token | Value |
| --- | --- |
| `--d2u-sidebar-width` | 280px |
| `--d2u-header-height` | 56px |

**Trace span colors** (waterfall bars, by span type)

| Token | Light | Dark | Span type |
| --- | --- | --- | --- |
| `--d2u-span-request` | `#7747e0` | `#9976dc` | HTTP request |
| `--d2u-span-job` | `#0958d9` | `#4096ff` | Background job |
| `--d2u-span-llm` | `#722ed1` | `#9254de` | LLM call |
| `--d2u-span-db` | `#ad6800` | `#dcaa37` | Database query |
| `--d2u-span-stage` | `#0a7d38` | `#3fb266` | Generation stage |
| `--d2u-span-error` | `#cf1323` | `#e5736f` | Any span that errored |

## Motion

- **Tokens:** `--motion-fast` (0.1s) for hover and small state changes; `--motion-base` (0.2s) for expanding, collapsing and tab switches. Easing is `--ease-standard`, `cubic-bezier(0.4, 0.0, 0.2, 1)`.
- **What animates:** only opacity, color and height/transform on collapsibles. Nothing animates on page load, and scaling never starts from 0.
- **Reduced motion:** under `prefers-reduced-motion: reduce`, transitions on those same properties drop to 0. The copy button's "Copied" feedback still appears; it just doesn't animate.
- **Progress bars:** batch progress and waterfall bars may move linearly.

## Accessibility

- **Contrast:** body and UI text meets 4.5:1 against both `--bg` and `--surface`, in both themes. This includes method badge text on its badge background and syntax colors on `--d2u-code-bg`.
- **Graphic elements:** timeline bars and non-text indicators meet 3:1 against `--surface`.
- **Keyboard:** every interactive element is reachable by keyboard and shows `--focus-ring` on `:focus-visible`. Tabs and collapsibles use native `button` elements with appropriate ARIA state.
- **Never color alone:** method badges show the method name, status pills show their label, errors show the word "error", and "not enriched" is written out.
- **Print:** the print stylesheet hides the sidebar and feedback controls, and wraps long code lines instead of letting them overflow the page.

## Anti-patterns

- **No web fonts,** including Inter. System stacks only.
- **No raw colors in component CSS:** no hex, `rgb()` or `hsl()` outside `tokens.css`.
- **No green links.** Links use `--accent`.
- **No more than two accent uses per screen.** Info states use `--d2u-info` sparingly for the same reason.
- **No hero sections, marketing layouts, decorative gradients or stock imagery.**
- **No theme-specific rules inside components.** Override tokens instead.
- **No `--d2u-` tokens in components shared outside Docs-to-UI.**
- **No meaning conveyed by color alone.**
