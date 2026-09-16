"""Shared fixtures: a realistic ezdxf document, a fake odafc addon, fake LLM."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import ezdxf
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # allow running tests without installation
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# CAD fixtures
# ---------------------------------------------------------------------------


def build_architecture_doc(*, version: str = "R2018") -> Any:
    """A small but structurally complete architectural drawing."""
    doc = ezdxf.new(version, setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUPREC"] = 4
    doc.header["$LTSCALE"] = 1.0

    doc.layers.new("A-WALL", dxfattribs={"color": 7, "linetype": "Continuous", "lineweight": 35})
    doc.layers.new("A-DOOR", dxfattribs={"color": 3, "linetype": "Continuous"})
    doc.layers.new("A-ANNO-DIM", dxfattribs={"color": 1, "linetype": "Continuous"})
    doc.layers.new("A-ANNO-TEXT", dxfattribs={"color": 6, "linetype": "Continuous"})
    doc.layers.new("S-COLS", dxfattribs={"color": 4, "linetype": "HIDDEN"})
    doc.layers.new("E-PWR", dxfattribs={"color": 5, "linetype": "CENTER"})
    doc.layers.new("P-EQ", dxfattribs={"color": 9, "linetype": "Continuous"})
    doc.layers.new("A-DEAD", dxfattribs={"color": 7, "linetype": "Continuous"})
    doc.layers.get("A-DEAD").freeze()
    doc.layers.get("P-EQ").off()
    doc.layers.get("S-COLS").lock()

    door = doc.blocks.new("DOOR_STD", dxfattribs={"base_point": (0, 0, 0)})
    door.add_line((0, 0), (0.9, 0), dxfattribs={"layer": "A-DOOR"})
    door.add_attdef("TYPE", (0.1, 0.4), dxfattribs={"height": 0.15})
    door.add_attdef("WIDTH", (0.1, 0.2), dxfattribs={"height": 0.15})
    door.add_attdef("FIRE_RATING", (0.1, 0.0), dxfattribs={"height": 0.15})

    column = doc.blocks.new("COL-12x12", dxfattribs={"base_point": (0, 0, 0)})
    column.add_lwpolyline([(0, 0), (0.4, 0), (0.4, 0.4), (0, 0.4)], close=True, dxfattribs={"layer": "S-COLS"})
    column.add_attdef("LOAD_KN", (0.0, 0.5), dxfattribs={"height": 0.15})

    doc.blocks.new("UNUSED_BLOCK").add_circle((0, 0), 1.0)

    msp = doc.modelspace()
    for index in range(6):
        msp.add_line((index * 2.0, 0), (index * 2.0, 6.0), dxfattribs={"layer": "A-WALL"})
        msp.add_line((index * 2.0, 0), ((index + 1) * 2.0, 0), dxfattribs={"layer": "A-WALL"})
    for index in range(4):
        insert = msp.add_blockref("DOOR_STD", (index * 2.0 + 1.0, 0.0), dxfattribs={"layer": "A-DOOR", "rotation": 90})
        insert.add_auto_attribs({"TYPE": "SINGLE", "WIDTH": "36", "FIRE_RATING": "45" if index < 2 else "20"})
    for index in range(3):
        insert = msp.add_blockref("COL-12x12", (index * 5.0, 8.0), dxfattribs={"layer": "S-COLS"})
        insert.add_auto_attribs({"LOAD_KN": str(200 + index * 40)})

    msp.add_text(
        "ALL DIMENSIONS TO FACE OF STUD UNLESS NOTED",
        dxfattribs={"height": 0.2, "layer": "A-ANNO-TEXT", "insert": (1.0, 12.0)},
    )
    msp.add_text("GRID A", dxfattribs={"height": 0.35, "layer": "A-ANNO-TEXT", "insert": (0.0, 13.0)})
    msp.add_mtext(
        "General notes:\\P1. Tolerances per ACI 117.\\P2. Coordinate with MEP.",
        dxfattribs={"insert": (4.0, 12.0), "char_height": 0.18, "layer": "A-ANNO-TEXT"},
    )
    for index in range(3):
        msp.add_linear_dim(
            base=(index * 2.0, -1.0),
            p1=(index * 2.0, 0.0),
            p2=((index + 1) * 2.0, 0.0),
            dxfattribs={"layer": "A-ANNO-DIM"},
        ).render()
    msp.add_linear_dim(
        base=(8.0, -2.0),
        p1=(8.0, 0.0),
        p2=(10.0, 0.0),
        text="3000 TYP",
        dxfattribs={"layer": "A-ANNO-DIM"},
    ).render()
    msp.add_circle((1.0, 3.0), 0.5, dxfattribs={"layer": "E-PWR"})
    return doc


def build_mechanical_doc() -> Any:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.new("M-GEOM", dxfattribs={"color": 7, "linetype": "Continuous"})
    doc.layers.new("M-TOL", dxfattribs={"color": 1, "linetype": "CENTER"})
    doc.layers.new("M-BOLT", dxfattribs={"color": 2, "linetype": "HIDDEN"})
    bolt = doc.blocks.new("BOLT-M12x40")
    bolt.add_circle((0, 0), 0.9)
    bolt.add_attdef("GRADE", (0.0, 1.2), dxfattribs={"height": 0.4})
    msp = doc.modelspace()
    import math

    for index in range(16):
        angle = index * (2 * math.pi / 16)
        insert = msp.add_blockref(
            "BOLT-M12x40",
            (round(10 * math.cos(angle), 3), round(10 * math.sin(angle), 3)),
            dxfattribs={"layer": "M-BOLT"},
        )
        insert.add_auto_attribs({"GRADE": "8.8" if index % 2 else "10.9"})
    msp.add_circle((0, 0), 6.0, dxfattribs={"layer": "M-GEOM"})
    msp.add_text("RWELD ALL AROUND 6", dxfattribs={"height": 0.5, "layer": "M-TOL", "insert": (-2.0, 12.0)})
    return doc


@pytest.fixture
def arch_doc() -> Any:
    return build_architecture_doc()


@pytest.fixture
def mech_doc() -> Any:
    return build_mechanical_doc()


@pytest.fixture
def arch_dxf(tmp_path: Path) -> Path:
    path = tmp_path / "demo.dxf"
    build_architecture_doc().saveas(path)
    return path


@pytest.fixture
def fake_dwg(tmp_path: Path, arch_doc: Any) -> Path:
    """A DXF body with a real AC1032 DWG sentinel as the first 6 bytes.

    Enough to drive the version gate and the (stubbed) converter path without
    shipping a binary file in git.
    """
    path = tmp_path / "demo.dwg"
    dxf_text = tmp_path / "body.dxf"
    arch_doc.saveas(dxf_text)
    body = dxf_text.read_text(encoding="utf-8")
    path.write_bytes(b"AC1032\n" + body.encode("utf-8"))
    return path


# ---------------------------------------------------------------------------
# fake ODA File Converter addon
# ---------------------------------------------------------------------------


class FakeOdafc:
    """Duck-typed stand-in for ``ezdxf.addons.odafc``.

    Mirrors the real API surface cad2ai uses: ``is_installed``, ``readfile``,
    ``convert`` and the exception classes, so the parser's mapping logic is
    exercised against realistic behaviour.
    """

    def __init__(
        self,
        *,
        installed: bool = True,
        source: Path | None = None,
        readfile_error: Exception | None = None,
        convert_error: Exception | None = None,
        slow: bool = False,
    ) -> None:
        self.installed = installed
        self.source = source
        self.readfile_error = readfile_error
        self.convert_error = convert_error
        self.slow = slow
        self.readfile_calls: list[dict[str, Any]] = []
        self.convert_calls: list[dict[str, Any]] = []

    # exception classes are looked up by name in the parser
    class ODAFCError(IOError):
        pass

    class UnknownODAFCError(ODAFCError):
        pass

    class ODAFCNotInstalledError(ODAFCError):
        pass

    class UnsupportedFileFormat(ODAFCError):
        pass

    class UnsupportedPlatform(ODAFCError):
        pass

    class UnsupportedVersion(ODAFCError):
        pass

    def _exc(self, name: str) -> type[Exception]:
        return getattr(self, name)

    def is_installed(self) -> bool:
        return self.installed

    def readfile(self, filename: str, version: str | None = None, *, audit: bool = False) -> Any:
        import time

        self.readfile_calls.append({"filename": str(filename), "version": version, "audit": audit})
        if self.slow:
            time.sleep(1.5)
        error = self.readfile_error
        if error is not None:
            raise error
        assert self.source is not None, "FakeOdafc needs a source DXF"
        return ezdxf.readfile(str(self.source))

    def convert(self, source: str, dest: str = "", *, version: str = "R2018", audit: bool = True, replace: bool = False) -> None:
        self.convert_calls.append({"source": str(source), "dest": str(dest), "version": version})
        if self.convert_error is not None:
            raise self.convert_error
        assert self.source is not None, "FakeOdafc needs a source DXF"
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(Path(self.source).read_text(encoding="utf-8"), encoding="utf-8")


@pytest.fixture
def oda_factory(monkeypatch: pytest.MonkeyPatch):
    """Build a :class:`FakeOdafc` and install it as the parser's odafc addon."""

    def factory(**kwargs: Any) -> FakeOdafc:
        from cad2ai import parser

        fake = FakeOdafc(**kwargs)
        monkeypatch.setattr(parser, "_import_odafc", lambda: fake)
        return fake

    return factory


# ---------------------------------------------------------------------------
# fake OpenAI/DeepSeek transport
# ---------------------------------------------------------------------------


class FakeMessage:
    def __init__(self, content: str | None, reasoning: str | None = None) -> None:
        self.content = content
        self.reasoning_content = reasoning


class FakeChoice:
    def __init__(self, content: str | None, finish_reason: str = "stop", reasoning: str | None = None) -> None:
        self.message = FakeMessage(content, reasoning)
        self.finish_reason = finish_reason
        self.index = 0


class FakeUsage:
    def __init__(self, prompt: int = 1000, completion: int = 200, cached: int = 0) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion
        self.prompt_tokens_details = types.SimpleNamespace(cached_tokens=cached) if cached else None
        self.completion_tokens_details = None


class FakeCompletion:
    def __init__(
        self,
        content: str | None,
        *,
        finish_reason: str = "stop",
        prompt_tokens: int = 1000,
        cached: int = 0,
        reasoning: str | None = None,
    ) -> None:
        self.choices = [FakeChoice(content, finish_reason, reasoning)]
        self.usage = FakeUsage(prompt_tokens, 200, cached)
        self.model = "deepseek-flash"
        self.id = "cmpl-fake-1"
        self.created = 1700000000


class FakeResponse:
    """Minimal httpx-like response for error construction."""

    def __init__(self, status_code: int, headers: dict[str, str] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self) -> Any:
        return json.loads(self.text)


class FakeLLM:
    """Scripted ``openai.OpenAI`` replacement: yields responses, raises errors.

    ``default`` is returned once the script runs out, which keeps concurrent
    tests (where completion order is not deterministic) simple.
    """

    def __init__(self, script: list[Any] | None = None, *, default: Any = None) -> None:
        self.script: list[Any] = list(script or [])
        self.default = default
        self.calls: list[dict[str, Any]] = []
        self._completions = _Completions(self)
        self.chat = types.SimpleNamespace(completions=self._completions)

    def next(self) -> Any:
        if not self.script:
            if self.default is not None:
                return self.default() if callable(self.default) else self.default
            raise AssertionError("FakeLLM ran out of scripted responses")
        item = self.script.pop(0)
        if isinstance(item, dict) and item.get("kind") == "json":
            return FakeCompletion(json.dumps(item["data"]))
        return item


class _Completions:
    def __init__(self, owner: FakeLLM) -> None:
        self.owner = owner

    def create(self, **kwargs: Any) -> Any:
        self.owner.calls.append(kwargs)
        item = self.owner.next()
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM(
        [
            {
                "kind": "json",
                "data": {
                    "summary": "Single-storey commercial shell; 86 entities across 10 layers.",
                    "confidence": 0.78,
                    "findings": ["no door schedule on sheet"],
                    "data_gaps": ["no 3D solids present"],
                },
            }
        ]
    )


@pytest.fixture
def recorder() -> list[float]:
    """Sleep recorder: keeps retry tests fast and lets them assert delays."""
    return []


@pytest.fixture
def settings() -> Any:
    from cad2ai.config import Settings

    return Settings.from_env(
        environ={
            "DEEPSEEK_API_KEY": "sk-test-0000",
            "CAD2AI_LOG_LEVEL": "WARNING",
            "CAD2AI_MAX_PAYLOAD_TOKENS": "4096",
        }
    )
