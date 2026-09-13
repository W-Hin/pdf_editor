from pathlib import Path

from scripts import vendor_ocr_binaries
from scripts.vendor_ocr_binaries import _gs_version_key, find_ghostscript_src


def test_find_ghostscript_src_picks_numerically_newest_version(tmp_path, monkeypatch):
    # Regression test for a bug where sorted(GS_ROOT.glob("gs*")) sorted Path
    # objects lexicographically as strings: "gs10.08.0" < "gs9.56.1" because
    # the character "1" < "9", so a plain sort's [-1] ("last") wrongly picked
    # the OLDER 9.x install when both 9.x and 10.x were present side by side.
    # Verified empirically: sorted(["gs10.08.0", "gs9.56.1"]) ==
    # ["gs10.08.0", "gs9.56.1"], so the old buggy code's candidates[-1] would
    # have returned "gs9.56.1" here instead of the numerically newer
    # "gs10.08.0".
    older = tmp_path / "gs9.56.1"
    newer = tmp_path / "gs10.08.0"
    older.mkdir()
    newer.mkdir()

    monkeypatch.setattr(vendor_ocr_binaries, "GS_ROOT", tmp_path)

    result = find_ghostscript_src()

    assert result == newer
    assert result != older


def test_gs_version_key_orders_versions_numerically():
    assert _gs_version_key(Path("gs9.56.1")) < _gs_version_key(Path("gs10.08.0"))
