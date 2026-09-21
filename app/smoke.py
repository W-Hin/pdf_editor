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
        import re
        from pathlib import Path

        from app.ui.theme import stylesheet

        missing = [p for p in re.findall(r'url\("([^"]+)"\)', stylesheet()) if not Path(p).is_file()]
        assert not missing, f"stylesheet images missing from this build: {missing}"
        win = build_main_window()
        win.show()
        QApplication.processEvents()
        # Kept beside the report so a build can be looked at, not just trusted.
        win.grab().save(str(report.with_suffix(".png")))

    def edit_pdf_tool():
        from PySide6.QtWidgets import QApplication

        from app.main import build_main_window
        from app.ui.dialogs.edit_dialogs import EditPdfDialog
        from app.ui.theme import apply_theme

        apply_theme(QApplication.instance())
        win = build_main_window()
        win.open_tool("Edit PDF", EditPdfDialog)  # builds the toolbar (icons) inside the window
        tool = win._current_tool
        tool.on_files_changed([str(text_pdf)])
        assert tool._page_widgets, "Edit PDF showed no pages"
        assert tool.undo_btn is not None and tool.select_btn is not None
        # Pages are drawn on a background thread: prove that works in this build.
        import time

        deadline = time.monotonic() + 20
        while not tool._page_widgets[0].has_pixmap and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        tool.shutdown()
        assert tool._page_widgets[0].has_pixmap, "the background page renderer never delivered a picture"

    def history():
        from app.core import history

        db = work / "history.db"
        history.add_entry(str(text_pdf), "Smoke test", page_count=1, db_path=db)
        entries = history.list_entries(db_path=db)
        assert len(entries) == 1 and entries[0]["exists"]

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

    return [("main window", window), ("edit pdf tool", edit_pdf_tool), ("recent files database", history), ("rotate", rotate), ("pdf to markdown", markdown), ("ocr", ocr)]


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
