# cad2ai · Sheet Review Console

A dark, blueprint-scanner dashboard for the JSON that `cad2ai`'s DeepSeek phase writes as
`analysis.json`. It is deliberately a **review console**, not a report: the release gate and
the severity HUD are at the top, and every finding expands into the exact payload paths it
was derived from — so a disputed answer can be checked in seconds.

```
out/<run>/analysis.json  ──▶  normalizeAnalysis()  ──▶  header gate · HUD · tabs (findings / layers / dimensions) · gap panels
```

## Quick start

```bash
cd web
npm install                      # or: pnpm install / yarn
npm run dev                      # http://localhost:3000  (binds 0.0.0.0)
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
components/ui/              card · badge · accordion · tabs · input   (shadcn, vendored)
lib/analysis.ts             types + normalizeAnalysis + analysisStats  (the defensive layer)
lib/analysis-source.ts      server-side resolution of analysis.json
lib/utils.ts                cn/thousands/percent/truncate
tailwind.config.ts          HSL-var colours, neon tokens, keyframes (accordion/glow/sweep)
next.config.mjs             ALLOWED_DEV_ORIGINS escape hatch for proxies/previews
```

## Dev notes

- `npm run dev` binds `0.0.0.0:3000`. Behind a host-based proxy, if the dev server refuses
  the origin: `ALLOWED_DEV_ORIGINS=3000-your-sandbox.e2b.app npm run dev`.
- No `next/font` / remote assets: the app builds and runs with no network at all.
- `tsconfig.json` uses `@/*` → repo root of `web/`, matching `components.json` aliases.
