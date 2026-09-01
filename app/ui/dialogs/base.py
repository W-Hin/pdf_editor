import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QLabel,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QWidget,
    QScrollArea,
)

from app.core.errors import PDFError
from app.core.pdf_ops import get_page_count, render_page_thumbnail
from app.ui.workers import Worker


class ToolDialog(QDialog):
    """Base dialog: input file picker + subclass-provided options + run button + progress."""

    title = "Tool"
    file_filter = "PDF files (*.pdf)"
    allow_multiple_files = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self.resize(480, 360)
        self._worker: Worker | None = None
        self._output_paths: list[str] = []

        layout = QVBoxLayout(self)

        file_row = QHBoxLayout()
        self.file_list = QListWidget()
        file_row.addWidget(self.file_list)
        pick_btn = QPushButton("Add file(s)…")
        pick_btn.clicked.connect(self._pick_files)
        file_row.addWidget(pick_btn)
        layout.addLayout(file_row)

        self.thumbnail_strip = QScrollArea()
        self.thumbnail_strip.setWidgetResizable(True)
        self.thumbnail_strip.setFixedHeight(130)
        self.thumbnail_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._thumbnail_container = QWidget()
        self._thumbnail_layout = QHBoxLayout(self._thumbnail_container)
        self.thumbnail_strip.setWidget(self._thumbnail_container)
        layout.addWidget(self.thumbnail_strip)

        self.options_widget = QWidget()
        self.build_options(self.options_widget)
        layout.addWidget(self.options_widget)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        button_row = QHBoxLayout()
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self._run)
        button_row.addWidget(self.run_button)
        self.open_folder_button = QPushButton("Show in folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        button_row.addWidget(self.open_folder_button)
        layout.addLayout(button_row)

    def build_options(self, container: QWidget) -> None:
        """Override in subclasses to add tool-specific option widgets into `container`."""

    def on_files_changed(self, paths: list[str]) -> None:
        """Override in subclasses to react when the selected file list changes."""

    def run_operation(self, input_paths: list[str]) -> list[str]:
        """Override in subclasses: perform the operation, return output path(s)."""
        raise NotImplementedError

    def selected_files(self) -> list[str]:
        return [self.file_list.item(i).text() for i in range(self.file_list.count())]

    def _pick_files(self) -> None:
        if not self.allow_multiple_files:
            self.file_list.clear()
            path, _ = QFileDialog.getOpenFileName(self, "Select file", "", self.file_filter)
            if path:
                self.file_list.addItem(path)
        else:
            paths, _ = QFileDialog.getOpenFileNames(self, "Select file(s)", "", self.file_filter)
            for path in paths:
                self.file_list.addItem(path)
        self.on_files_changed(self.selected_files())
        self._refresh_thumbnails()

    def _refresh_thumbnails(self) -> None:
        while self._thumbnail_layout.count():
            item = self._thumbnail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        paths = self.selected_files()
        if not paths:
            return
        try:
            count = get_page_count(paths[0])
        except PDFError:
            return
        for i in range(1, count + 1):
            try:
                thumb_bytes = render_page_thumbnail(paths[0], i, max_size=100)
            except PDFError:
                continue
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            label = QLabel()
            label.setPixmap(pixmap)
            label.setToolTip(f"Page {i}")
            self._thumbnail_layout.addWidget(label)

    def _run(self) -> None:
        input_paths = self.selected_files()
        if not input_paths:
            QMessageBox.warning(self, "No file selected", "Add at least one file first.")
            return
        self.run_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Working…")
        self._worker = Worker(self.run_operation, input_paths)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, output_paths) -> None:
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        self._output_paths = output_paths if isinstance(output_paths, list) else [output_paths]
        self.status_label.setText(f"Done — {len(self._output_paths)} file(s) created.")
        self.open_folder_button.setEnabled(True)

    def _on_failure(self, message: str) -> None:
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        self.status_label.setText("Failed.")
        QMessageBox.critical(self, "Operation failed", message)

    def _open_output_folder(self) -> None:
        if not self._output_paths:
            return
        folder = str(Path(self._output_paths[0]).parent)
        os.startfile(folder)
