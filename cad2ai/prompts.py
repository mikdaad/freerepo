"""Phase 3a -- prompt construction (how to read the payload, what to output).

The system prompt is the difference between "an LLM guessed about my drawing"
and "an LLM read the extracted data".  It therefore does three jobs:

1. **Schema briefing** -- it explains every payload section, the ACI colour
   numbering, the layer-state flags, what a dimension ``value`` means (and its
   unit), and how block ``refs``/``leverage`` are computed.
2. **Grounding rules** -- claims must cite a JSON path, unknowns must be
   reported as gaps, and anything marked ``degraded``/``truncated`` must not be
   extrapolated into totals.
3. **Output contract** -- a hard JSON schema per task, so the answer can be
   piped straight into a spreadsheet, ticket system or QC gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = ["TASKS", "TaskSpec", "build_messages", "build_system_prompt", "resolve_task"]

#: ACI colour numbers -> name (AutoCAD's standard colour index table).
ACI_COLORS: dict[int, str] = {
    1: "red",
    2: "yellow",
    3: "green",
    4: "cyan",
    5: "blue",
    6: "magenta",
    7: "white/black (depends on background)",
    9: "light red",
    30: "orange",
    40: "light green",
    90: "light gray",
    140: "dark gray",
    210: "purple",
    250: "gray",
}

SCHEMA_BRIEF = """PAYLOAD STRUCTURE (JSON, one line, keys are described here once):
- source: file name, size, sha256, parser backend. "lossless": true means the full
  DWG object graph was read locally; false means only structural metadata from the
  Autodesk Model Derivative service is present (no entity colours/geometry).
- document.units.insunits / document.units.name: drawing units ($INSUNITS), e.g. 4 =
  millimeters. EVERY bare number in the payload is in these units unless stated.
- document.extents: model-space bounding box {min,max,size,area} in drawing units.
- document.header: selected header vars ($LUNITS, $LUPREC, $LTSCALE, $PSLTSCALE,
  $DIMASSOC, ...). $MEASUREMENT=1 means metric templates.
- document.tables: table entry counts (layers, linetypes, text styles, dimstyles,
  blocks, views, ...). A large template table with few used entries means an
  over-stuffed template, not drawing content.
- layers[]: {name, color (ACI index -- see colour table below), color_hex, linetype,
  lineweight (1/100 mm), state ("off,frozen,locked,donotplot"), entities,
  annotations, text, dimensions, xrefs, proxy}. "entities" is the count of layout
  entities assigned to that layer: it tells you what the drawing is actually made of.
- layer_stats: {count, off, frozen, locked, not_plotted, empty, used,
  with_dimensions, annotation_ratio, referenced_but_undefined[], top_by_entities[]}.
  "referenced_but_undefined" = entities on layers missing from the layer table
  (a real defect: orphaned layer references plot unpredictably).
- entities: {total, by_type{DXFTYPE: count}, distinct_types, geometry, annotations,
  representations, text_entities, dimensions, inserts, three_d, layout_breakdown}.
- layouts[]: per paper-space/model-space layout {name, entities, modelspace,
  paper_height, scale, types{}}. Multiple layouts = plotting sheets.
- blocks.items[]: {name, refs (INSERT count), entities (size of the definition),
  attributes (ATTDEF tag names), types{}, leverage (= refs * entities), external
  (XREF), anonymous, base}. Anonymous names start with "*" and include dimension
  geometry blocks (rendered dimensions) -- do not report those as reusable parts.
- blocks.stats: {definitions, used, unused, repeated, anonymous, external,
  with_attributes, insert_entities, distinct_insert_names, missing_definitions[],
  reusable[]}.
- text[]: {layer, type (text|mtext|attrib), tag (ATTRIB tag name, e.g. FIRE_RATING),
  text (whitespace collapsed, may end with an ellipsis when clipped), at [x,y],
  h (text height in drawing units), rot}. ATTRIB entries are block attribute VALUES
  (schedule data); use tag+text pairs as the primary source for takeoffs.}
- text_stats / dimension_stats / proxies: totals, how many items were included, and
  whether the lists were capped ("truncated": true).
- dimensions[]: {layer, kind (linear|aligned|angular_2line|angular_3point|diameter|
  radius|center|ordinate|arc_length|large_radius), value (measured length/angle in
  document units; angles are in the drawing's angular unit), unit, text (an explicit
  text override -- "<>" placeholder means "use measurement" and is omitted), style
  (dimstyle name), flags[] (text_override|text_user_positioned|ordinate_x|unmeasured)}.
- dimension_styles[]: {name, text_height, decimal_places, linear_factor (dimlfac),
  rounding, scale, zero_suppression}. A linear_factor other than 1 means the printed
  dimension text does NOT equal "value": report measured and nominal separately.
- linetypes[] / text_styles[]: table entries (dash segment counts, font files).
- discipline: heuristic guess at the engineering discipline from layer names,
  linetypes and 3D content, with {primary, confidence, candidates[], signals[]}.
  Treat it as a hypothesis to confirm or reject from the layer/text evidence.
- warnings[]: parser/audit findings (recovered structure, legacy versions, proxy
  objects). Reflect them in "data_gaps".
- meta: {token_estimate, token_budget, degraded[], truncations{}}. When
  "degraded" is non-empty, the lists you see are SAMPLES of a larger set: use the
  *_stats sections for totals and never multiply sample counts.

STANDARD COLOUR NUMBERS (ACI): 1 red, 2 yellow, 3 green, 4 cyan, 5 blue, 6 magenta,
7 white/black, 8 dark gray, 9 light red, 250 gray. Colours encode meaning in most
office standards (e.g. red = revision clouds, magenta = MEP) -- mention it when it
matters, never assert an office standard you were not given."""

GROUNDING_RULES = """RULES (mandatory):
1. Ground every claim in the payload. Cite the JSON path in "evidence"
   (e.g. "layers[3].entities", "blocks.items[name=BOLT-M12].refs", "dimensions[12].value").
   If you cannot cite it, do not say it.
2. Never invent quantities. If a needed number is not present and cannot be derived,
   return null for that field and list the missing input in "data_gaps".
3. Respect units and precision. Quote measurements with the unit from
   document.units.name and the dimension style's decimal_places; convert only if the
   task explicitly asks, and show the conversion.
4. Distinguish geometry from annotation: geometry = lines/polylines/hatches/solids;
   annotation = text/dimensions/leaders/mleaders. A drawing that is mostly annotation is a
   sheet, not a model.
5. Distinguish the template from the content: unused blocks, empty layers and unused
   linetypes/styles are template baggage -- report them as cleanup findings, not as
   drawing scope.
6. State confidence and verification steps for anything that needs the drawing itself
   (visual checks, clashes, tolerances, real-world compliance).
7. If "source.lossless" is false, prefix conclusions with what the metadata cannot
   support (colours, linetypes, dimension values, block attributes) and recommend the
   local odafc parse path.
8. Be terse and quantitative: short sentences, numbers, no marketing language, no
   restating the payload back to the user.
9. Output ONLY one JSON object, no prose outside it, no markdown fences, no comments,
   no trailing commas. Keys exactly as in OUTPUT SCHEMA; use [] / {} / null for empty.
10. Language: reply in the language of the user's brief (default: English)."""


@dataclass(frozen=True)
class TaskSpec:
    """One analysis job: what to ask for and the exact JSON shape to return."""

    key: str
    title: str
    instructions: str
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    #: payload sections the model should focus on (mentioned to save reading effort)
    focus: tuple[str, ...] = ()

    def schema_text(self) -> str:
        return json.dumps(self.output_schema, separators=(",", ":"), ensure_ascii=False)

    def render_instructions(self) -> str:
        return (
            f"TASK: {self.title}\n{self.instructions.strip()}\n"
            f"FOCUS SECTIONS: {', '.join(self.focus) if self.focus else 'all'}\n"
            f"OUTPUT SCHEMA (obey exactly):\n{self.schema_text()}"
        )


_COMMON_HEAD = {
    "drawing": "string|null -- sheet/drawing identifier read from the payload (title text or file name)",
    "discipline": {
        "assigned": "string|null -- value of discipline.primary from the payload",
        "confirmed": "boolean",
        "comment": "string|null",
    },
    "confidence": "number 0..1",
}

TASKS: dict[str, TaskSpec] = {
    "sheet_review": TaskSpec(
        key="sheet_review",
        title="Drawing sheet QA review",
        instructions="""Act as a senior CAD manager reviewing this sheet for release.
Find concrete, actionable defects in four buckets and rank them by severity
("high" = will cause rework or a field error, "medium" = standards violation or
ambiguity, "low" = hygiene):
- missing_information: absent title/revision/scale/legend/grid data, sheets with no
  annotation, dimensions on layers that are off/frozen, un-plotted layers holding content
- standards_issues: layer names that break the visible naming convention, orphaned layer
  references, text height/font inconsistencies (compare text.h against document and
  text_styles), linetype misuse, dimstyles whose dimlfac/scale makes printed text differ
  from measured values
- data_quality: zero-length or duplicate-ish geometry signals (very high entity counts with
  few distinct types), proxy/unknown objects, anonymous blocks dominating content,
  huge unused template tables
- complexity: a two-sentence profile with the numbers that drive review effort
Use only evidence available in structured data; do not claim to see graphical problems
such as overlapping linework.""",
        output_schema={
            **_COMMON_HEAD,
            "findings": [
                {
                    "id": "F1",
                    "bucket": "missing_information|standards_issues|data_quality|complexity",
                    "severity": "high|medium|low",
                    "title": "string",
                    "detail": "string",
                    "evidence": ["json.path=value", "string"],
                    "recommendation": "string",
                }
            ],
            "layer_findings": [{"layer": "string", "issue": "string", "evidence": "string"}],
            "dimension_findings": [
                {"kind": "string", "count": "number", "issue": "string", "evidence": "string"}
            ],
            "checks_not_possible_from_data": ["string"],
            "data_gaps": ["string"],
            "release_recommendation": "release|release_with_comments|hold",
            "effort_hours_estimate": "number|null",
        },
        focus=("layers", "layer_stats", "entities", "dimensions", "dimension_styles", "warnings"),
    ),
    "bom": TaskSpec(
        key="bom",
        title="Bill of materials / component takeoff",
        instructions="""Produce a component takeoff from block references and their attributes.
- Each distinct non-anonymous block name with refs > 0 becomes one line; quantity = refs.
- Carry the ATTDEF tag names as available attributes; where the payload contains ATTRIB
  text values (see text[] entries of type "attrib"), group the observed values per block.
- Mark lines "needs_source_data" when attributes are defined but no values were captured.
- Report dimension-driven quantities separately (e.g. total wall length is NOT derivable
  from block counts -- say so in exclusions rather than estimating).
- Keep the block name verbatim; do not rename parts or infer manufacturers.""",
        output_schema={
            **_COMMON_HEAD,
            "units": "string|null",
            "items": [
                {
                    "name": "string",
                    "quantity": "number",
                    "definition_entities": "number|null",
                    "attributes": [{"tag": "string", "values": ["string"], "fill_rate": "number 0..1|null"}],
                    "layers": ["string"],
                    "notes": "string|null",
                }
            ],
            "totals": {"lines": "number", "instances": "number", "attribute_coverage": "number 0..1"},
            "exclusions": [{"item": "string", "reason": "string"}],
            "next_steps": ["string"],
        },
        focus=("blocks", "text", "document.units"),
    ),
    "complexity_metrics": TaskSpec(
        key="complexity_metrics",
        title="Quantitative complexity profile",
        instructions="""Report the drawing's complexity and reuse profile as numbers with derivations.
Compute (and show the formula in "derivation"):
- entity density: entities per layout and per populated layer
- annotation ratio: annotations / total entities (also compare with layer_stats.annotation_ratio)
- reuse ratio: sum(blocks.items[].refs) / max(1, entities.total); leverage: max(blocks.items[].leverage)
- 3D share: entities.three_d / entities.total
- proxy share: proxies.count / entities.total (data-portability risk)
- dimension intensity: dimension_stats.total / max(1, entities.total)
- sheet count: number of non-modelspace layouts
Then give a draughting-effort estimate band (hours) with the assumptions that drive it,
and flag whether the file is best analysed as a sheet set, a model, or a hybrid.""",
        output_schema={
            **_COMMON_HEAD,
            "metrics": [
                {
                    "name": "string",
                    "value": "number",
                    "unit": "string|null",
                    "derivation": "string",
                    "evidence": ["json.path"],
                }
            ],
            "profile": "sheet_set|model|hybrid",
            "effort": {"hours_low": "number", "hours_high": "number", "assumptions": ["string"]},
            "risk_flags": [{"flag": "string", "why": "string", "severity": "high|medium|low"}],
            "data_gaps": ["string"],
        },
        focus=("entities", "layers", "blocks", "dimension_stats", "layouts", "proxies"),
    ),
    "standards_compliance": TaskSpec(
        key="standards_compliance",
        title="Layer/annotation standards compliance",
        instructions="""Audit the drawing against the naming/annotation standard visible in its own data
(default to the discipline convention implied by discipline.primary; honour any standard
given in the user brief). For each rule: state the expected pattern, the observed value,
a pass/fail, and the affected layer/style names (from layers[]/text_styles[]/
dimension_styles[]/linetypes[]).
Check at minimum: layer prefix consistency (discipline-prefix code), one linetype per
discipline where conventions demand it, text heights clustered on a small set,
dimstyle reuse vs. overrides (dimensions[].style vs. dimension_styles[].text_height),
frozen/off/locked misuse (content on non-plotted layers), orphaned layer references,
and unused template baggage. Report compliance as a percentage of checks passed.""",
        output_schema={
            **_COMMON_HEAD,
            "standard": {"name": "string", "source": "payload_convention|user_brief", "notes": "string|null"},
            "checks": [
                {
                    "rule": "string",
                    "expected": "string",
                    "observed": "string",
                    "status": "pass|fail|warn|not_checkable",
                    "affected": ["string"],
                    "evidence": ["json.path"],
                }
            ],
            "compliance": {"passed": "number", "failed": "number", "score": "number 0..1"},
            "remediation_plan": [{"priority": "number", "action": "string", "targets": ["string"]}],
            "data_gaps": ["string"],
        },
        focus=("layers", "linetypes", "text_styles", "dimension_styles", "discipline"),
    ),
    "discipline_summary": TaskSpec(
        key="discipline_summary",
        title="Executive drawing summary",
        instructions="""Write a short summary for a project lead who will not open the file:
what this drawing is, what it contains, what it is drawn with, and what looks risky.
Every statement must be traceable to a payload value. Confirm or reject the
discipline heuristic and explain why. Close with three follow-up questions to the
design team that the data cannot answer.""",
        output_schema={
            **_COMMON_HEAD,
            "sheet_name": "string|null",
            "scale": "string|null",
            "contents": [{"description": "string", "evidence": "string"}],
            "authoring_profile": {
                "primary_layers": [{"layer": "string", "entities": "number", "role": "geometry|annotation|mixed"}],
                "units": "string|null",
                "reusable_components": "number",
            },
            "risks": [{"risk": "string", "why": "string", "severity": "high|medium|low"}],
            "highlights": ["string"],
            "questions_for_design_team": ["string"],
        },
        focus=("document", "layers", "entities", "blocks", "text", "discipline"),
    ),
    "custom": TaskSpec(
        key="custom",
        title="Requested analysis",
        instructions="""Answer the user's brief below, in full. The brief defines the deliverable;
the rules above still apply (grounded claims, units, JSON only). If the brief asks for
fields not present in the payload, add them with null values and list them in
"data_gaps".""",
        output_schema={"summary": "string", "findings": ["string"], "data_gaps": ["string"]},
        focus=(),
    ),
}


def resolve_task(name: str | None) -> TaskSpec:
    """Look up a task by key, tolerating aliases; unknown keys fall back to custom."""
    if not name:
        return TASKS["discipline_summary"]
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "qa": "sheet_review",
        "review": "sheet_review",
        "qc": "sheet_review",
        "materials": "bom",
        "schedule": "bom",
        "metrics": "complexity_metrics",
        "complexity": "complexity_metrics",
        "layers": "standards_compliance",
        "compliance": "standards_compliance",
        "summary": "discipline_summary",
        "exec": "discipline_summary",
    }
    key = aliases.get(key, key)
    return TASKS.get(key, TASKS["custom"])


def build_system_prompt(
    *,
    extra_instructions: str | None = None,
    output_mode: str = "json",
    audience: str = "engineering review",
) -> str:
    """Assemble the system prompt (schema brief + rules + task + output contract)."""
    blocks = [
        "You are a senior CAD/BIM data analyst. You read machine-extracted JSON descriptions of "
        "AutoCAD DWG drawings and produce engineering-review-grade findings.",
        SCHEMA_BRIEF,
        GROUNDING_RULES,
    ]
    if audience:
        blocks.append(f"AUDIENCE: {audience}. Write for working engineers, not for marketing.")
    if extra_instructions:
        blocks.append(f"OPERATOR INSTRUCTIONS (highest priority):\n{extra_instructions.strip()}")
    if output_mode != "json":
        blocks.append(
            "OUTPUT MODE: markdown prose is allowed for this request, but keep it structured "
            "(headings + bullets, numbers inline) and still cite payload paths."
        )
    return "\n\n".join(blocks)


def build_task_message(
    task: TaskSpec | str | None,
    *,
    payload_json: str,
    brief: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> str:
    """Build the user message: task instructions + the JSON payload."""
    spec = task if isinstance(task, TaskSpec) else resolve_task(task if isinstance(task, str) else None)
    header = [
        "Analyze the drawing payload and return the JSON object described below.",
        spec.render_instructions(),
    ]
    if brief:
        header.append(f"CLIENT BRIEF (authoritative, may narrow the scope):\n{brief.strip()}")
    if context:
        header.append("RUN CONTEXT:\n" + json.dumps(dict(context), separators=(",", ":"), ensure_ascii=False))
    header.extend(
        [
            "DWG PAYLOAD (minified JSON):",
            payload_json,
            "Respond with the JSON object only.",
        ]
    )
    return "\n\n".join(block for block in header if block)


def build_messages(
    payload_json: str,
    *,
    task: TaskSpec | str | None = None,
    brief: str | None = None,
    context: Mapping[str, Any] | None = None,
    extra_instructions: str | None = None,
    output_mode: str = "json",
    audience: str = "engineering review",
) -> list[dict[str, str]]:
    """Full ``messages`` array for ``POST /chat/completions``."""
    spec = task if isinstance(task, TaskSpec) else resolve_task(task if isinstance(task, str) else None)
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                extra_instructions=_task_in_system(spec, output_mode),
                output_mode=output_mode,
                audience=audience,
            ),
        },
        {"role": "user", "content": build_task_message(spec, payload_json=payload_json, brief=brief, context=context)},
    ]


def _task_in_system(task: TaskSpec, output_mode: str) -> str | None:
    """Repeat the task title in the system prompt.

    DeepSeek's JSON mode works best when the word "json" and the target shape
    appear in the *system* prompt as well as in the user turn, so the task title
    and the output schema are anchored there.
    """
    if output_mode != "json":
        return f"Current task: {task.title}. Output valid JSON."
    return (
        f"Current task: {task.title}. The reply MUST be a single valid JSON object "
        f"matching this schema exactly:\n{task.schema_text()}\n"
        "Emit the JSON only -- no explanation outside the object."
    )
