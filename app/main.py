import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.dialogs.organize_dialogs import MergeDialog, SplitDialog


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.add_tool("Organize", "Merge PDF", MergeDialog)
    window.add_tool("Organize", "Split PDF", SplitDialog)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
