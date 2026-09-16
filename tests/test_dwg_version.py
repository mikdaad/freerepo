"""DWG header sniffing and the version policy gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from cad2ai import dwg_version
from cad2ai.errors import NotACadFileError, UnsupportedDwgVersionError


def test_read_sentinel_accepts_known_codes():
    assert dwg_version.read_sentinel(b"AC1032\x00\x00") == "AC1032"
    assert dwg_version.read_sentinel(b"AC1015") == "AC1015"


def test_read_sentinel_rejects_garbage():
    assert dwg_version.read_sentinel(b"MC0000") is None
    assert dwg_version.read_sentinel(b"AC2000") is None
    assert dwg_version.read_sentinel(b"") is None


def test_describe_maps_release_and_years():
    info = dwg_version.describe("AC1032")
    assert info is not None
    assert info.release == "R2018"
    assert info.ezdxf_representable is True
    assert info.known is True
    assert dwg_version.describe("AC1036").ezdxf_representable is False


def test_describe_unknown_returns_none():
    assert dwg_version.describe("AC1099") is None
    assert dwg_version.describe(None) is None


def test_sniff_file(tmp_path: Path):
    target = tmp_path / "x.dwg"
    target.write_bytes(b"AC1027" + b"\x00" * 100)
    sentinel, info = dwg_version.sniff_result(target)
    assert sentinel == "AC1027"
    assert info.release == "R2013"


def test_sniff_missing_file_raises_typed_error(tmp_path: Path):
    with pytest.raises(NotACadFileError) as excinfo:
        dwg_version.sniff_file(tmp_path / "nope.dwg")
    assert excinfo.value.exit_code == 4


def test_policy_rejects_legacy_versions():
    info = dwg_version.describe("AC1009")
    with pytest.raises(UnsupportedDwgVersionError) as excinfo:
        dwg_version.enforce_policy(info, source="old.dwg")
    error = excinfo.value
    assert error.exit_code == 3
    assert "R12" in error.message
    assert "SAVE AS" in (error.hint or "").upper()
    assert error.details["supported_versions"]


def test_policy_allows_legacy_when_opted_in():
    warnings = dwg_version.enforce_policy(dwg_version.describe("AC1009"), source="old.dwg", allow_legacy=True)
    assert any("legacy" in text for text in warnings)


def test_policy_warns_for_newer_than_representable():
    warnings = dwg_version.enforce_policy(dwg_version.describe("AC1036"), source="new.dwg")
    assert any("down-levels" in text for text in warnings)


def test_policy_warns_for_unknown_future_sentinel():
    future = dwg_version.DwgVersionInfo("AC1099", "R2099", "2099", 99)
    warnings = dwg_version.enforce_policy(future, source="future.dwg")
    assert any("newer than the" in text for text in warnings)


def test_policy_accepts_recent_versions_silently():
    assert dwg_version.enforce_policy(dwg_version.describe("AC1032")) == []
    assert dwg_version.enforce_policy(dwg_version.describe("AC1015")) == []


def test_policy_missing_header_raises():
    with pytest.raises(UnsupportedDwgVersionError, match="header is missing"):
        dwg_version.enforce_policy(None, source="broken.dwg")
