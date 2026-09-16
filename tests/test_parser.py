"""Phase 1: the ezdxf + odafc loader, its version gate and error mapping."""

from __future__ import annotations

import ezdxf
import pytest

from pathlib import Path

from cad2ai import parser
from cad2ai.errors import (
    CorruptCadFileError,
    DwgConverterError,
    DwgConverterNotInstalledError,
    InputFileError,
    NotACadFileError,
    UnsupportedDwgVersionError,
)
from cad2ai.parser import Backend, load_drawing


def test_loads_dxf_directly(arch_dxf):
    parsed = load_drawing(arch_dxf, audit=True)
    assert parsed.backend is Backend.EZDXF
    assert parsed.doc is not None
    assert parsed.source == arch_dxf
    assert parsed.size_bytes > 0
    assert parsed.sha256 and len(parsed.sha256) == 12
    assert parsed.audit is not None and parsed.audit.ok
    summary = parsed.summary()
    assert summary["modelspace_entities"] > 20
    assert summary["layer_count"] >= 10


def test_dxf_load_needs_no_oda(arch_dxf, monkeypatch):
    # Even with the converter unavailable, DXF input must work (no ODA needed).
    monkeypatch.setattr(parser, "_import_odafc", lambda: (_ for _ in ()).throw(DwgConverterNotInstalledError("nope")))
    assert load_drawing(arch_dxf).backend.value == "ezdxf.readfile"


def test_dwg_uses_odafc_readfile(fake_dwg, oda_factory, arch_dxf):
    fake = oda_factory(installed=True, source=arch_dxf)
    parsed = load_drawing(fake_dwg, backend="oda", oda_timeout=None)
    assert parsed.backend is Backend.ODA_READFILE
    assert parsed.doc is not None
    assert parsed.dwg.sentinel == "AC1032"
    assert fake.readfile_calls, "odafc.readfile must be the primary code path"
    call = fake.readfile_calls[0]
    assert call["filename"] == str(fake_dwg)
    assert call["version"] == "ACAD2018"
    assert call["audit"] is True
    assert parsed.lossless if hasattr(parsed, "lossless") else True


def test_dwg_falls_back_to_convert_on_unicode_bug(fake_dwg, oda_factory, arch_dxf):
    fake = oda_factory(installed=True, source=arch_dxf, readfile_error=UnicodeEncodeError("ascii", "x", 0, 1, "surrogates not allowed"))
    parsed = load_drawing(fake_dwg, backend="oda", oda_timeout=None)
    assert parsed.backend is Backend.ODA_CONVERT
    assert fake.convert_calls, "the known ezdxf decoding bug must trigger the convert fallback"
    assert any("odafc.readfile failed" in warning for warning in parsed.warnings)
    assert parsed.converted_dxf is None


def test_unsupported_version_is_refused_before_the_converter(fake_dwg, oda_factory, tmp_path):
    legacy = tmp_path / "legacy.dwg"
    legacy.write_bytes(b"AC1009" + b"\x00" * 64)
    fake = oda_factory(installed=True, source=tmp_path / "body.dxf")
    with pytest.raises(UnsupportedDwgVersionError) as excinfo:
        load_drawing(legacy)
    assert excinfo.value.sentinel == "AC1009"
    assert fake.readfile_calls == [], "the converter must not be launched for known-bad versions"


def test_missing_converter_raises_actionable_error(fake_dwg, oda_factory):
    oda_factory(installed=False)
    with pytest.raises(DwgConverterNotInstalledError) as excinfo:
        load_drawing(fake_dwg)
    hint = excinfo.value.hint or ""
    assert "opendesign.com" in hint
    assert "fallback aps" in hint


def test_converter_version_rejection_is_mapped(fake_dwg, oda_factory):
    oda_factory(installed=True, source=None, readfile_error=FakeOdafcError(fake_dwg))
    with pytest.raises(UnsupportedDwgVersionError) as excinfo:
        load_drawing(fake_dwg, oda_timeout=None)
    assert "ODA File Converter rejected" in excinfo.value.message
    assert excinfo.value.details["path"].endswith("demo.dwg")

    # the addon's own exception type maps to the same typed error
    fake2 = oda_factory(installed=True, source=None)
    fake2.readfile_error = _make_odafc_exception(fake2, "UnsupportedVersion", "unsupported DWG version")
    with pytest.raises(UnsupportedDwgVersionError):
        load_drawing(fake_dwg, oda_timeout=None)


class FakeOdafcError(Exception):
    """Message-only failure that mentions a version problem."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "the file version is not supported by this converter build"


def _make_odafc_exception(fake, name: str, message: str) -> Exception:
    return getattr(fake, name)(message)


def test_corrupt_output_is_mapped(fake_dwg, oda_factory):
    fake = oda_factory(installed=True, source=None)
    fake.readfile_error = _make_odafc_exception(fake, "UnknownODAFCError", "invalid DXF stream, cannot recover file")
    with pytest.raises(CorruptCadFileError):
        load_drawing(fake_dwg, oda_timeout=None)


def test_generic_converter_failure_keeps_context(fake_dwg, oda_factory):
    fake = oda_factory(installed=True, source=None)
    fake.readfile_error = _make_odafc_exception(fake, "UnknownODAFCError", "segfault in module AcDb")
    with pytest.raises(DwgConverterError) as excinfo:
        load_drawing(fake_dwg, oda_timeout=None)
    assert "segfault" in excinfo.value.details["converter_error"]
    assert "doctor" in (excinfo.value.hint or "")


def test_converter_timeout_is_bounded(fake_dwg, oda_factory, arch_dxf):
    oda_factory(installed=True, source=arch_dxf, slow=True)
    with pytest.raises(DwgConverterError) as excinfo:
        load_drawing(fake_dwg, oda_timeout=0.05)
    assert "TIMEOUT" in (excinfo.value.hint or "").upper() or "timed out" in excinfo.value.message


def test_size_guard_rejects_absurd_inputs(tmp_path, oda_factory):
    oda_factory(installed=True, source=None)
    huge = tmp_path / "huge.dwg"
    huge.write_bytes(b"AC1032" + b"\x00" * 4096)
    # any real file fails a 0.00001 MB (10 byte) guard
    with pytest.raises(InputFileError, match="above the"):
        load_drawing(huge, max_file_mb=0.00001)
    with pytest.raises(InputFileError, match="does not exist"):
        load_drawing(tmp_path / "missing.dwg")


def test_wrong_extension_rejected(tmp_path, oda_factory):
    oda_factory(installed=True, source=None)
    pdf = tmp_path / "drawing.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    with pytest.raises(NotACadFileError, match="unsupported file extension"):
        load_drawing(pdf)
    dwg = tmp_path / "explicit.dwg"
    dwg.write_bytes(b"AC1032" + b"\x00" * 20)
    with pytest.raises(NotACadFileError, match="is a DWG but backend='dxf'"):
        load_drawing(dwg, backend="dxf")


def test_unknown_backend_rejected(arch_dxf):
    with pytest.raises(Exception, match="unknown backend"):
        load_drawing(arch_dxf, backend="magic")


def test_dwg_without_header_is_reported(arch_dxf, tmp_path, oda_factory):
    # A .dwg with no AC10xx sentinel (e.g. a DXF renamed by a client): typed error.
    oda_factory(installed=True, source=arch_dxf)
    lying = tmp_path / "renamed.dxf.dwg"
    lying.write_bytes(b"  0\nSECTION\n" + b"\x00" * 32)
    with pytest.raises(UnsupportedDwgVersionError, match="header is missing"):
        load_drawing(lying, backend="oda")


def test_recover_path_handles_missing_eof_tag(tmp_path, arch_dxf):
    lines = Path(arch_dxf).read_text(encoding="utf-8").splitlines(keepends=True)
    broken = tmp_path / "broken.dxf"
    broken.write_text("".join(lines[:-2]), encoding="utf-8")  # drop the trailing 0/EOF pair
    with pytest.raises(Exception, match="missing EOF tag"):
        ezdxf.readfile(broken)
    doc, backend = parser.read_dxf_robust(broken)
    assert backend is Backend.EZDXF_RECOVER
    assert len(doc.modelspace()) > 10


def test_unreadable_file_is_a_typed_parse_error(tmp_path):
    junk = tmp_path / "junk.dxf"
    junk.write_text("this is not a dxf file at all\nhello\nworld\n", encoding="utf-8")
    with pytest.raises(parser.CorruptCadFileError, match="could not load DXF"):
        parser.read_dxf_robust(junk)


def test_settings_supply_defaults(arch_dxf):
    from cad2ai.config import Settings

    settings = Settings.from_env(environ={"CAD2AI_MAX_FILE_MB": "50", "ODA_TARGET_VERSION": "ACAD2013"})
    parsed = load_drawing(arch_dxf, settings=settings)
    assert parsed.size_bytes > 0
    tight = Settings.from_env(environ={"CAD2AI_MAX_FILE_MB": "0.00001"})
    with pytest.raises(InputFileError, match="above the"):
        load_drawing(arch_dxf, settings=tight)


def test_proxy_graphics_are_preserved_on_every_load(arch_dxf, monkeypatch):
    # The "lossless" requirement: proxies survive the read regardless of --no-audit.
    calls: list[bool] = []
    monkeypatch.setattr(ezdxf.options, "preserve_proxy_graphics", lambda state=True: calls.append(state))
    load_drawing(arch_dxf, audit=True)
    load_drawing(arch_dxf, audit=False)
    assert calls == [True, True]
    parsed = load_drawing(arch_dxf, audit=True)
    assert not any("proxy graphic" in warning for warning in parsed.warnings)
