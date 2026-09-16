import fs from "node:fs";
import path from "node:path";

/**
 * Where the dashboard reads `analysis.json` from, in priority order:
 *
 * 1. `ANALYSIS_JSON=/abs/path/analysis.json` (env var — the CI / kiosk hook)
 * 2. `web/data/analysis.json` (a copy checked next to the app, if you want a fixed demo)
 * 3. the newest `out/<run>/analysis.json` produced by `python main.py analyze`
 *
 * Returns `null` when nothing is available, and the caller falls back to the
 * bundled sample. Every failure is reported in `notes` rather than thrown: a
 * broken artifact on disk must still render a dashboard, with the reason visible.
 */
export interface AnalysisSource {
  raw: unknown | null;
  label: string;
  origin: "file" | "none";
  notes: string[];
}

function readJson(file: string, notes: string[]): unknown | null {
  try {
    const text = fs.readFileSync(file, "utf8");
    if (!text.trim()) {
      notes.push(`${path.basename(file)} is empty`);
      return null;
    }
    return JSON.parse(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    notes.push(`${path.basename(file)} could not be parsed: ${message.split("\n")[0]}`);
    return null;
  }
}

/** Newest `out/<run>/analysis.json` under the repository root. */
function newestArtifact(root: string): string | null {
  const outDir = path.join(root, "out");
  if (!fs.existsSync(outDir)) return null;
  const candidates: { file: string; mtimeMs: number }[] = [];
  const walk = (dir: string, depth: number) => {
    if (depth > 3) return;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full, depth + 1);
      } else if (entry.isFile() && entry.name === "analysis.json") {
        try {
          candidates.push({ file: full, mtimeMs: fs.statSync(full).mtimeMs });
        } catch {
          /* ignore unreadable file */
        }
      }
    }
  };
  walk(outDir, 0);
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return candidates[0]!.file;
}

export function loadAnalysisSource(cwd: string = process.cwd()): AnalysisSource {
  const notes: string[] = [];
  const repoRoot = path.resolve(cwd, "..");

  const fromEnv = process.env.ANALYSIS_JSON?.trim();
  if (fromEnv) {
    const file = path.resolve(cwd, fromEnv);
    if (fs.existsSync(file)) {
      const raw = readJson(file, notes);
      if (raw !== null) return { raw, label: file, origin: "file", notes };
    } else {
      notes.push(`ANALYSIS_JSON points at a missing file: ${file}`);
    }
  }

  const local = path.join(cwd, "data", "analysis.json");
  if (fs.existsSync(local)) {
    const raw = readJson(local, notes);
    if (raw !== null) return { raw, label: local, origin: "file", notes };
  }

  const artifact = newestArtifact(repoRoot);
  if (artifact) {
    const raw = readJson(artifact, notes);
    if (raw !== null) return { raw, label: artifact, origin: "file", notes };
  }

  return { raw: null, label: "bundled sample", origin: "none", notes };
}
