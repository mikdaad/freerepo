#!/usr/bin/env python3
"""A deliberately small OpenAI-compatible stub, for development only.

It answers ``POST /chat/completions`` with a fixed ``sheet_review`` analysis, so the
whole stack — FastAPI service, pipeline phases 1-3, dashboard — can be exercised,
demoed and screenshot without ``DEEPSEEK_API_KEY`` or any network egress::

    python scripts/dev_stub_deepseek.py            # listens on 127.0.0.1:8123
    DEEPSEEK_API_KEY=sk-stub-not-a-real-key DEEPSEEK_BASE_URL=http://127.0.0.1:8123 \\
        uvicorn server:app --host 0.0.0.0 --port 8000

The reply is canned: it does not read your drawing. It only borrows the file name
from the payload it was sent so the dashboard header looks plausible. Do not point
production traffic at this; it has no auth, no TLS and no rate limit.

Environment:
    ``STUB_PORT``      default 8123
    ``STUB_DELAY_S``   sleep before answering (use ~40 to watch the progress panel)
"""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = os.environ.get("STUB_MODEL", "deepseek-flash")
DELAY = float(os.environ.get("STUB_DELAY_S", "0"))


def analysis_for(drawing: str) -> dict[str, object]:
    """A plausible sheet review of an architectural plan."""
    return {
        "drawing": drawing,
        "discipline": {
            "assigned": "architectural",
            "confirmed": False,
            "comment": (
                "Layer prefixes are architectural (A-/S-) with 3/32 annotation sizing, but the mechanical "
                "overlay carries real geometry; confirm this is not a mixed trade sheet before judging "
                "annotation standards."
            ),
        },
        "confidence": 0.78,
        "findings": [
            {
                "id": "F1",
                "bucket": "missing_information",
                "severity": "high",
                "title": "Door fire ratings are not filled on every reference",
                "detail": (
                    "DOOR_STD declares a FIRE_RATING attribute, yet part of its reference set leaves it empty, so a "
                    "door schedule cannot be produced from this sheet and fire-separation intent cannot be verified."
                ),
                "evidence": [
                    "blocks.items[0].name=DOOR_STD",
                    "blocks.items[0].attribute_fill.FIRE_RATING=0.75",
                    "text_stats.attribs is non-zero so ATTRIBs are being read",
                ],
                "recommendation": (
                    "Populate FIRE_RATING on every door from the schedule, then re-run with --include-handles so the "
                    "next review can name the specific INSERT entities."
                ),
            },
            {
                "id": "F2",
                "bucket": "data_quality",
                "severity": "high",
                "title": "Typed dimension text hides the measured value",
                "detail": (
                    "Dimensions carrying overridden text look complete while their measurement is unverifiable; at "
                    "least one disagrees with the value the geometry implies."
                ),
                "evidence": ["dimensions[].flags includes text_override", "dimensions[].text is not '<>'"],
                "recommendation": "Strip the overrides and re-measure; express true typicals with a note, not dimension text.",
            },
            {
                "id": "F3",
                "bucket": "standards_issues",
                "severity": "medium",
                "title": "A layer references an undefined linetype",
                "detail": (
                    "The extraction reports a layer linetype missing from the LTYPE table. Plotters silently fall back "
                    "to CONTINUOUS, so hidden linework prints as visible geometry."
                ),
                "evidence": ["layer_stats.linetypes_undefined contains HIDDEN"],
                "recommendation": "Load the office linetype file, redefine it, and add it to the template so it cannot drift.",
            },
            {
                "id": "F4",
                "bucket": "complexity",
                "severity": "low",
                "title": "Template baggage inflates every count",
                "detail": (
                    "Empty layouts, unused layers and an unreferenced block definition are present. Nothing plots, but "
                    "the layer manager, the file size and any downstream quantity are misleading."
                ),
                "evidence": ["layers[].entities=0 entries exist", "block_stats reports unreferenced definitions", "layouts includes empties"],
                "recommendation": "PURGE (including zero-object layers and empty layouts), then AUDIT before issue.",
            },
            {
                "id": "F5",
                "bucket": "missing_information",
                "severity": "medium",
                "title": "No plotted-scale annotation captured on the sheet",
                "detail": "Units are declared, but no scale text was found on the paper-space layout, so the print scale cannot be cross-checked against measured lengths.",
                "evidence": ["document.units is present", "layouts[].text is empty for the sheet layout"],
                "recommendation": "Drive a SCALE attribute from the viewport and put it in the title block.",
            },
        ],
        "layer_findings": [
            {"layer": "A-DEAD", "issue": "Frozen layer with 0 entities — template carry-over", "evidence": "layers[?].entities=0 · frozen=true"},
            {"layer": "S-COLS", "issue": "Locked layer references an undefined linetype", "evidence": "layers[?].linetype=HIDDEN · layer_stats.linetypes_undefined"},
            {"layer": "P-EQ", "issue": "Layer is OFF but carries annotations that will not plot", "evidence": "layers[?].on=false · layers[?].dimensions>0"},
            {"layer": "X-TEMPLATE-UNUSED", "issue": "No geometry and no annotations; purge candidate", "evidence": "layers[?].entities=0"},
        ],
        "dimension_findings": [
            {"kind": "text_override", "count": 1, "issue": "Dimension text typed over the measured value", "evidence": "dimensions[].flags=text_override"},
            {"kind": "dimstyle_variety", "count": 2, "issue": "More than one dimension style on one sheet", "evidence": "dimensions[].dimstyle ∈ {ARCH-3-32, MECH-ISO}"},
            {"kind": "unmeasured", "count": 0, "issue": "No non-measured dimensions detected", "evidence": "dimension_stats"},
        ],
        "checks_not_possible_from_data": [
            "Overlapping or double-drawn linework (needs geometry, not counts)",
            "Plot style table (CTB/STB) colour-to-weight mapping",
            "Title block legibility at the plotted paper size",
            "Coordination with the linked model (xref freshness is not exposed)",
        ],
        "data_gaps": [
            "Handles may be excluded from the payload, so findings cannot name exact entities",
            "Text and dimension lists are capped and may be aggregated; counts are authoritative, lists are not",
        ],
        "release_recommendation": "hold",
        "effort_hours_estimate": 6,
    }


def drawing_name_from(messages: list[dict[str, object]]) -> str:
    """Borrow the file name from the payload so the UI looks coherent."""
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue
        match = re.search(r'"name"\s*:\s*"([^"]+\.(?:dwg|dxf))"', content, re.IGNORECASE)
        if match:
            return str(match.group(1))
        match = re.search(r"([A-Za-z0-9._ -]+\.(?:dwg|dxf))", content)
        if match:
            return str(match.group(1))
    return "STUB-SHEET.dxf"


class Handler(BaseHTTPRequestHandler):
    server_version = "cad2ai-stub/1.0"

    def _send(self, payload: dict[str, object], code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "authorization,content-type")
        self.send_header("access-control-allow-methods", "POST,GET,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/models"):
            self._send({"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "stub"}]})
        else:
            self._send({"ok": True, "service": "cad2ai dev stub", "model": MODEL, "usage": "development only"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send({"error": {"message": "stub: body was not JSON", "type": "invalid_request"}}, 400)
            return
        if DELAY:
            time.sleep(DELAY)
        messages = request.get("messages") or []
        if isinstance(messages, list):
            typed = [entry for entry in messages if isinstance(entry, dict)]
        else:  # pragma: no cover - defensive
            typed = []
        content = json.dumps(analysis_for(drawing_name_from(typed)), ensure_ascii=False, separators=(",", ":"))
        prompt_tokens = max(256, sum(len(str(entry.get("content", ""))) for entry in typed) // 4)
        completion_tokens = len(content) // 4
        self._send(
            {
                "id": f"chatcmpl-stub-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.get("model") or MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
        )

    def log_message(self, fmt: str, *args: object) -> None:  # quieter, single-line
        print(f"[stub] {self.command} {self.path} · {fmt % args}", flush=True)


def main() -> int:
    port = int(os.environ.get("STUB_PORT", "8123"))
    host = os.environ.get("STUB_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(
        f"[stub] listening on http://{host}:{port} (model={MODEL}, delay={DELAY}s) — development only, no auth",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
