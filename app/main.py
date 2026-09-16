import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.dialogs.organize_dialogs import MergeDialog, SplitDialog
from app.ui.dialogs.pages_dialogs import RemovePagesDialog, ExtractPagesDialog, ReorderPagesDialog
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog
from app.ui.dialogs.optimize_dialogs import CompressDialog, RepairDialog, ProtectDialog, OcrDialog, PdfToPdfaDialog, UnlockDialog
from app.ui.dialogs.convert_dialogs import ToImagesDialog, ToWordDialog, PdfToMarkdownDialog, PdfToPptxDialog, PdfToXlsxDialog, ImagesToPdfDialog


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.add_tool("Organize", "Merge PDF", MergeDialog)
    window.add_tool("Organize", "Split PDF", SplitDialog)
    window.add_tool("Organize", "Remove pages", RemovePagesDialog)
    window.add_tool("Organize", "Extract pages", ExtractPagesDialog)
    window.add_tool("Organize", "Reorder pages", ReorderPagesDialog)
    window.add_tool("Edit", "Rotate PDF", RotateDialog)
    window.add_tool("Edit", "Add watermark", WatermarkDialog)
    window.add_tool("Optimize", "Compress PDF", CompressDialog)
    window.add_tool("Optimize", "Repair PDF", RepairDialog)
    window.add_tool("Optimize", "Protect PDF", ProtectDialog)
    window.add_tool("Optimize", "OCR PDF", OcrDialog)
    window.add_tool("Optimize", "PDF to PDF/A", PdfToPdfaDialog)
    window.add_tool("Optimize", "Unlock PDF", UnlockDialog)
    window.add_tool("Convert", "PDF to JPG", ToImagesDialog)
    window.add_tool("Convert", "PDF to Word", ToWordDialog)
    window.add_tool("Convert", "PDF to Markdown", PdfToMarkdownDialog)
    window.add_tool("Convert", "PDF to PowerPoint", PdfToPptxDialog)
    window.add_tool("Convert", "PDF to Excel", PdfToXlsxDialog)
    window.add_tool("Convert", "Images to PDF", ImagesToPdfDialog)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
