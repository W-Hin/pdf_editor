"""One-time script to vendor trimmed Tesseract + Ghostscript runtimes into
ocr_binaries/ (git-ignored) for bundling into the PyInstaller build.

Run this once on a machine with Tesseract and Ghostscript installed via
their official installers (winget: UB-Mannheim.TesseractOCR; official
Artifex GitHub releases for Ghostscript). Re-run after bumping either
dependency's installed version.

Source locations expected (Windows default install paths):
  Tesseract:  C:\\Program Files\\Tesseract-OCR\\
  Ghostscript: C:\\Program Files\\gs\\gs<version>\\ (auto-detected by glob)
"""

import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST = REPO_ROOT / "ocr_binaries"

TESSERACT_SRC = Path(r"C:\Program Files\Tesseract-OCR")
TESSDATA_LANGUAGES = ["eng", "osd", "spa", "fra", "deu", "por", "chi_sim", "jpn", "ara"]

# Optional fallback source directory for .traineddata files not present under
# TESSERACT_SRC/tessdata (e.g. language packs downloaded straight from the
# official tesseract-ocr/tessdata_fast GitHub repo, staged locally instead of
# installed system-wide). Set TESSDATA_FALLBACK_DIR to that directory before
# re-running this script; each language still sourced from TESSERACT_SRC take
# priority, and where a language comes from is printed so the run stays
# self-documenting.
TESSDATA_FALLBACK_DIR_ENV = "TESSDATA_FALLBACK_DIR"

GS_ROOT = Path(r"C:\Program Files\gs")


def find_ghostscript_src() -> Path:
    candidates = sorted(GS_ROOT.glob("gs*"))
    if not candidates:
        sys.exit(f"No Ghostscript install found under {GS_ROOT} — install it first.")
    if len(candidates) > 1:
        print(f"Multiple Ghostscript versions found, using the last one: {candidates[-1]}")
    return candidates[-1]


def vendor_tesseract() -> None:
    if not TESSERACT_SRC.exists():
        sys.exit(f"Tesseract not found at {TESSERACT_SRC} — install it first (winget install UB-Mannheim.TesseractOCR).")
    dest = DEST / "tesseract"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    shutil.copy2(TESSERACT_SRC / "tesseract.exe", dest / "tesseract.exe")
    for dll in TESSERACT_SRC.glob("*.dll"):
        shutil.copy2(dll, dest / dll.name)

    tessdata_dest = dest / "tessdata"
    tessdata_dest.mkdir()
    fallback_dir_raw = os.environ.get(TESSDATA_FALLBACK_DIR_ENV)
    fallback_dir = Path(fallback_dir_raw) if fallback_dir_raw else None

    missing_languages = []
    sourced_from_fallback = []
    for lang in TESSDATA_LANGUAGES:
        src_file = TESSERACT_SRC / "tessdata" / f"{lang}.traineddata"
        if src_file.exists():
            shutil.copy2(src_file, tessdata_dest / src_file.name)
            continue
        fallback_file = fallback_dir / f"{lang}.traineddata" if fallback_dir else None
        if fallback_file is not None and fallback_file.exists():
            shutil.copy2(fallback_file, tessdata_dest / fallback_file.name)
            sourced_from_fallback.append(lang)
            continue
        missing_languages.append(lang)
    if "eng" in missing_languages:
        sys.exit(f"Missing required trained-data file: {TESSERACT_SRC / 'tessdata' / 'eng.traineddata'}")
    if sourced_from_fallback:
        print(
            f"NOTE: {len(sourced_from_fallback)} language pack(s) not installed under "
            f"{TESSERACT_SRC / 'tessdata'}, sourced instead from {TESSDATA_FALLBACK_DIR_ENV}="
            f"{fallback_dir}: {', '.join(sourced_from_fallback)}"
        )
    if missing_languages:
        print(
            f"WARNING: {len(missing_languages)} language pack(s) not installed on this machine, "
            f"skipped: {', '.join(missing_languages)}. Install them under "
            f"{TESSERACT_SRC / 'tessdata'} (or point {TESSDATA_FALLBACK_DIR_ENV} at a staging "
            "directory containing them) and re-run this script to add them."
        )
    shutil.copytree(TESSERACT_SRC / "tessdata" / "configs", tessdata_dest / "configs")
    shutil.copytree(TESSERACT_SRC / "tessdata" / "tessconfigs", tessdata_dest / "tessconfigs")
    shutil.copy2(TESSERACT_SRC / "tessdata" / "pdf.ttf", tessdata_dest / "pdf.ttf")
    print(f"Vendored Tesseract -> {dest}")


def vendor_ghostscript() -> None:
    src = find_ghostscript_src()
    dest = DEST / "ghostscript"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    bin_dest = dest / "bin"
    bin_dest.mkdir()
    shutil.copy2(src / "bin" / "gswin64c.exe", bin_dest / "gswin64c.exe")
    for dll in (src / "bin").glob("*.dll"):
        shutil.copy2(dll, bin_dest / dll.name)

    shutil.copytree(src / "Resource", dest / "Resource")
    shutil.copytree(src / "lib", dest / "lib")
    shutil.copytree(src / "iccprofiles", dest / "iccprofiles")
    print(f"Vendored Ghostscript ({src.name}) -> {dest}")


if __name__ == "__main__":
    vendor_tesseract()
    vendor_ghostscript()
