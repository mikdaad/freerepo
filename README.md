# Hybrid CAD Compliance System

A municipal **building-code compliance verifier** that checks setback rules (e.g. *"the
building perimeter must be at least **1.5 m** from the boundary wall"*) directly from
raw **`.dwg`** files.

**Core architectural principle:** Large Language Models hallucinate exact spatial
mathematics, so this system strictly separates concerns:

| Concern | Owner | Technology |
| --- | --- | --- |
| Geometry parsing (exact coordinates) | **Deterministic** | C# (.NET 8) + ACadSharp |
| "Which lines are the building / the boundary?" | **Semantic AI** | DeepSeek (via `openai` SDK) |
| Distance measurement & PASS/FAIL verdict | **Deterministic** | Python + Shapely |
| Formal report prose | **Semantic AI** | DeepSeek (numbers fed to it verbatim) |

The AI never measures anything. The LLM never decides PASS/FAIL.

---

## Repository structure

```
freerepo/
├── cad-engine/                    # Phase 1 — C# deterministic geometry engine
│   └── CadEngine/
│       ├── CadEngine.csproj       #   .NET 8 console app, ACadSharp NuGet
│       ├── Program.cs             #   CLI: cad-engine <input.dwg> <output.json>
│       ├── Models/ExportModels.cs #   cad_geometry.json data contract
│       └── Extraction/GeometryExtractor.cs  # Line/LwPolyline/Insert extraction
│
├── backend/                       # Orchestration backend (FastAPI)
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── main.py                #   FastAPI app + 4-phase SSE orchestration
│       ├── config.py              #   pydantic-settings configuration
│       ├── schemas.py             #   data contracts (pydantic)
│       ├── db.py                  #   optional Supabase/PostgreSQL persistence
│       └── pipeline/
│           ├── cad_extractor.py   # Phase 1: invokes the C# engine
│           ├── semantic.py        # Phase 2: DeepSeek semantic mapping
│           ├── geometry.py        # Phase 3: Shapely minimum-distance math
│           └── reporting.py       # Phase 4: DeepSeek report drafting
│
├── frontend/                      # Next.js (App Router) dashboard
│   ├── app/page.tsx               #   upload + live pipeline tracker + report view
│   ├── components/                #   pipeline-tracker, compliance-result, shadcn/ui
│   └── lib/api.ts                 #   SSE streaming client
│
└── samples/
    └── cad_geometry.example.json  # demo geometry (fails the 1.5 m rule by design)
```

## The 4-step hybrid pipeline

```
 ┌─────────────┐   ┌───────────────────┐   ┌──────────────────┐   ┌──────────────────┐
 │ 1 EXTRACT   │   │ 2 IDENTIFY        │   │ 3 VERIFY         │   │ 4 REPORT         │
 │ C#/ACadSharp│──▶│ DeepSeek          │──▶│ Python/Shapely   │──▶│ DeepSeek         │
 │ .dwg →      │   │ ids → building /  │   │ exact min dist   │   │ figures → formal │
 │ cad_geometry│   │ boundary ids      │   │ vs 1.5 m rule    │   │ markdown report  │
 │ .json       │   │ (no math!)        │   │ → PASS/FAIL      │   │ (no new math!)   │
 └─────────────┘   └───────────────────┘   └──────────────────┘   └──────────────────┘
```

1. **Deterministic Extraction** — the C# engine loads the DWG with
   `DwgReader.Read(stream)`, iterates `doc.Entities` (Line, LwPolyline, Insert),
   and serializes exact `StartPoint`/`EndPoint`/`Vertices`, layer names and block
   attributes into a **minified `cad_geometry.json`**.
2. **Semantic Identification** — FastAPI feeds that JSON to **DeepSeek**, whose only
   job is returning `{"building_lines": [...], "boundary_lines": [...], "rationale": ...}`
   using stable DWG handle ids. Output is clamped to ids that actually exist.
3. **Mathematical Verification** — Shapely builds the geometries, computes the exact
   minimum distance (with unit conversion from the DWG `INSUNITS` header), and
   produces the **PASS/FAIL verdict deterministically**.
4. **Compliance Reporting** — the exact figures (e.g. *"Calculated distance: 1.42 m,
   Required: 1.5 m"*) go back into DeepSeek to draft the formal municipality report.
   The model is forbidden from altering any number.

Progress is streamed to the dashboard as **Server-Sent Events**; the UI shows the
4-phase loading state and a big PASS/FAIL badge sourced from the deterministic step.

---

## Prerequisites

| Component | Requirement |
| --- | --- |
| CAD engine | [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0) |
| Backend | Python 3.11+ |
| Frontend | Node.js 20+ |
| AI | A [DeepSeek API key](https://platform.deepseek.com) (optional for dev — see mock mode) |
| Database | A [Supabase](https://supabase.com) project (optional) |

## 1. C# CAD engine (`cad-engine/`)

```bash
cd cad-engine/CadEngine

# restore the ACadSharp NuGet package and build
dotnet restore
dotnet build -c Release

# manual test (produces cad_geometry.json next to the input)
dotnet run -- /path/to/site_plan.dwg ./cad_geometry.json

# recommended for production: publish a fast-start binary
dotnet publish -c Release -r linux-x64 --self-contained false
# → bin/Release/net8.0/linux-x64/publish/cad-engine
```

## 2. Orchestration backend (`backend/`)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit: DEEPSEEK_API_KEY, DATABASE_URL, ...

# development server on http://localhost:8000
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Key environment variables (see `backend/.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | — | DeepSeek key (empty ⇒ automatic mock mode) |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek model |
| `MOCK_AI` | `false` | Force deterministic AI stubs for offline dev |
| `MIN_SETBACK_METERS` | `1.5` | The municipal rule enforced in Phase 3 |
| `CAD_ENGINE_BIN` | — | Path to the published `cad-engine` binary |
| `CAD_ENGINE_TIMEOUT_S` | `300` | Subprocess timeout for Phase 1 |
| `DATABASE_URL` | — | Supabase/PostgreSQL connection string |
| `CORS_ORIGINS` | localhost:3000 | Allowed browser origins |

### Supabase setup (optional)

1. Create a project at [supabase.com](https://supabase.com).
2. Copy the connection string (**Project Settings → Database**, port `5432`,
   session mode) into `DATABASE_URL`.
3. Done — the backend creates the `compliance_reports` table automatically on
   startup. Equivalent SQL:

```sql
CREATE TABLE IF NOT EXISTS compliance_reports (
    id                   text PRIMARY KEY,
    created_at           timestamptz NOT NULL DEFAULT now(),
    source_file          text NOT NULL,
    verdict              text NOT NULL CHECK (verdict IN ('PASS', 'FAIL')),
    min_distance_m       double precision NOT NULL,
    required_distance_m  double precision NOT NULL,
    drawing_units        text,
    ai_mapping           jsonb NOT NULL,
    verification         jsonb NOT NULL,
    cad_metadata         jsonb,
    report_markdown      text NOT NULL
);
```

## 3. Frontend dashboard (`frontend/`)

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

The browser calls **relative URLs** (`/backend/...`), which Next.js rewrites to the
FastAPI backend (`BACKEND_URL`, default `http://localhost:8000`) — no CORS needed.
Open <http://localhost:3000>, upload a `.dwg`, and watch the 4-phase pipeline
execute live; or click **"Run bundled sample"** to see the full flow without a DWG
or .NET toolchain (the sample intentionally **fails** the 1.5 m rule at 1.42 m).

## Trying it without a DWG file

```bash
# phases 2–4 against the bundled sample geometry:
curl -N -X POST http://localhost:8000/api/pipeline/run-sample

# or bring your own pre-extracted cad_geometry.json:
curl -N -X POST http://localhost:8000/api/pipeline/run-json \
     -F "file=@samples/cad_geometry.example.json;type=application/json"
```

## API overview

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Health + config summary |
| `GET` | `/api/pipeline/phases` | Phase metadata + active rule |
| `GET` | `/api/sample-geometry` | Bundled `cad_geometry.json` sample |
| `POST` | `/api/pipeline/run` | Full 4-phase pipeline for an uploaded `.dwg`/`.dxf` |
| `POST` | `/api/pipeline/run-json` | Phases 2–4 from a `cad_geometry.json` upload |
| `POST` | `/api/pipeline/run-sample` | Phases 2–4 on the bundled sample |

All `run*` endpoints stream SSE: `pipeline_start` → `phase` (running/complete/failed)
→ `result` (full report) or `error`.

## Known limitations (scaffold stage)

- LwPolyline **bulge (arc) segments are treated as chords** — fine for setback
  checks on typical plans, exact arc support is a roadmap item.
- Only **model-space** entities are extracted (layouts/paper space ignored).
- `Insert` geometry is represented by its insertion point; exploding block
  geometry is on the roadmap.
- A single rule (minimum setback) is enforced; a rule engine for heights,
  coverage ratios, etc. is the natural next step.
