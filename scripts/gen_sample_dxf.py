#!/usr/bin/env python3
"""Generate a sample DXF for demos and tests (no binary CAD files in git).

The sample reproduces every structure Phase 2 reads -- a layer table with ACI
colours/linetypes/lineweights (including an off and a non-plotted layer),
dimension styles with overrides, blocks with ``ATTDEF`` attributes and many
``INSERT`` references, frozen/anonymous XREF-ish blocks, TEXT/MTEXT annotation
and both associated and text-overridden dimensions -- so the whole pipeline can
be exercised without an ODA File Converter::

    python scripts/gen_sample_dxf.py samples/demo.dxf
    python scripts/gen_sample_dxf.py samples/mech.dxf --scheme mech
    python main.py analyze samples/demo.dxf --task bom --dry-run

``--as-dwg`` writes the file with a ``.dwg`` extension and a real DWG version
header so the Phase-1 version gate and fallback logic can be demoed too (the
body is DXF, which the parser will report on rather than pretend to parse).
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing


def _layers(doc: Drawing) -> None:
    def ensure(name: str, **attribs: object) -> None:
        # ezdxf pre-creates DEFPOINTS (and the doc may be re-opened), so adding
        # blindly would raise DXFTableEntryError.
        if name in doc.layers:
            return
        doc.layers.new(name, dxfattribs=dict(attribs))

    ensure("A-WALL", color=7, linetype="Continuous", lineweight=35)
    ensure("A-DOOR", color=3, linetype="Continuous", lineweight=25)
    ensure("A-WWIN-TEXT", color=2, linetype="Continuous")
    ensure("A-ANNO-DIM", color=1, linetype="Continuous")
    ensure("A-ANNO-TEXT", color=6, linetype="Continuous")
    ensure("A-ANNO-GRID", color=8, linetype="DASHED")
    # HIDDEN is deliberately *not* defined below: it exercises the undefined
    # linetype diagnostic.
    ensure("S-COLS", color=4, linetype="HIDDEN")
    ensure("E-PWR", color=5, linetype="CENTER")
    ensure("P-EQ", color=9, linetype="Continuous")
    ensure("DEFPOINTS", color=7, plot=0)
    ensure("X-TEMPLATE-UNUSED", color=250, linetype="Continuous")
    ensure("A-DEAD", color=7, linetype="Continuous")
    doc.layers.get("A-DEAD").freeze()
    doc.layers.get("P-EQ").off()
    doc.layers.get("S-COLS").lock()


def _linetypes(doc: Drawing) -> None:
    existing = {line_type.dxf.name for line_type in doc.linetypes}
    for name, pattern, description in (
        ("DASHED", [0.25, -0.25], "Dashed ____ ____"),
        ("CENTER2", [1.25, -0.25, 0.25, -0.25], "Center __._.__._"),
        ("GAS_LEADER", [0.0, -0.125, 0.0], "Gas leader"),
    ):
        if name not in existing:
            doc.linetypes.new(name, dxfattribs={"description": description, "pattern": pattern})


def _styles(doc: Drawing) -> None:
    if "ARCH_TITLE" not in {style.dxf.name for style in doc.styles}:
        doc.styles.new("ARCH_TITLE", dxfattribs={"font": "romans.shx", "bigfont": "txt.shx", "width": 0.85})
    # ezdxf rejects "/" in table entry names, so the architectural 3/32 style is
    # stored as ARCH-3-32.
    if "ARCH-3-32" not in {style.dxf.name for style in doc.dimstyles}:
        doc.dimstyles.new(
            "ARCH-3-32",
            dxfattribs={
                "dimtxt": 0.1875,
                "dimdec": 2,
                "dimgap": 0.0625,
                "dimtad": 1,
                "dimzin": 8,
                "dimlfac": 1.0,
                "dimtxsty": "ARCH_TITLE",
            },
        )
    if "MECH-ISO" not in {style.dxf.name for style in doc.dimstyles}:
        doc.dimstyles.new(
            "MECH-ISO",
            dxfattribs={"dimtxt": 3.5, "dimdec": 1, "dimlfac": 1.0, "dimrnd": 0.1, "dimaunit": 2},
        )


def _blocks(doc: Drawing) -> None:
    door = doc.blocks.new("DOOR_STD", dxfattribs={"base_point": (0, 0, 0)})
    door.add_line((0, 0), (0.9, 0), dxfattribs={"layer": "A-DOOR"})
    door.add_arc((0, 0), 0.9, 0, 90, dxfattribs={"layer": "A-DOOR"})
    door.add_attdef("TYPE", (0.1, 0.4), dxfattribs={"height": 0.15, "layer": "A-WWIN-TEXT"})
    door.add_attdef("WIDTH", (0.1, 0.2), dxfattribs={"height": 0.15, "layer": "A-WWIN-TEXT"})
    door.add_attdef("FIRE_RATING", (0.1, 0.0), dxfattribs={"height": 0.15, "layer": "A-WWIN-TEXT"})

    column = doc.blocks.new("COL-12x12", dxfattribs={"base_point": (0, 0, 0)})
    column.add_lwpolyline([(0, 0), (0.37, 0), (0.37, 0.37), (0, 0.37)], close=True, dxfattribs={"layer": "S-COLS"})
    column.add_attdef("LOAD_KN", (0.0, 0.5), dxfattribs={"height": 0.15})

    panel = doc.blocks.new("PANEL-208V", dxfattribs={"base_point": (0, 0, 0)})
    panel.add_circle((0, 0), 0.3, dxfattribs={"layer": "E-PWR"})
    panel.add_attdef("PANEL_ID", (0.0, 0.4), dxfattribs={"height": 0.15})
    panel.add_attdef("AMPS", (0.0, -0.4), dxfattribs={"height": 0.15})

    # Anonymous/paper-space-like block that is never referenced -> "template baggage".
    doc.blocks.new("TITLEBAR_UNUSED", dxfattribs={"base_point": (0, 0, 0)}).add_line((0, 0), (10, 0))


def _walls(msp, rng: random.Random) -> None:
    for index in range(14):
        x = index * 4.0
        msp.add_line((x, 0), (x, 9.0), dxfattribs={"layer": "A-WALL"})
        msp.add_line((x, 0), (x + 4.0, 0), dxfattribs={"layer": "A-WALL"})
        if index % 3 == 0:
            msp.add_lwpolyline(
                [(x + 0.5, 1.0), (x + 2.5, 1.0), (x + 2.5, 3.0), (x + 0.5, 3.0)],
                close=True,
                dxfattribs={"layer": "A-WALL"},
            )
    for index in range(9):
        msp.add_text(
            f"GRID {chr(ord('A') + index)}",
            dxfattribs={"height": 0.35, "layer": "A-ANNO-GRID", "insert": (index * 4.0, -1.2), "style": "ARCH_TITLE"},
        )


def _inserts(msp, rng: random.Random) -> None:
    for index in range(11):
        insert = msp.add_blockref(
            "DOOR_STD",
            (index * 3.5 + 1.0, 0.0),
            dxfattribs={"layer": "A-DOOR", "rotation": rng.choice([0, 90, 180, 270]), "xscale": round(rng.uniform(0.9, 1.1), 3)},
        )
        insert.add_auto_attribs(
            {
                "TYPE": rng.choice(["SINGLE", "DOUBLE", "LOBBY", "SERVICE"]),
                "WIDTH": rng.choice(["36", "42", "72", "90"]),
                "FIRE_RATING": rng.choice(["20", "45", "60", "90"]),
            }
        )
    for row in range(4):
        for col in range(5):
            insert = msp.add_blockref("COL-12x12", (col * 8.0, 12.0 + row * 8.0), dxfattribs={"layer": "S-COLS"})
            insert.add_auto_attribs({"LOAD_KN": str(rng.randint(180, 640))})
    for index in range(6):
        insert = msp.add_blockref("PANEL-208V", (index * 6.0 + 2.0, 30.0), dxfattribs={"layer": "E-PWR"})
        insert.add_auto_attribs({"PANEL_ID": f"LP-{index + 1}", "AMPS": rng.choice(["225", "400", "600"])})


def _annotation(msp, rng: random.Random) -> None:
    notes = (
        "ALL DIMENSIONS TO FACE OF STUD UNLESS NOTED",
        "PROVIDE FIRE STOP AT ALL PENETRATIONS (UL U363)",
        "CONTRACTOR TO VERIFY EXISTING CONDITIONS PRIOR TO FABRICATION",
        "DOOR HARDWARE PER SCHEDULE DP-1",
        "UNO: WALL THICKNESS 150 MM",
        "SEE SHEET S-201 FOR COLUMN REINFORCEMENT",
        "PANEL SCHEDULE PER E-401 - VERIFY AMPS WITH CLIENT",
        "ROOF DRAIN SLOPE 1:100 TOWARD SCUPPER",
    )
    for index, note in enumerate(notes):
        msp.add_text(note, dxfattribs={"height": 0.2, "layer": "A-ANNO-TEXT", "insert": (2.0, 44.0 + index * 0.8)})
    msp.add_mtext(
        "General notes:\\P1. All work to comply with IBC Chapter 10.\\P2. Tolerances per ACI 117."
        "\\P3. Coordinate with MEP rough-in before deck pour.",
        dxfattribs={"insert": (26.0, 44.0), "char_height": 0.18, "layer": "A-ANNO-TEXT", "width": 24.0},
    )
    for index in range(9):
        msp.add_linear_dim(
            base=(index * 4.0, -3.0),
            p1=(index * 4.0, 0.0),
            p2=((index + 1) * 4.0, 0.0),
            dimstyle="ARCH-3-32",
            dxfattribs={"layer": "A-ANNO-DIM"},
        ).render()
    for index in range(4):
        msp.add_linear_dim(
            base=(30.0 + index * 2.0, 8.0),
            p1=(30.0 + index * 2.0, 0.0),
            p2=(round(30.0 + index * 2.0 + rng.uniform(1.0, 3.9), 3), 0.0),
            dimstyle="MECH-ISO",
            override={"dimrnd": 0.5},
            dxfattribs={"layer": "A-ANNO-DIM"},
        ).render()
    # A dimension with an overridden text string: a classic review finding.
    msp.add_linear_dim(
        base=(0.0, 6.0),
        p1=(0.0, 0.0),
        p2=(12.0, 0.0),
        dimstyle="ARCH-3-32",
        text="12000 TYP",
        dxfattribs={"layer": "A-ANNO-DIM"},
    ).render()


def _mechanical(doc: Drawing, msp, rng: random.Random) -> None:
    """Optional mechanical overlay: bolt circle, tolerance layer, weld note."""
    doc.layers.new("M-GEOM", dxfattribs={"color": 7, "linetype": "Continuous"})
    doc.layers.new("M-TOL", dxfattribs={"color": 1, "linetype": "CENTER"})
    bolt = doc.blocks.new("BOLT-M12x40")
    bolt.add_circle((0, 0), 0.9)
    bolt.add_attdef("GRADE", (0.0, 1.2), dxfattribs={"height": 0.4})
    for index in range(24):
        angle = index * (2 * math.pi / 24)
        insert = msp.add_blockref(
            "BOLT-M12x40",
            (round(60 + 10 * math.cos(angle), 3), round(60 + 10 * math.sin(angle), 3)),
            dxfattribs={"layer": "M-GEOM"},
        )
        insert.add_auto_attribs({"GRADE": rng.choice(["8.8", "10.9", "A2-70"])})
    msp.add_circle((60, 60), 6.0, dxfattribs={"layer": "M-GEOM"})
    msp.add_circle((60, 60), 3.2, dxfattribs={"layer": "M-GEOM"})
    msp.add_linear_dim(
        base=(60, 72), p1=(54, 60), p2=(66, 60), dimstyle="MECH-ISO", dxfattribs={"layer": "M-TOL"}
    ).render()
    msp.add_text("RWELD ALL AROUND 6", dxfattribs={"height": 0.5, "layer": "M-TOL", "insert": (48, 74)})



def _mechanism(doc: Drawing, rng: random.Random) -> None:
    """A standalone machined assembly (no building layers at all).

    ``--scheme mech`` uses this so the discipline classifier gets a genuinely
    mechanical file to chew on instead of a plan with a bolt circle dropped on it.
    """
    for name, attribs in (
        ("M-GEOM", {"color": 7, "linetype": "Continuous"}),
        ("M-TOL", {"color": 1, "linetype": "CENTER"}),
        ("M-DIM", {"color": 1, "linetype": "Continuous"}),
        ("M-TEXT", {"color": 7, "linetype": "Continuous"}),
        # deliberately references a linetype that is not in the LTYPE table
        ("M-FIT", {"color": 4, "linetype": "HIDDEN"}),
        ("M-TEMPLATE-UNUSED", {"color": 250, "linetype": "Continuous"}),
    ):
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs=attribs)

    if "BOLT-M12x40" not in doc.blocks:
        bolt = doc.blocks.new("BOLT-M12x40", dxfattribs={"base_point": (0, 0, 0)})
        bolt.add_circle((0, 0), 0.9)
        bolt.add_line((-0.9, 0), (0.9, 0))
        bolt.add_attdef("GRADE", (0.0, 1.2), dxfattribs={"height": 0.4, "layer": "M-TEXT"})
    if "BEARING-6204" not in doc.blocks:
        bearing = doc.blocks.new("BEARING-6204", dxfattribs={"base_point": (0, 0, 0)})
        bearing.add_circle((0, 0), 2.0)
        bearing.add_circle((0, 0), 1.0)
        bearing.add_attdef("FIT", (0.0, 2.4), dxfattribs={"height": 0.4, "layer": "M-TEXT"})
    if "GEAR-24T" not in doc.blocks:
        gear = doc.blocks.new("GEAR-24T", dxfattribs={"base_point": (0, 0, 0)})
        gear.add_circle((0, 0), 4.8)
        gear.add_circle((0, 0), 1.6)
        for tooth in range(24):
            angle = tooth * (2 * math.pi / 24)
            gear.add_line(
                (round(4.8 * math.cos(angle), 3), round(4.8 * math.sin(angle), 3)),
                (round(5.4 * math.cos(angle), 3), round(5.4 * math.sin(angle), 3)),
            )
        gear.add_attdef("MODULE", (0.0, 5.8), dxfattribs={"height": 0.4, "layer": "M-TEXT"})

    msp = doc.modelspace()
    for index in range(24):
        angle = index * (2 * math.pi / 24)
        insert = msp.add_blockref(
            "BOLT-M12x40",
            (round(20 + 8 * math.cos(angle), 3), round(20 + 8 * math.sin(angle), 3)),
            dxfattribs={"layer": "M-GEOM"},
        )
        insert.add_auto_attribs({"GRADE": rng.choice(["8.8", "10.9", "A2-70"])})
    for index in range(4):
        insert = msp.add_blockref("BEARING-6204", (44.0 + index * 6.0, 20.0), dxfattribs={"layer": "M-FIT"})
        insert.add_auto_attribs({"FIT": rng.choice(["H7/g6", "H8/f7"])})
    for index in range(3):
        insert = msp.add_blockref(
            "GEAR-24T",
            (20.0 + index * 14.0, 44.0),
            dxfattribs={"layer": "M-GEOM", "rotation": rng.choice([0.0, 7.5, 15.0])},
        )
        insert.add_auto_attribs({"MODULE": rng.choice(["2.0", "2.5", "3.0"])})

    # plate profile with a centre bore
    msp.add_lwpolyline(
        [(0, 0), (60, 0), (60, 30), (0, 30)], close=True, dxfattribs={"layer": "M-GEOM"}
    )
    msp.add_circle((20, 20), 6.0, dxfattribs={"layer": "M-GEOM"})
    msp.add_circle((20, 20), 3.2, dxfattribs={"layer": "M-GEOM"})
    for index in range(6):
        msp.add_line((index * 10.0, 0), (index * 10.0, 4.0), dxfattribs={"layer": "M-GEOM"})

    for index in range(6):
        msp.add_linear_dim(
            base=(index * 10.0, -4.0),
            p1=(index * 10.0, 0.0),
            p2=((index + 1) * 10.0, 0.0),
            dimstyle="MECH-ISO",
            dxfattribs={"layer": "M-DIM"},
        ).render()
    msp.add_linear_dim(
        base=(30.0, 36.0), p1=(0.0, 30.0), p2=(60.0, 30.0), dimstyle="MECH-ISO", dxfattribs={"layer": "M-DIM"}
    ).render()
    # overridden dimension text -- the kind of thing a review is supposed to catch
    msp.add_linear_dim(
        base=(66.0, 15.0),
        p1=(60.0, 0.0),
        p2=(60.0, 30.0),
        dimstyle="MECH-ISO",
        text="30 REF",
        dxfattribs={"layer": "M-DIM"},
    ).render()
    for index, note in enumerate(
        (
            "BREAK ALL SHARP EDGES 0.2 x 45",
            "TOLERANCE +/-0.1 UNLESS NOTED",
            "HEAT TREAT 42-46 HRC",
            "DEBURR HOLES",
            "FINISH 3.2 Ra",
        )
    ):
        msp.add_text(note, dxfattribs={"height": 0.5, "layer": "M-TOL", "insert": (2.0, 34.0 + index * 1.4)})
    msp.add_text(
        "PLATE - REV C",
        dxfattribs={"height": 1.0, "layer": "M-TEXT", "insert": (44.0, 34.0), "style": "ARCH_TITLE"},
    )

def build(scheme: str = "arch", seed: int = 7) -> Drawing:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    doc.header["$MEASUREMENT"] = 0  # imperial template
    doc.header["$LUPREC"] = 4
    doc.header["$LTSCALE"] = 1.0
    doc.header["$PSLTSCALE"] = 1
    rng = random.Random(seed)
    _linetypes(doc)
    _styles(doc)
    if scheme == "mech":
        _mechanism(doc, rng)
        sheet_text, sheet_border, title = "M-TEXT", "M-GEOM", "SAMPLE - MECHANISM"
    else:
        _layers(doc)
        _blocks(doc)
        msp = doc.modelspace()
        _walls(msp, rng)
        _inserts(msp, rng)
        _annotation(msp, rng)
        if scheme == "mixed":
            _mechanical(doc, msp, rng)
        sheet_text, sheet_border, title = "A-ANNO-TEXT", "A-WALL", f"SAMPLE - FLOOR PLAN {scheme.upper()}"
    # A title block on the sheet layout, so paper space is not empty.
    layout = doc.layout("Layout1") if "Layout1" in doc.layout_names() else doc.new_layout("Layout1")
    layout.add_text(
        f"{title}  SCALE: 1/4\" = 1'-0\"",
        dxfattribs={"insert": (1.0, 10.0), "height": 0.25, "layer": sheet_text, "style": "ARCH_TITLE"},
    )
    layout.add_lwpolyline([(0, 0), (22.0, 0), (22.0, 17.0), (0, 17.0)], close=True, dxfattribs={"layer": sheet_border})
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", nargs="?", default="samples/demo.dxf", help="output .dxf path")
    parser.add_argument(
        "--scheme",
        choices=("arch", "mech", "mixed"),
        default="arch",
        help="arch: floor plan (default). mech: standalone machined assembly. mixed: plan + mechanical overlay",
    )
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    target = Path(args.output)
    if target.suffix.lower() != ".dxf":
        target = target.with_suffix(".dxf")
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = build(scheme=args.scheme, seed=args.seed)
    doc.saveas(target)
    print(
        f"wrote {target} ({target.stat().st_size} bytes, {len(doc.modelspace())} modelspace entities, "
        f"{len(doc.layers)} layers, {len(list(doc.blocks))} blocks)"
    )
    print("this is a DXF, so it parses with the ezdxf backend: no ODA File Converter needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
