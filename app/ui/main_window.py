from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QGridLayout, QPushButton, QGroupBox


class MainWindow(QMainWindow):
    CATEGORIES = ("Organize", "Edit", "Optimize", "Convert")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Editor")
        self.resize(700, 500)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._grids: dict[str, QGridLayout] = {}
        for name in self.CATEGORIES:
            box = QGroupBox(name)
            grid = QGridLayout(box)
            self._grids[name] = grid
            layout.addWidget(box)

    def add_tool(self, category: str, label: str, dialog_cls) -> None:
        grid = self._grids[category]
        row, col = divmod(grid.count(), 3)
        button = QPushButton(label)
        button.clicked.connect(lambda: dialog_cls(self).exec())
        grid.addWidget(button, row, col)
