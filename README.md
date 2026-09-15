# cad2ai

Turn proprietary AutoCAD `.dwg` drawings into a compact, structured JSON payload and
have **DeepSeek** reason over it — sheet QA, bill of materials, complexity metrics,
standards compliance.

The problem this solves is not "call an LLM with a DXF". DWG is a closed binary
format, and a naive `dxf2json` round-trip throws away exactly the metadata that makes a
drawing reviewable: layer state, block attribute values, dimension *overrides*, text
styles, units. `cad2ai` keeps that metadata, packs it into a token-budgeted payload, and
teaches the model how to read it.

```
 ┌──────────────── Phase 1 ───────────────┐   ┌───── Phase 2 ─────┐   ┌──── Phase 3 ────┐
 │ .dwg                                   │   │ structured model  │   │ minified JSON     │
 │   ├─ ezdxf + odafc  (lossless, local)  │──▶│ layers / blocks / │──▶│ + schema brief      │──▶ DeepSeek
 │   └─ Autodesk Platform Services (cloud) │   │ text / dims / audit│  │ token-budgeted    │   │  (OpenAI SDK)
 └────────────────────────────────────────┘   └───────────────────┘   └───────────────────┘
```

## Highlights

* **Lossless first.** `.dwg` is read with `ezdxf` + the `odafc` addon (`odafc.readfile`),
  i.e. the ODA File Converter converts *into* the DXF that `ezdxf` parses — no generic
  converter, no metadata loss. Every object graph is audited (`doc.audit()`) and proxy
  entities are counted rather than silently dropped.
* **Cloud fallback that is not a dead end.** If the local converter is missing or the file
  defeats it, the drawing is uploaded to **Autodesk Platform Services** (2-legged OAuth →
  OSS signed-S3 upload → Model Derivative) and the structural manifest is normalised into
  the same model shape — explicitly flagged `"lossless": false` so nobody mistakes
  manifest counts for object counts.
* **Honest payload.** Text, dimension values, units, block attribute fill rates and layer
  state are kept; overlong lists are *degraded* (aggregated, then capped) with every
  omission announced in `meta.truncations` so the model can say "I cannot see the rest"
  instead of guessing.
* **DeepSeek through the OpenAI SDK**, with `Retry-After`-aware backoff, JSON-mode repair,
  truncation detection, empty-response retries and token accounting.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt              # ezdxf, openai, python-dotenv, requests
cp .env.example .env                         # then put your real DEEPSEEK_API_KEY in it
```

For `.dwg` input also install the **ODA File Converter** (free, from
<https://www.opendesign.com/guestfiles/oda_file_converter>) — see
[`docs/RUNBOOK.md`](docs/RUNBOOK.md#1-oda-file-converter-phase-1) for per-OS steps.
`.dxf` input needs nothing extra. Autodesk Platform Services credentials are only needed
for the fallback path.

Check the whole environment at any time:

```bash
python main.py doctor            # human report
python main.py doctor --json     # machine-readable, safe to paste into a ticket
```

## Five-minute tour

```bash
# 1. a real-looking sample drawing (or use your own .dwg / .dxf)
python scripts/gen_sample_dxf.py samples/demo.dxf
python scripts/gen_sample_dxf.py --scheme mech samples/mechanism.dxf

# 2. phases 1+2: parse, structure, build the payload, write artifacts
python main.py extract samples/demo.dxf --out out/demo
python main.py payload samples/mechanism.dxf | head -c 400

# 3. see exactly what the model would be told, then run phase 3
python main.py prompt samples/demo.dxf --task sheet_review --system-only
python main.py analyze samples/demo.dxf --task sheet_review --out out/demo --show-markdown

# no API key / no spend? build the payload and stop:
python main.py analyze samples/demo.dxf --dry-run --out out/demo
```

`analyze` writes everything needed to audit the answer:

| artifact            | what it is                                                            |
| ------------------- | --------------------------------------------------------------------- |
| `cad_model.json`    | full Phase 2 extraction (pretty JSON, human-scale)                     |
| `payload.json`      | the exact minified bytes sent to DeepSeek                              |
| `analysis.json`     | the model's answer, parsed                                             |
| `analysis.md`       | the same answer rendered as a readable report                          |
| `ai_meta.json`      | model id, finish reason, attempts, token usage                         |
| `run_manifest.json` | timings, backend, warnings, error, and the **masked** config          |
| `aps_manifest.json` | only on the Autodesk path with `--raw-manifest`: untouched manifest   |

Because `payload.json` is what was actually sent, a disputed answer can be reproduced
byte-for-byte (`python main.py analyze --help` shows how to raise the budget).

## The three phases

### Phase 1 — parsing (`cad2ai/parser.py`, `cad2ai/dwg_version.py`, `cad2ai/aps.py`)

| backend id            | path                                                       | lossless |
| --------------------- | ---------------------------------------------------------- | -------- |
| `ezdxf`               | `.dxf` read directly                                       | yes      |
| `ezdxf-recovered`     | `.dxf` re-read with `ezdxf.recover` after a failed read    | yes*     |
| `odafc.readfile`      | `.dwg` → DXF → `ezdxf.readfile` (primary path)             | yes      |
| `odafc.convert+dxf`   | converter output re-read tolerantly (broken proxy graphics) | yes*     |
| `aps-model-derivative`| Autodesk Model Derivative structural manifest              | **no**   |

`load_drawing()` sniffs the 6-byte `AC10xx` sentinel *before* touching any converter, so:

* pre-R13 files (`AC1004`…`AC1009`) are rejected with an actionable error unless
  `CAD2AI_ALLOW_LEGACY_VERSIONS=1`;
* `AC1036` (R2024+) is converted down to `AC1032` — the newest version `ezdxf` can
  represent — and the run records that;
* encrypted / eTransmit-packed / non-CAD files each get their own error class and hint.

Timeouts: `odafc` exposes none, so `_run_bounded()` runs the converter under a wall-clock
limit (`ODA_TIMEOUT`) in a temp workspace that is always cleaned up.

### Phase 2 — structuring (`cad2ai/structurer.py`, `discipline.py`, `payload.py`)

* **Layers**: name, ACI colour (+hex), linetype, lineweight, on/frozen/locked/plotted,
  and per-layer counts of entities, annotations, text, dimensions, xrefs, proxies. A layer
  referencing a linetype missing from the `LTYPE` table is reported as a finding.
* **Discipline inference**: layer-name profiles weighted by entity counts, corroborated by
  linetype/text-style/dimension-style signals, with per-discipline share and the top
  contributing layers — `architectural`, `mechanical`, `electrical`, `plumbing`,
  `structural`, `civil`, `mixed` or `undetermined`.
* **Complexity & reuse**: per-layout entity histograms, block reference counts, attribute
  tag inventories and a `leverage` figure (`refs × entities per definition`) that ranks
  reusable components.
* **Text**: `TEXT`/`MTEXT` (markup stripped, each sample capped at 160 characters), attribute values harvested from
  `INSERT`/`ATTRIB` with their **tags**, plus a per-layer histogram.
* **Dimensions**: measured value + units, dimension type, dimstyle, and the flags that
  matter in a review — `text_override` (group 1 ≠ `<>`), ordinate axes,
  user-positioned text, non-measured.
* **Payload**: minified (`separators=(",", ":")`, `ensure_ascii=False`), coordinates
  rounded, empty fields removed, then degraded step-by-step until it fits
  `CAD2AI_MAX_PAYLOAD_TOKENS` (aggregation before deletion), with `meta.counts`,
  `meta.truncations` and `meta.degraded` describing what the model is *not* seeing.

Payload top-level keys: `cad_schema, source, document, layers, layer_stats, entities,
layouts, blocks, discipline, stats, linetypes, text_styles, dimension_styles, text,
dimensions, warnings, table_counts, truncations, meta`.

### Phase 3 — DeepSeek (`cad2ai/prompts.py`, `cad2ai/ai_client.py`)

* OpenAI-compatible: `openai.OpenAI(base_url="https://api.deepseek.com", api_key=...)`,
  key read from `DEEPSEEK_API_KEY` (process env or `.env`).
* The **system prompt teaches the schema**: field meanings, ACI colour table, `BYLAYER`
  semantics, unit conversions, the `source.lossless` caveat, and 10 grounding rules
  ("cite a JSON path for every finding", "never invent a quantity", "report gaps in
  `data_gaps`").
* Tasks: `sheet_review`, `bom`, `complexity_metrics`, `standards_compliance`,
  `discipline_summary`, `custom` (aliases like `--task qa` / `--task materials` work too).
  Each has a strict output schema, so `analysis.json` is machine-usable.
* Reliability: `max_retries=0` on the SDK (the client owns backoff), retry only
  429/5xx/transport, honour `Retry-After` (clamped), bounded retries for DeepSeek's
  documented *empty JSON content*, JSON repair (fences, trailing commas, concatenated
  objects), and a hard failure — never a partial object — when `finish_reason == "length"`.
* Cost control: per-section caps + budget, optional batching with bounded concurrency,
  `CAD2AI_DEEPSEEK_MIN_INTERVAL_MS` pacing, and prompt-token accounting written back into
  `run_manifest.json` as a tokenizer calibration factor for the next run.

## Configuration

Everything is environment-driven (see `.env.example` for the annotated list). Precedence:
**explicit CLI flag → process environment → `.env` → built-in default**.

| variable | default | meaning |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | — | required for Phase 3 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `DEEPSEEK_MODEL` | `deepseek-flash` | any model your account can access |
| `DEEPSEEK_MAX_TOKENS` | `8000` | answer budget |
| `DEEPSEEK_THINKING` | `disabled` | `enabled` = chain of thought (`DEEPSEEK_REASONING_EFFORT=low\|high\|max`) |
| `DEEPSEEK_MAX_ATTEMPTS` | `5` | retries for 429/5xx/transport only |
| `CAD2AI_MAX_PAYLOAD_TOKENS` | `120000` | payload budget that drives degradation |
| `CAD2AI_MAX_TEXT_ITEMS` / `…_MAX_DIMENSIONS` / `…_MAX_BLOCKS` / `…_MAX_LAYERS` | `800/400/120/200` | per-section caps |
| `CAD2AI_FLOAT_PRECISION` | `3` | decimal places kept for coordinates |
| `CAD2AI_ALLOW_LEGACY_VERSIONS` | `0` | accept pre-R13 DWG sentinels |
| `ODA_EXECUTABLE` | on `PATH` | ODA File Converter binary |
| `APS_CLIENT_ID` / `APS_CLIENT_SECRET` / `APS_BUCKET_KEY` | — | required for the Autodesk fallback |
| `APS_OUTPUT_FORMAT` | `svf2` | `svf` is the legacy fallback |
| `APS_TRANSLATION_TIMEOUT` | `900` | seconds spent polling the manifest |

CLI overrides exist for the frequently-tuned subset (`--payload-tokens`, `--max-text`,
`--max-dimensions`, `--max-blocks`, `--max-layers`, `--float-precision`, `--include-handles`,
`--model`, `--max-tokens`, `--thinking`, `--temperature`).

## Errors and exit codes

Every failure is a `Cad2AiError` subclass with a human `message`, an actionable `hint`,
and machine-readable `details`. The CLI maps them to distinct exit codes so a batch runner
can tell "bad input" from "retry later":

| code | meaning | examples |
| --- | --- | --- |
| `0` | success | |
| `1` | unexpected bug | wrap with `CAD2AI_TRACEBACK=1` for the stack trace |
| `2` | configuration | missing `DEEPSEEK_API_KEY`, malformed `CAD2AI_*` value, bad `--env-file` |
| `3` | unsupported DWG version | `AC1009` floor, unreadable sentinel |
| `4` | parse/input | not a CAD file, corrupt DXF, ODA File Converter not installed |
| `5` | Autodesk/APS | auth/scope error, upload failure, translation failure/timeout, expired URN |
| `6` | DeepSeek | 401/402 (not retried), 429/5xx after backoff, truncated or unparsable answer |

`--json` reports failures as `{"ok": false, "error": {...}}` on stdout, so a queue worker
never has to parse prose.

## Library use

```python
from cad2ai.config import Settings
from cad2ai.pipeline import Pipeline

settings = Settings.from_env()
pipeline = Pipeline(settings)

report = pipeline.run("drawings/A-101.dwg", task="sheet_review", brief="permit set", out_dir="out/a101")
print(report.summary["payload"]["token_estimate"], report.usage)
for finding in report.analysis["findings"]:
    print(finding["severity"], finding["title"], finding["evidence"])
```

Composable pieces: `parser.load_drawing`, `structurer.build_cad_model`,
`payload.build_payload` / `split_batches`, `prompts.build_messages`,
`ai_client.DeepSeekClient.complete_json`, `aps.ApsClient.extract`,
`pipeline.extract` (phases 1+2 only).

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest            # 268 tests, all offline (~6 s)
```

The suite builds real DXF documents with `ezdxf`, drives the ODA and Autodesk paths with
scripted fakes, and stubs the OpenAI transport (real `openai` exception objects), so
retry/`Retry-After`/JSON-mode/truncation behaviour is exercised without a network or a key.

## Known limits (deliberate, not silent)

* `odafc` cannot return an object graph for `AC1036`+ directly: the converter down-levels
  to `AC1032`, and any feature `ezdxf` cannot represent is counted as a proxy, not invented.
* The Autodesk fallback sees **structure, not geometry**: no colours, no dimensions, no
  block definitions. Payloads built from it say so (`source.lossless: false`) and Phase 3
  is told to report those as `data_gaps`.
* `token_estimate` is a heuristic; after each call the real
  `usage.prompt_tokens` is stored as a calibration factor.
* Proxy/`ACAD_PROXY_ENTITY` payloads are counted and hashed, not decoded.

## Layout

```
cad2ai/
  __init__.py     lazy public API (no heavy imports at package import time)
  errors.py       Cad2AiError hierarchy + exit codes
  config.py       .env loading, validation, masking
  dwg_version.py  AC10xx sentinel table + policy
  dxfutils.py     safe DXF access, rounding, warnings, markup stripping
  parser.py       Phase 1: ezdxf + odafc (audit, recover, bounded converter)
  aps.py          Phase 1 fallback: Autodesk OSS + Model Derivative
  structurer.py   Phase 2: CadModel (layers, blocks, text, dimensions)
  discipline.py   layer/linetype/table based discipline inference
  payload.py      Phase 2b: minification, token budget, degradation ladder
  prompts.py      Phase 3: system brief, task specs, message assembly
  ai_client.py    Phase 3: DeepSeek via the OpenAI SDK (retry, usage, JSON repair)
  pipeline.py     orchestration + artifacts + markdown rendering
  cli.py          argparse front-end (doctor/extract/analyze/payload/prompt/aps)
main.py           entry point
scripts/gen_sample_dxf.py  sample drawing generator (arch / mech / mixed)
docs/RUNBOOK.md   operator guide
tests/            268 offline tests
```

## Security

* Secrets are only read from the environment; `Settings.to_safe_dict()` masks anything that
  looks like a key and that is what lands in `run_manifest.json`.
* `.env` is git-ignored (`.env.example` is the template).
* Drawings sent to Autodesk are stored in your own bucket with a `transient` policy;
  `--delete-after` removes the object once the manifest is fetched. Model Derivative and
  DeepSeek both receive *derived* data, never your original file, unless you use the APS path.
