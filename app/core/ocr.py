import os
from pathlib import Path

import ocrmypdf
import ocrmypdf.exceptions

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf

_binaries_ensured = False


def _ocr_binaries_dir() -> Path:
    import sys

    if hasattr(sys, "_MEIPASS"):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent.parent.parent
    return base_dir / "ocr_binaries"


def _ensure_ocr_binaries_on_path() -> None:
    global _binaries_ensured
    if _binaries_ensured:
        return
    binaries_dir = _ocr_binaries_dir()
    tesseract_dir = binaries_dir / "tesseract"
    ghostscript_bin_dir = binaries_dir / "ghostscript" / "bin"
    if not (tesseract_dir / "tesseract.exe").exists() or not (ghostscript_bin_dir / "gswin64c.exe").exists():
        raise PDFError(
            "OCR is unavailable — required files are missing from this installation. "
            "Try reinstalling the app."
        )
    os.environ["PATH"] = os.pathsep.join([str(tesseract_dir), str(ghostscript_bin_dir), os.environ.get("PATH", "")])
    _binaries_ensured = True


def _count_pages_with_text(path: str) -> int:
    doc = open_pdf(path)
    try:
        return sum(1 for page in doc if page.get_text().strip())
    finally:
        doc.close()


def ocr_pdf(input_path: str, output_path: str, languages: list[str], convert_to_pdfa: bool) -> dict:
    if not languages:
        raise PDFError("Select at least one language.")
    _ensure_ocr_binaries_on_path()

    pages_with_text_before = _count_pages_with_text(input_path)
    try:
        ocrmypdf.ocr(
            input_path,
            output_path,
            language="+".join(languages),
            skip_text=True,
            rotate_pages=True,
            output_type="pdfa" if convert_to_pdfa else "pdf",
            progress_bar=False,
        )
    except ocrmypdf.exceptions.ExitCodeException as exc:
        raise PDFError(f"OCR failed: {exc}") from exc

    import fitz

    doc = fitz.open(input_path)
    try:
        total_pages = doc.page_count
    finally:
        doc.close()
    pages_skipped = pages_with_text_before
    pages_ocred = total_pages - pages_skipped
    return {"pages_ocred": pages_ocred, "pages_skipped": pages_skipped}


def pdf_to_pdfa(input_path: str, output_path: str) -> None:
    _ensure_ocr_binaries_on_path()
    try:
        ocrmypdf.ocr(
            input_path,
            output_path,
            skip_text=True,
            tesseract_timeout=0,
            output_type="pdfa",
            progress_bar=False,
        )
    except ocrmypdf.exceptions.ExitCodeException as exc:
        raise PDFError(f"PDF/A conversion failed: {exc}") from exc
