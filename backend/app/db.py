"""Optional persistence to Supabase (PostgreSQL) via plain psycopg.

The database stores compliance reports and CAD metadata for audit purposes.
Persistence is deliberately optional: when DATABASE_URL is not configured the
pipeline still completes end-to-end and simply reports
`persisted_to_database=false`.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("cad-compliance.db")

try:
    import psycopg
except ImportError:  # pragma: no cover - driver optional at import time
    psycopg = None  # type: ignore[assignment]

_SCHEMA = """
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
"""


def is_available() -> bool:
    return psycopg is not None


def ensure_schema(database_url: str | None) -> None:
    """Create the compliance_reports table if it does not exist yet."""
    if not database_url or psycopg is None:
        return
    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
        logger.info("compliance_reports table is ready")
    except Exception as exc:  # never block the pipeline on DB issues
        logger.warning("Could not ensure DB schema (persistence disabled): %s", exc)


def save_report(database_url: str | None, report: dict) -> bool:
    """Insert one ComplianceReport dict. Returns True when persisted."""
    if not database_url:
        logger.debug("DATABASE_URL not set — skipping persistence")
        return False
    if psycopg is None:
        logger.warning("psycopg not installed — skipping persistence")
        return False

    verification = report["verification"]
    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO compliance_reports (
                        id, source_file, verdict, min_distance_m,
                        required_distance_m, drawing_units, ai_mapping,
                        verification, cad_metadata, report_markdown
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        report["report_id"],
                        report["source_file"],
                        report["verdict"],
                        verification["min_distance_m"],
                        verification["required_distance_m"],
                        verification.get("drawing_units"),
                        json.dumps(report["mapping"]),
                        json.dumps(verification),
                        json.dumps(report.get("cad_metadata", {})),
                        report["report_markdown"],
                    ),
                )
        return True
    except Exception as exc:
        logger.warning("Report persistence failed (pipeline result unaffected): %s", exc)
        return False
