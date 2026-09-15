# Runbook

Operator notes for deploying `cad2ai` on a workstation or in a batch job: what to install,
how to verify it, what each knob costs, and what to do when a run fails.

* [0. Preflight](#0-preflight)
* [1. ODA File Converter (Phase 1)](#1-oda-file-converter-phase-1)
* [2. Autodesk Platform Services app (fallback)](#2-autodesk-platform-services-app-fallback)
* [3. DeepSeek key and budget](#3-deepseek-key-and-budget)
* [4. Running a sheet set](#4-running-a-sheet-set)
* [5. Interpreting the artifacts](#5-interpreting-the-artifacts)
* [6. Troubleshooting](#6-troubleshooting)
* [7. CI and containers](#7-ci-and-containers)
* [8. Upgrades and drift](#8-upgrades-and-drift)
* [9. Data handling](#9-data-handling)

---

## 0. Preflight

```bash
python main.py doctor --json > doctor.json
jq '.problems' doctor.json
```

What must be true, and what breaks if it is not:

| check | good | if missing |
| --- | --- | --- |
| `phase1_local.oda_installed` | `true` for `.dwg` input | `.dwg` → exit 4 `DwgConverterNotInstalledError`; `.dxf` unaffected |
| `phase1_local.xvfb_available` | `true` on Linux | the converter may fail with an X11 error (it is a Qt app) |
| `deepseek.api_key_present` | `true` for Phase 3 | exit 2 `MissingEnvironmentVariableError`; `--dry-run` still works |
| `deepseek.model_known` | `true` | only a warning — set `DEEPSEEK_MODEL` to any id your account has |
| `autodesk_fallback.configured` | `true` if you rely on the cloud path | the fallback raises instead of uploading, with the missing variables in the hint |

Useful environment switches for a debugging session:

```bash
CAD2AI_LOG_LEVEL=DEBUG     # per-stage debug logging (also: -v / -vv on the CLI)
CAD2AI_TRACEBACK=1         # let unexpected errors raise with a stack trace
```

---

## 1. ODA File Converter (Phase 1)

`ezdxf`'s `odafc` addon shells out to this free converter; it is the only supported way to
read `.dwg` losslessly without AutoCAD itself.

| OS | install | notes |
| --- | --- | --- |
| Windows | installer from <https://www.opendesign.com/guestfiles/oda_file_converter> | default path `C:\Program Files\ODA File Converter\ODAFileConverter.exe`; found via `PATH` or `ODA_EXECUTABLE` |
| macOS | `.dmg` from the same page | `ODA_EXECUTABLE=/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter` |
| Linux | `.AppImage` | `chmod +x`, then `ODA_EXECUTABLE=/opt/oda/ODAFileConverter.AppImage`; needs `libopengl0`/`libxcb*` and **`xvfb`** |

```bash
# Linux, headless
sudo apt-get install -y xvfb
python main.py doctor | grep -i "ODA converter"
```

Behaviour worth knowing:

* `odafc.readfile(path)` converts to a temp DXF and then calls `ezdxf.readfile`. If that
  read fails (proxy graphics or unknown DXF tags), `cad2ai` falls back to
  **convert-to-`ACAD2018` + tolerant re-read** (`backend = oda-convert+dxf`) instead of
  giving up, and keeps the intermediate DXF when you pass `--keep-dxf DIR`.
* The converter has no timeout of its own, so `ODA_TIMEOUT` (default 300 s) bounds it; a
  hung converter is killed and reported as `DwgConverterError` with `details.timeout_s`.
* Version floor: `ODA_IMPORT_MIN = AC1012` (R13). Newer-than-`AC1032` files are
  down-levelled — that is the newest DXF revision `ezdxf` can fully represent. Anything
  `ezdxf` cannot model survives as a **proxy entity** and is counted in
  `payload.stats.proxies`, so a review can say "N objects were not interpreted".
* A file that AutoCAD opens but the converter rejects is usually one of: eTransmit pack,
  password-protected drawing, or a non-Autodesk variant (BricsCAD/GstarCAD). Re-save from
  AutoCAD as DWG 2018 and retry.

---

## 2. Autodesk Platform Services app (fallback)

Only needed when the local converter is unavailable or you deliberately run
`--fallback aps` (e.g. a container with no Qt libs).

1. <https://platform.autodesk.com> → **Create app** → *Server-to-Server (2-legged) authentication*.
2. Enable **Data Management (OSS)** and **Model Derivative** APIs.
3. Copy the key/secret into `.env`:

```bash
APS_CLIENT_ID=...
APS_CLIENT_SECRET=...
APS_BUCKET_KEY=cad2ai-acme-01        # GLOBAL namespace: unique, lower-case, 3-128 chars
APS_POLICY_KEY=transient             # or temporary (24 h) / persistent (keep for reuse)
```

4. Verify:

```bash
python main.py doctor --check-aps --json | jq '.autodesk_fallback.health'
```

Notes:

* Buckets are created on demand (`ensure_bucket`) and reused; `transient` objects are
  garbage-collected by Autodesk after 30 days, `temporary` after 24 h. Use
  `--delete-after` on the `aps` command to remove the source object right away.
* Re-running the same unchanged file is cheap: `upload_file` compares the object's size via
  `objects/{key}/details` and **skips the upload** (the run reports `reused: true`).
* Translations are polled with backoff up to `APS_TRANSLATION_TIMEOUT` (900 s default).
  A `404` on the manifest usually means the URN expired rather than a bug.
* The output of this path is a **structural manifest**, not a DWG object graph. The payload
  records `source.lossless: false`, `source.provenance: "autodesk-platform-services"`, and
  warnings saying what is missing (no colours, no dimensions, no block definitions). Do not
  quote APS counts as entity counts in a deliverable.
* To reuse an existing translation instead of uploading again:
  `python main.py aps --status-only --urn <encoded-urn> --out out/urn-check`.

---

## 3. DeepSeek key and budget

```bash
DEEPSEEK_API_KEY=sk-...            # required
DEEPSEEK_MODEL=deepseek-flash      # deepseek-v4-pro for harder reasoning
DEEPSEEK_MAX_TOKENS=8000           # answer budget
DEEPSEEK_THINKING=disabled         # enabled = chain of thought, slower + pricier
CAD2AI_MAX_PAYLOAD_TOKENS=120000   # input budget (drives degradation)
```

Cost model per sheet, roughly: `prompt = system brief (~1.8k tokens) + payload`, and the
payload is capped at `CAD2AI_MAX_PAYLOAD_TOKENS`. To spend less:

* lower `CAD2AI_MAX_PAYLOAD_TOKENS` (the ladder aggregates text and dimension lists before
  it deletes anything, and `meta.truncations` tells the model the list is partial);
* analyse per sheet instead of per drawing (`payload.split_batches` is used by
  `complete_many` when you call the library API);
* keep `DEEPSEEK_THINKING=disabled` unless a sheet review genuinely needs the CoT pass.

DeepSeek-specific quirks this client already handles (do not re-add them):

* **429**: DeepSeek throttles *concurrency per key*; `Retry-After` is honoured and clamped
  by `DEEPSEEK_RETRY_MAX_DELAY`. Keep `--concurrency` (library) ≤ 2 per key for batch jobs.
* **Empty JSON content**: `response_format={"type":"json_object"}` occasionally returns an
  empty message. Retried `DEEPSEEK_EMPTY_CONTENT_RETRIES` times, then raised as
  `DeepSeekEmptyResponseError`.
* **`finish_reason == "length"`**: the answer is rejected outright
  (`DeepSeekTruncatedResponseError`) rather than repaired — a half object is worse than a
  retry with a bigger `DEEPSEEK_MAX_TOKENS`.
* **401 / 402** are never retried (a retry loop will not fix a key or a balance).
* `temperature` is ignored by the API while thinking is enabled; the client drops it so the
  request stays honest.

Reachability/auth check without spending meaningful tokens:

```bash
python main.py doctor --check-api --json | jq '.deepseek.health'
```

---

## 4. Running a sheet set

```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p out/logs
for dwg in drawings/*.dwg; do
  name=$(basename "$dwg" .dwg)
  python main.py analyze "$dwg" \
      --task sheet_review --out "out/$name" \
      --brief "Permit-issue set. Flag anything that blocks issue." \
      --json > "out/logs/$name.json" 2> "out/logs/$name.log" || {
        code=$?
        echo "$name exited $code: $(jq -r '.error.message' "out/logs/$name.json" 2>/dev/null || tail -1 "out/logs/$name.log")"
      }
done
```

Useful flags:

| flag | why |
| --- | --- |
| `--fallback none` | fail fast on bad input; never upload to Autodesk (data-residency or offline runs) |
| `--fallback aps` | force the cloud path even when the converter works |
| `--backend dxf` | skip the sentinel/converter logic entirely |
| `--no-audit` | skip `doc.audit()` on trusted files (a few % faster on big drawings) |
| `--raw-manifest` | keep the untouched APS manifest next to the payload |
| `--dry-run` | produce the payload only (no key, no cost) |
| `--include-handles` | add DXF handles for tracing a finding back to the entity |
| `--env-file prod.env` | per-project configuration without touching the shell |

Exit codes are stable, so a wrapper can branch:
`2` config, `3` unsupported DWG version, `4` parse/input, `5` Autodesk, `6` DeepSeek,
`1` unexpected. Retry only `5`/`6` (and `1` once, after reading the log).

---

## 5. Interpreting the artifacts

```
out/<name>/
├── cad_model.json     # what we read        (Phase 2, pretty)
├── payload.json       # what the model read  (minified, exactly the bytes sent)
├── analysis.json      # what the model said  (schema-validated)
├── analysis.md        # the same, for humans
├── ai_meta.json       # model, attempts, usage, finish_reason, repair notes
└── run_manifest.json  # timings, backend, warnings, error, masked config
```

Reading order when an answer looks wrong:

1. `run_manifest.json` → `mode` (which backend produced this) and `warnings`.
2. `payload.json` → `meta.degraded`, `meta.truncations`, `meta.counts`. If the model
   claimed "there are 12 doors" and `counts.blocks` is 12, that is a real count; if
   `truncations.blocks` is non-zero the list was capped and the model was told so.
3. `document.units` / `source.lossless` — a dimension without units is not a length.
4. `ai_meta.json` → `attempts > 1` means the API was flaky; `repair_notes` shows the JSON
   was repaired (fences/trailing commas), which is fine but worth knowing.
5. Only then blame the model: every finding carries `evidence` as `json.path=value`, so
   grep `payload.json` for that path.

`tokenizer_calibration` in `run_manifest.json` is the ratio actual/estimated prompt tokens.
If it drifts far from 1.0 across runs, tighten `CAD2AI_MAX_PAYLOAD_TOKENS` accordingly.

---

## 6. Troubleshooting

| symptom | cause | action |
| --- | --- | --- |
| `requires the ODA File Converter, which was not found` | converter missing from `PATH` | install it or set `ODA_EXECUTABLE`; or work from `.dxf`; or `--fallback aps` |
| `predates the AC1012 (R13) minimum` | pre-R13 DWG | open in any 2013+ product and SAVE AS DWG 2018; `CAD2AI_ALLOW_LEGACY_VERSIONS=1` to try anyway |
| `DWG header is missing or not a recognised AutoCAD DWG signature` | DXF renamed to `.dwg`, or an eTransmit pack | pass the real file; unpack eTransmit; `.dxf` works directly |
| `not a DXF file: found ASCII text` | an ASCII `.dwg`-looking export or a text diff | re-export from CAD |
| converter killed after N seconds (`details.timeout_s`) | huge/complex drawing, cold AppImage, missing fonts dialog | raise `ODA_TIMEOUT`; install the SHX font pack so the converter does not prompt |
| `audit: N errors` warnings | file-level DXF damage | keep the payload, note the warnings, and re-export if errors exceed a few hundred |
| `APS authentication/authorisation failed (401)` | clock skew or expired token | re-run (tokens are refreshed automatically); check `date`, app key, and that both APIs are enabled |
| `the app is missing an OAuth scope` | `APS_SCOPES` too narrow | add `data:read data:write data:create bucket:create bucket:read` |
| `APS translation failed: …` (from the manifest messages) | the drawing is corrupt or password protected | open it in AutoCAD/trueView, repair, re-save |
| `APS translation did not finish within 900s` | big sheet set | raise `APS_TRANSLATION_TIMEOUT`; translate once and reuse the URN via `--status-only` |
| `no such url` / 404 on the manifest | transient bucket, object GC'd | re-upload; use `persistent` policy for long-lived reuse |
| `DeepSeek rate limit reached (HTTP 429)` after N attempts | key concurrency cap | lower batch concurrency, raise `DEEPSEEK_MAX_ATTEMPTS`, add `DEEPSEEK_MIN_INTERVAL_MS` |
| `DeepSeek rejected the API key (HTTP 401)` | wrong/revoked key, or `DEEPSEEK_BASE_URL` pointing elsewhere | fix `.env`; the base URL must be `https://api.deepseek.com` |
| `insufficient balance (HTTP 402)` | billing | top up; not retried on purpose |
| `The model ... does not exist` (400) | model id renamed or unavailable | `DEEPSEEK_MODEL=deepseek-flash`; `doctor` lists known ids |
| `DeepSeek response was truncated by max_tokens` | answer budget too small | raise `DEEPSEEK_MAX_TOKENS`, or ask for fewer findings (smaller `--max-*` caps) |
| `could not parse JSON from the model reply` | model answered in prose | keep `DEEPSEEK_JSON_MODE=1`; if your gateway rejects it, `--no-json-mode` + `--show-markdown` |
| payload "still exceeds the budget after degradation" | sheet is genuinely enormous | split per layout/sheet, or raise the budget; `meta.budget_exceeded_by` says by how much |
| discipline looks wrong | generic layer naming | check `discipline.candidates` and `layer_scores`; fix layer naming upstream — the classifier is deliberately conservative and returns `undetermined` rather than guessing |

When a run fails, `run_manifest.json` is still written (with `error`), and `payload.json`
survives if Phase 2 succeeded — so you can iterate on Phase 3 alone:

```bash
python main.py prompt samples/demo.dxf --task bom > prompt.txt   # inspect the exact prompt
```

---

## 7. CI and containers

```Dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends xvfb fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Drop the ODA AppImage into the image and point at it, or rely on --fallback aps.
ENV ODA_EXECUTABLE=/opt/oda/ODAFileConverter.AppImage
CMD ["python", "main.py", "doctor"]
```

CI notes:

* The test suite is fully offline (scripted ODA/APS/OpenAI fakes): `python -m pytest` in ~6 s (268 tests).
* Keep secrets out of artifacts: `run_manifest.json` is written from `Settings.to_safe_dict()`
  (values masked); artefacts are git-ignored under `out/`.
* Add a smoke step that needs no key:
  `python scripts/gen_sample_dxf.py samples/demo.dxf && python main.py analyze samples/demo.dxf --dry-run --out out/smoke`

---

## 8. Upgrades and drift

| dependency | pin | drift risk |
| --- | --- | --- |
| `ezdxf` | `>=1.1,<2` | new DXF versions/entity classes; `odafc` target-version names |
| `openai` | `>=1.40` | the SDK's exception names (`_classify` guards `isinstance` checks and falls back to status codes) |
| DeepSeek API | — | **model ids get renamed** (the code warns but never hard-fails); JSON-mode empty content; thinking-mode parameter placement (`extra_body.thinking`) |
| APS | — | API versions are pinned in URLs (`v2`); Model Derivative accepts `svf2`/`svf` only — that is validated locally before any upload |

If DeepSeek renames models again, only `DEEPSEEK_MODEL` (and the advisory `KNOWN_MODELS`
list in `cad2ai/config.py`) need to change.

---

## 9. Data handling

* Drawings are read locally; nothing leaves the machine unless the APS fallback is used
  (`--fallback none` disables it completely, and it is also disabled when APS credentials
  are absent).
* In the Autodesk path the source `.dwg` is uploaded to **your** bucket (`transient` by
  default) and deleted on request (`--delete-after`); the payload sent to DeepSeek is
  derived JSON, and by default contains **no** DXF handles, no directory paths (only the
  file name) and no raw text longer than 160 characters per item (`--include-handles` opt-in).
* Title blocks are text: if your sheet set embeds client names, addresses or consultant
  contacts, that text goes to DeepSeek. Lower `CAD2AI_MAX_TEXT_ITEMS`, or run Phase 2 only
  (`extract`) and redact `payload.json` before Phase 3.
* Artifacts may contain drawing metadata worth treating as confidential: keep `out/` on
  managed storage and never commit it (already in `.gitignore`).
