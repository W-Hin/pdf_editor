import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.dialogs.organize_dialogs import MergeDialog, SplitDialog
from app.ui.dialogs.pages_dialogs import RemovePagesDialog, ExtractPagesDialog, ReorderPagesDialog
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog
from app.ui.dialogs.optimize_dialogs import CompressDialog


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
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
