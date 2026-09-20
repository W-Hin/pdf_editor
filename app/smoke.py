"""Self-test for a packaged desktop build: `PDFEditorDesktop.exe --smoke <report>`.

Exercises the parts a broken bundle loses first (the Qt window, PDF to Markdown's
layout model, OCR's bundled engines) and writes what happened to <report>. The
packaged exe is windowed, so it has no console to print to.
"""
import os
import sys
import tempfile
import traceback
from pathlib import Path


def _checks(work: Path, report: Path) -> list[tuple[str, object]]:
    import pymupdf

    from app.core.ocr import ocr_pdf
    from app.core.pdf_ops import pdf_to_markdown_zip, rotate_pages

    text_pdf = work / "text.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    page.insert_textbox(pymupdf.Rect(30, 30, 370, 250), "Smoke test page. The quick brown fox.", fontsize=20)
    pix = page.get_pixmap(dpi=200)
    doc.save(str(text_pdf))
    doc.close()

    scan_pdf = work / "scan.pdf"
    scan = pymupdf.open()
    scan_page = scan.new_page(width=400, height=300)
    scan_page.insert_image(scan_page.rect, pixmap=pix)
    scan.save(str(scan_pdf))
    scan.close()

    def window():
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication

        from app.main import build_main_window
        from app.ui.theme import apply_theme

        apply_theme(QApplication.instance())
        assert "Inter" in QFontDatabase.families(), "the bundled Inter font did not load"
        win = build_main_window()
        win.show()
        QApplication.processEvents()
        # Kept beside the report so a build can be looked at, not just trusted.
        win.grab().save(str(report.with_suffix(".png")))

    def rotate():
        out = work / "rotated.pdf"
        rotate_pages(str(text_pdf), str(out), 90)
        with pymupdf.open(str(out)) as d:
            assert d[0].rotation == 90

    def markdown():
        out = work / "md.zip"
        pdf_to_markdown_zip(str(text_pdf), str(out))
        assert out.stat().st_size > 0

    def ocr():
        out = work / "ocr.pdf"
        ocr_pdf(str(scan_pdf), str(out), languages=["eng"], convert_to_pdfa=False)
        with pymupdf.open(str(out)) as d:
            assert "fox" in d[0].get_text().lower(), "OCR produced no text"

    return [("main window", window), ("rotate", rotate), ("pdf to markdown", markdown), ("ocr", ocr)]


def run_smoke(report_path: str) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines: list[str] = []
    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        try:
            checks = _checks(Path(tmp), Path(report_path))
        except Exception:
            lines.append("SETUP FAILED\n" + traceback.format_exc())
            checks = []
            failed = True
        for name, check in checks:
            try:
                check()
                lines.append(f"ok    {name}")
            except Exception:
                failed = True
                lines.append(f"FAIL  {name}\n{traceback.format_exc()}")
    lines.append("SMOKE FAILED" if failed else "SMOKE PASSED")
    Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
