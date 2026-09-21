import multiprocessing
import os
import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme
from app.ui.dialogs.organize_dialogs import MergeDialog, SplitDialog
from app.ui.dialogs.pages_dialogs import RemovePagesDialog, ExtractPagesDialog, ReorderPagesDialog
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog, RedactDialog, SignDialog, FillFormDialog, CompareDialog, EditPdfDialog
from app.ui.dialogs.optimize_dialogs import CompressDialog, RepairDialog, ProtectDialog, OcrDialog, PdfToPdfaDialog, UnlockDialog
from app.ui.dialogs.convert_dialogs import ToImagesDialog, ToWordDialog, PdfToMarkdownDialog, PdfToPptxDialog, PdfToXlsxDialog, ImagesToPdfDialog


def build_main_window() -> MainWindow:
    window = MainWindow()
    window.add_tool("Organize", "Merge PDF", MergeDialog, "stack")
    window.add_tool("Organize", "Split PDF", SplitDialog, "scissors")
    window.add_tool("Organize", "Remove pages", RemovePagesDialog, "file-x")
    window.add_tool("Organize", "Extract pages", ExtractPagesDialog, "file-arrow-down")
    window.add_tool("Organize", "Reorder pages", ReorderPagesDialog, "arrows-down-up")
    window.add_tool("Edit", "Rotate PDF", RotateDialog, "arrow-clockwise")
    window.add_tool("Edit", "Add watermark", WatermarkDialog, "drop")
    window.add_tool("Edit", "Add page numbers", AddPageNumbersDialog, "list-numbers")
    window.add_tool("Edit", "Crop PDF", CropDialog, "crop")
    window.add_tool("Edit", "Redact PDF", RedactDialog, "eraser")
    window.add_tool("Edit", "Sign PDF", SignDialog, "signature")
    window.add_tool("Edit", "PDF Forms", FillFormDialog, "list-checks")
    window.add_tool("Edit", "Compare PDF", CompareDialog, "file-magnifying-glass")
    window.add_tool("Edit", "Edit PDF", EditPdfDialog, "note-pencil")
    window.add_tool("Optimize", "Compress PDF", CompressDialog, "arrows-in-simple")
    window.add_tool("Optimize", "Repair PDF", RepairDialog, "wrench")
    window.add_tool("Optimize", "Protect PDF", ProtectDialog, "lock")
    window.add_tool("Optimize", "OCR PDF", OcrDialog, "scan")
    window.add_tool("Optimize", "PDF to PDF/A", PdfToPdfaDialog, "archive")
    window.add_tool("Optimize", "Unlock PDF", UnlockDialog, "lock-open")
    window.add_tool("Convert", "PDF to Image", ToImagesDialog, "image")
    window.add_tool("Convert", "PDF to Word", ToWordDialog, "file-doc")
    window.add_tool("Convert", "PDF to Markdown", PdfToMarkdownDialog, "file-text")
    window.add_tool("Convert", "PDF to PowerPoint", PdfToPptxDialog, "file-ppt")
    window.add_tool("Convert", "PDF to Excel", PdfToXlsxDialog, "file-xls")
    window.add_tool("Convert", "Images to PDF", ImagesToPdfDialog, "file-image")
    return window


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = build_main_window()
    window.show()
    window.check_for_updates()
    return app.exec()


if __name__ == "__main__":
    # Needed for the packaged exe: OCR starts worker processes, and without this
    # each one re-runs this whole program (a second window) instead of its job.
    multiprocessing.freeze_support()
    if len(sys.argv) >= 3 and sys.argv[1] == "--smoke":
        from app.smoke import run_smoke

        # Headless: a build machine may have no display. Qt must also exist
        # before the smoke test builds the window.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication(sys.argv)
        sys.exit(run_smoke(sys.argv[2]))
    sys.exit(main())
