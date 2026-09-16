# cad2ai · Sheet Review Console

A dark, blueprint-scanner dashboard for the JSON that `cad2ai`'s DeepSeek phase writes as
`analysis.json`. It is deliberately a **review console**, not a report: the release gate and
the severity HUD are at the top, and every finding expands into the exact payload paths it
was derived from — so a disputed answer can be checked in seconds.

```
                                   ┌───────────────────────── service (../server.py) ─────────────────────────┐
browser ── drop .dwg/.dxf ──▶ POST /api/analyze ──▶ ezdxf+odafc / APS ──▶ payload ──▶ DeepSeek ──▶ analysis.json
                                   └──────────────────────────────────────────────────────────────────────────┘
                                                        │
   out/<run>/analysis.json ──▶ normalizeAnalysis() ──▶  header gate · HUD · tabs (findings / layers / dimensions) · gap panels
```

Two ways to get data on screen, both landing in the same console:

* **Read from disk** — the page picks up the last pipeline run with nothing running (`ANALYSIS_JSON=…`, `web/data/analysis.json`, or the newest `out/*/analysis.json`).
* **Upload a drawing** — `Workbench` posts to the FastAPI service, walks the user through the 70-80 s of extraction while it waits, and renders the response as soon as it lands. The disk path is still the initial state, so a stale-but-real run beats an empty form.

## Quick start

```bash
cd web
npm install                      # or: pnpm install / yarn
npm run dev                      # http://localhost:3000  (binds 0.0.0.0)
```

To use the upload flow as well, start the service in another terminal (from the repo root, in
the Python venv — see the root README, "HTTP service"):

```bash
DEEPSEEK_API_KEY=sk-your-key uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Production check (typecheck + build; this is what CI should run):

```bash
npm run typecheck && npm run build && npm start
```

There is nothing to configure to see it work: with no `analysis.json` present the page
renders the bundled sample (`A-101-FLOOR-PLAN-R2018.dwg`, 6 findings, hold verdict).

## Installing / refreshing the UI primitives

The four primitives this dashboard uses are **vendored** into `components/ui/` (that is the
shadcn model — the code belongs to you), so `npm install` is enough and no registry access
is needed at build time. To (re)install or extend them:

```bash
npx shadcn@latest init                 # already configured via components.json (new-york, css vars, @/ aliases)
npx shadcn@latest add card badge accordion tabs input
npx shadcn@latest add button dialog select   # optional extras
```

> The old `shadcn-ui@latest` package name is deprecated; use `shadcn@latest`.
> `components/ui/*` carry a header comment naming the CLI command that regenerates them.

Runtime dependencies: `framer-motion` (ingestion/entrance animation), `lucide-react`
(icons), `@radix-ui/react-accordion` + `react-tabs` + `react-slot` (the primitives'
behaviour), `class-variance-authority` / `clsx` / `tailwind-merge` (styling).
Dev/Tailwind: `tailwindcss@3`, `tailwindcss-animate`, `autoprefixer`.

## Feeding it real data

The page is a **server component** (`export const dynamic = "force-dynamic"`), so it re-reads
disk on every request — drop a new file and refresh. Resolution order:

1. `ANALYSIS_JSON=/abs/path/analysis.json npm run dev` (or `start`) — explicit file, the CI/kiosk hook.
2. `web/data/analysis.json` — a fixed demo copy (git-ignored).
3. The newest `out/*/analysis.json` under the repository root — i.e. **whatever your last
   pipeline run produced**, no copying required.
4. Otherwise: bundled sample (the header chip then reads `sample data`, not `live analysis.json`).

Produce a real file with the pipeline (needs `DEEPSEEK_API_KEY` in the repo's `.env`):

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/gen_sample_dxf.py samples/demo.dxf
python main.py analyze samples/demo.dxf --task sheet_review --out out/demo
cd web && npm run dev          # now reads ../out/demo/analysis.json
```

Without an API key, `analysis.json` cannot be produced (that is Phase 3), but you can still
inspect the exact payload the model would receive: `python main.py analyze <file> --dry-run`.

## The upload workbench (`components/dashboard/workbench.tsx`)

`Workbench` is a four-state machine — `idle → processing → success | error` — and it is the only
place that talks to the network. `page.tsx` stays a server component and hands it `initial`
(disk data, if any) plus `sample`.

* **idle** — drag-and-drop zone (`UploadPanel`): only `.dwg`/`.dxf` accepted, checked on drop *and*
  in the file input, size checked against what `/api/health` reported, plus the run options
  (task, brief, `dry run`, `keep artifacts`). A 415/413/422 is explained inline next to the field
  that caused it; a dead backend turns the zone grey with a "check connection" retry instead of
  letting you queue a doomed upload.
* **processing** — `ProcessingPanel`, because a real sheet review takes ~75 s: an asymptotic bar
  (it approaches 97 % and never lies about finishing), seven phases that advance on a schedule and
  name the file being worked on — *Parsing DWG Binary… → Extracting Metadata… → Building Payload →
  Running DeepSeek Analysis… → Normalising Verdict* — a `mm:ss` timer, the concurrency the server
  reported, and a console readout. **Cancel** detaches the browser (abort the fetch); the panel
  says so, because the service cannot preempt a Python thread.
* **success** — the upload zone is gone. `ReviewConsole` renders the response with the same
  components the disk path uses, under a summary strip: mode used, elapsed, payload size vs token
  budget, usage tokens, truncation warnings, timings, and download buttons for
  `analysis.json` / `report.md`.
* **error** — the failure panel shows HTTP status, `error.code`, `message`, `hint`, `retryable`
  and `details` verbatim from the server envelope, and the dropzone comes back so you can retry.
  Toasts mirror the outcome.

### Talking to the service

`lib/api.ts` resolves the base once per call:

1. `NEXT_PUBLIC_API_BASE` if set (absolute URL, or a path prefix such as `/backend`).
2. `http://localhost:8000` when the page itself is on `localhost`/`127.0.0.1` — the direct, CORS-covered dev path.
3. Otherwise same-origin `/api/*`, which `next.config.mjs` rewrites to `API_PROXY_TARGET`
   (`http://127.0.0.1:8000` by default) — the path a proxied preview, container or VM takes,
   where "localhost" would mean the user's laptop.

```bash
API_PROXY_TARGET= NEXT_PUBLIC_API_BASE=http://cad.internal:8000 npm run dev   # disable proxy, point at a host
API_PROXY_TARGET=http://10.0.0.5:8000 npm run build                           # bake a different backend into a build
```

`analyzeDrawing()` never throws on a `{"ok": false}` body it can read: it raises `ApiError`
carrying `status` + the server's `error` object, so the UI renders the server's own hint rather
than inventing one. `resolveTask` mismatches (`unknown_task` with `known_tasks`), `busy` with
`Retry-After`, and `extraction_timeout` all land in that panel.

`fetchHealth()` runs on mount and on demand; `probe=1` asks the *server* to make one tiny DeepSeek
completion, which is how you confirm a key without uploading 100 kB of drawing first.

### Data contract

| field in `analysis.json`                                    | where it renders |
| ----------------------------------------------------------- | ---------------- |
| `drawing`                                                    | header title |
| `discipline.{assigned,confirmed,comment}`                    | header chips + comment line |
| `confidence`                                                 | animated radial gauge (colour degrades below 0.85 / 0.6 / 0.4) |
| `findings[].{id,bucket,severity,title,detail,evidence,recommendation}` | tab 1 — searchable accordion; `evidence` in a monospace readout, `recommendation` in its own panel |
| `layer_findings[].{layer,issue,evidence}`                     | tab 2 — data table (prefix chip, blocking marker) |
| `dimension_findings[].{kind,count,issue,evidence}`            | tab 3 — data table with relative-share bars |
| `release_recommendation`                                      | the big status badge: red + pulse on `hold`, amber on `release_with_comments`, green on `release` |
| `effort_hours_estimate`                                       | rework-estimate metric block |
| `checks_not_possible_from_data`, `data_gaps`                  | bottom "what this cannot tell you" panels |

Nothing here trusts the input. `lib/analysis.ts` (`normalizeAnalysis`) tolerates what real
model output does: missing keys, numbers as strings, `evidence` given as a single joined
string instead of an array, severity spelled `critical`/`minor`, a confidence on a 0-100
scale (rescaled, and the rescaling is reported as an *ingest note*), verdicts spelled
`approve`/`blocked`/`conditional`. A malformed or unreadable JSON file does not crash the
page: it falls back to the sample and prints the reason. If you want strictness, that is the
place to add a zod schema — the rest of the app only consumes the normalised `Analysis` type.

## Layout & responsiveness

- CSS Grid for the outer stack and the HUD (`sm:grid-cols-2 xl:grid-cols-4`); Flexbox inside
  cards and the control bars.
- Header wraps to two columns at `lg`, the verdict/ring/estimate cluster is one flex row that
  reflows below `sm`.
- Tables scroll horizontally below `720–760px` and the layer table body is height-capped
  (`max-h-[62vh]`) with a sticky header, so a 40-layer sheet stays usable.
- Tab labels carry count bubbles (blocking counts in red) so the state is readable without
  opening a panel.
- Motion: header/ring/HUD/rows fade-and-slide in with staggered delays (framer-motion),
  accordion open/close uses the Radix height keyframes. All of it collapses under
  `prefers-reduced-motion: reduce`.
- Print: `@media print` flips the dark palette to white, so a review can be handed over as paper.

## Accessibility notes

Findings are a real `Accordion` (keyboard, `aria-expanded`), tabs are Radix Tabs (arrow-key
roving), the search has a labelled `type="search"` input, severity is never encoded by colour
alone (label text + shape), and the confidence gauge carries an `sr-only` value. Focus rings
are theme-coloured rather than removed.

## Files

```
app/layout.tsx              dark-by-default <html class="dark">, metadata, global CSS
app/page.tsx                bundled SAMPLE_ANALYSIS (top of file) + page composition
app/globals.css             light/dark token pairs, .code-surface/.hud-*, print + reduced-motion
components/dashboard/       status-header · confidence-ring · metric-hud · findings-panel
                            layer-table · dimension-table · data-gaps · blueprint-bg
                            workbench · upload-panel · processing-panel · payload-summary
                            review-console (the shared console body: props in, DOM out)
components/ui/              card · badge · accordion · tabs · input · toast   (shadcn, vendored)
lib/api.ts                  base-URL resolution, health/analyze/artifact calls, ApiError
lib/analysis.ts             types + normalizeAnalysis + analysisStats  (the defensive layer)
lib/analysis-source.ts      server-side resolution of analysis.json
lib/utils.ts                cn/thousands/percent/truncate
tailwind.config.ts          HSL-var colours, neon tokens, keyframes (accordion/glow/sweep)
next.config.mjs             ALLOWED_DEV_ORIGINS escape hatch for proxies/previews
```

## Dev notes

- `npm run dev` binds `0.0.0.0:3000`. Behind a host-based proxy, if the dev server refuses
  the origin: `ALLOWED_DEV_ORIGINS=3000-your-sandbox.e2b.app npm run dev`.
- `next build` and `next dev` fight over `.next`: stop the dev server before building, or the
  build can hang.
- `/api/*` is proxied to the service by a rewrite (`API_PROXY_TARGET`), so a production `next start`
  needs no extra web server; `API_PROXY_TARGET=` disables it and `NEXT_PUBLIC_API_BASE` wins outright.
  `POST /api/analyze` is `multipart/form-data` streamed by the same route — curl it through :3000 to prove it.
- No `next/font` / remote assets: the app builds and runs with no network at all.
- `tsconfig.json` uses `@/*` → repo root of `web/`, matching `components.json` aliases.
