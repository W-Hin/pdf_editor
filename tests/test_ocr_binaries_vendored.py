import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESSERACT_DIR = REPO_ROOT / "ocr_binaries" / "tesseract"
GHOSTSCRIPT_BIN_DIR = REPO_ROOT / "ocr_binaries" / "ghostscript" / "bin"

TESSDATA_LANGUAGES = ["eng", "osd", "spa", "fra", "deu", "por", "chi_sim", "jpn", "ara"]


def test_vendored_tesseract_and_ghostscript_exist():
    assert (TESSERACT_DIR / "tesseract.exe").exists(), "Run scripts/vendor_ocr_binaries.py first."
    assert (GHOSTSCRIPT_BIN_DIR / "gswin64c.exe").exists(), "Run scripts/vendor_ocr_binaries.py first."
    for lang in TESSDATA_LANGUAGES:
        assert (TESSERACT_DIR / "tessdata" / f"{lang}.traineddata").exists(), (
            f"Missing vendored {lang}.traineddata. Run scripts/vendor_ocr_binaries.py "
            "(with TESSDATA_FALLBACK_DIR set if a language pack isn't installed under "
            r"C:\Program Files\Tesseract-OCR\tessdata)."
        )
    assert (TESSERACT_DIR / "tessdata" / "configs").is_dir()
    assert (TESSERACT_DIR / "tessdata" / "tessconfigs").is_dir()
    assert (TESSERACT_DIR / "tessdata" / "pdf.ttf").exists()


def test_vendored_binaries_run_standalone_with_isolated_path():
    # Prove the vendored copies are self-sufficient: run each with PATH set
    # to ONLY that binary's own folder (plus bare Windows system dirs needed
    # for basic DLL loading) - not the real system-wide installs.
    isolated_path = os.pathsep.join([str(TESSERACT_DIR), r"C:\Windows\system32", r"C:\Windows"])
    result = subprocess.run(
        [str(TESSERACT_DIR / "tesseract.exe"), "--version"],
        env={**os.environ, "PATH": isolated_path},
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "tesseract" in result.stdout.lower()

    isolated_path = os.pathsep.join([str(GHOSTSCRIPT_BIN_DIR), r"C:\Windows\system32", r"C:\Windows"])
    result = subprocess.run(
        [str(GHOSTSCRIPT_BIN_DIR / "gswin64c.exe"), "-dNODISPLAY", "-c", "quit"],
        env={**os.environ, "PATH": isolated_path},
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_vendored_ocrmypdf_end_to_end_with_isolated_path(tmp_path):
    # The definitive proof: ocrmypdf itself, with PATH pointing ONLY at the
    # vendored copies (set before ocrmypdf's own import, matching real app
    # startup order), produces correct OCR'd + PDF/A output using nothing
    # but the vendored binaries.
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Vendored binary isolation test.", fontsize=14)
    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    input_path = tmp_path / "input.pdf"
    scanned.save(str(input_path))
    scanned.close()
    doc.close()

    isolated_path = os.pathsep.join([
        str(TESSERACT_DIR), str(GHOSTSCRIPT_BIN_DIR), r"C:\Windows\system32", r"C:\Windows",
    ])
    output_path = tmp_path / "output.pdf"
    script = (
        "import os, sys\n"
        f"os.environ['PATH'] = {isolated_path!r}\n"
        "import ocrmypdf\n"
        f"ocrmypdf.ocr({str(input_path)!r}, {str(output_path)!r}, "
        "skip_text=True, output_type='pdfa', progress_bar=False)\n"
    )
    # Use sys.executable, not the bare string "python": on Windows a venv's
    # python.exe (using the newer venvlauncher.exe stub) re-execs the base
    # interpreter, so a bare "python" on PATH in a child subprocess can
    # resolve to the base/system install instead of this venv. sys.executable
    # guarantees the child uses the exact interpreter running pytest itself.
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert output_path.exists()

    check = fitz.open(str(output_path))
    assert "Vendored binary isolation test." in check[0].get_text()
    check.close()
