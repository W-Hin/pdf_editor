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

from app.core import history
from app.core.errors import PDFError
from app.core.pdf_ops import get_page_count, render_page_thumbnail
from app.ui.theme import MUTED_FOREGROUND, icon
from app.ui.workers import Worker


class ToolDialog(QDialog):
    """Base dialog: input file picker + subclass-provided options + run button + progress."""

    title = "Tool"
    file_filter = "PDF files (*.pdf)"
    allow_multiple_files = False
    dialog_size = (480, 360)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self.resize(*self.dialog_size)
        self._worker: Worker | None = None
        self._output_paths: list[str] = []
        self._embedded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Same as the web app: one wide "Choose a PDF file..." bar, then the
        # chosen file(s) listed beneath it.
        kind = "PDF " if self.file_filter.startswith("PDF") else ""
        self._pick_default_text = f"Choose {kind}files…" if self.allow_multiple_files else f"Choose a {kind}file…"
        pick_btn = QPushButton(self._pick_default_text)
        self._pick_btn = pick_btn
        pick_btn.setObjectName("dropButton")
        pick_btn.setIcon(icon("upload-simple", MUTED_FOREGROUND, 18))
        pick_btn.setCursor(Qt.PointingHandCursor)
        pick_btn.clicked.connect(self._pick_files)
        layout.addWidget(pick_btn)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(160 if self.allow_multiple_files else 56)
        self.file_list.setVisible(False)
        layout.addWidget(self.file_list)
        model = self.file_list.model()
        for changed in (model.rowsInserted, model.rowsRemoved, model.modelReset):
            changed.connect(self._sync_file_list_visibility)

        self.preview_widget = QWidget()
        self.build_preview(self.preview_widget)
        # The default thumbnail strip has nothing to show until a file is chosen.
        self.preview_widget.setVisible(not hasattr(self, "thumbnail_strip"))
        layout.addWidget(self.preview_widget)

        self.options_widget = QWidget()
        self.build_options(self.options_widget)
        if self.options_widget.layout() is not None:
            self.options_widget.layout().setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.options_widget)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.run_button = QPushButton("Run")
        self.run_button.setProperty("primary", True)
        self.run_button.setIcon(icon("play", "#ffffff", 16))
        self.run_button.clicked.connect(self._run)
        button_row.addWidget(self.run_button)
        self.open_folder_button = QPushButton("Show in folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        button_row.addWidget(self.open_folder_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

    def embed(self) -> None:
        """Turn this from a pop-up window into a plain widget that the main window
        shows in a page. Esc / Enter then no longer close it (a closed embedded
        tool would leave a blank page, and could discard unsaved edits)."""
        self._embedded = True
        self.setWindowFlags(Qt.Widget)

    def accept(self) -> None:
        if not self._embedded:
            super().accept()

    def reject(self) -> None:
        if not self._embedded:
            super().reject()

    def build_preview(self, container: QWidget) -> None:
        """Override in subclasses to replace the default thumbnail-strip preview
        with something else (e.g. an interactive rectangle-selection widget for
        Crop/Redact). Default: the existing horizontal scrolling thumbnail strip."""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.thumbnail_strip = QScrollArea()
        self.thumbnail_strip.setWidgetResizable(True)
        self.thumbnail_strip.setFixedHeight(130)
        self.thumbnail_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._thumbnail_container = QWidget()
        self._thumbnail_layout = QHBoxLayout(self._thumbnail_container)
        self._thumbnail_layout.setAlignment(Qt.AlignLeft)
        self.thumbnail_strip.setWidget(self._thumbnail_container)
        layout.addWidget(self.thumbnail_strip)

    def build_options(self, container: QWidget) -> None:
        """Override in subclasses to add tool-specific option widgets into `container`."""

    def on_files_changed(self, paths: list[str]) -> None:
        """Override in subclasses to react when the selected file list changes."""

    def gather_params(self) -> dict:
        """Override in subclasses to snapshot option-widget values on the GUI thread,
        before the background worker starts. `run_operation` must read only from the
        returned dict, never from `self.<widget>`, since it runs on a worker thread and
        Qt widgets are not safe to touch off the GUI thread."""
        return {}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        """Override in subclasses: perform the operation, return output path(s).
        Runs on a background thread — read only from `params` (see `gather_params`),
        never from `self.<widget>`. May instead return `(output_paths, message)` to
        override the default "Done — N file(s) created." status text with a custom
        one (e.g. a result summary)."""
        raise NotImplementedError

    @property
    def fills_page(self) -> bool:
        """Tools with their own interactive preview (a page canvas) want all the
        room they can get; the plain ones sit compactly under the file bar."""
        return type(self).build_preview is not ToolDialog.build_preview

    def selected_files(self) -> list[str]:
        return [self.file_list.item(i).text() for i in range(self.file_list.count())]

    def _sync_file_list_visibility(self, *_args) -> None:
        # A list of one file is just noise: a single-file tool shows the name on the
        # (now slim) choose bar instead, and only a multi-file tool lists its files.
        count = self.file_list.count()
        single = not self.allow_multiple_files
        self.file_list.setVisible(count > 0 and not single)
        chosen = single and count == 1
        if chosen:
            name = Path(self.file_list.item(0).text()).name
            self._pick_btn.setText(f"{name}   \u00b7   Change file")
        else:
            self._pick_btn.setText(self._pick_default_text)
        self._pick_btn.setIcon(icon("file-pdf" if chosen else "upload-simple", MUTED_FOREGROUND, 18))
        self._pick_btn.setProperty("compact", chosen)
        self._pick_btn.style().unpolish(self._pick_btn)
        self._pick_btn.style().polish(self._pick_btn)

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
        try:
            self.on_files_changed(self.selected_files())
        except PDFError as exc:
            QMessageBox.warning(self, "Could not read file", str(exc))
            self.file_list.clear()
            self._refresh_thumbnails()
            return
        self._refresh_thumbnails()

    def _refresh_thumbnails(self) -> None:
        if not hasattr(self, "_thumbnail_layout"):
            return
        while self._thumbnail_layout.count():
            item = self._thumbnail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.thumbnail_strip.setVisible(False)
        self.preview_widget.setVisible(False)
        paths = self.selected_files()
        if not paths:
            return
        try:
            count = get_page_count(paths[0])
        except PDFError:
            return
        self.thumbnail_strip.setVisible(count > 0)
        self.preview_widget.setVisible(count > 0)
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
        params = self.gather_params()
        self.run_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Working…")
        self._worker = Worker(self.run_operation, input_paths, params)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, result) -> None:
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        if isinstance(result, tuple):
            output_paths, message = result
        else:
            output_paths, message = result, None
        self._output_paths = output_paths if isinstance(output_paths, list) else [output_paths]
        self._record_history(self._output_paths)
        if message is None:
            message = f"Done — {len(self._output_paths)} file(s) created."
        self.status_label.setText(message)
        self.open_folder_button.setEnabled(True)

    def _record_history(self, paths: list[str]) -> None:
        # The list is a convenience: failing to write it must never turn a
        # finished operation into an error.
        for path in paths:
            try:
                pages = get_page_count(path) if str(path).lower().endswith(".pdf") else None
            except Exception:
                pages = None
            try:
                history.add_entry(str(path), self.title, page_count=pages)
            except Exception:
                pass

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
