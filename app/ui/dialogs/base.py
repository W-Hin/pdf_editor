import os
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QStackedWidget,
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
from app.ui.page_grid import PageGridWidget
from app.ui.theme import MUTED_FOREGROUND, icon, icon_pixmap
from app.ui.workers import Worker


class _StatusLabel(QLabel):
    """Takes no room while it has nothing to say (an empty label still costs its
    height plus the layout spacing, which showed as a gap above the Run button)."""

    def __init__(self):
        super().__init__("")
        self.setVisible(False)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


class ToolDialog(QDialog):
    """Base dialog: input file picker + subclass-provided options + run button + progress."""

    title = "Tool"
    file_filter = "PDF files (*.pdf)"
    allow_multiple_files = False
    dialog_size = (480, 360)
    SIDE_PANEL_WIDTH = 320

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self.resize(*self.dialog_size)
        self._worker: Worker | None = None
        self._output_paths: list[str] = []
        self._embedded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._states = QStackedWidget()
        outer.addWidget(self._states)
        self.setAcceptDrops(True)

        # ---- state 1: no file chosen yet - one big, obvious way to choose ----
        kind = "PDF " if self.file_filter.startswith("PDF") else ""
        self._pick_default_text = f"Choose {kind}files\u2026" if self.allow_multiple_files else f"Choose a {kind}file\u2026"
        chooser = QWidget()
        chooser_layout = QVBoxLayout(chooser)
        chooser_layout.addStretch(2)
        card = QFrame()
        card.setObjectName("chooserCard")
        card.setFixedWidth(520)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(10)
        card_icon = QLabel()
        card_icon.setPixmap(icon_pixmap("upload-simple", MUTED_FOREGROUND, 44))
        card_icon.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(card_icon)
        card_title = QLabel(self._pick_default_text.rstrip("\u2026"))
        card_title.setObjectName("chooserTitle")
        card_title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(card_title)
        card_hint = QLabel("or drop " + ("them" if self.allow_multiple_files else "it") + " here")
        card_hint.setObjectName("chooserHint")
        card_hint.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(card_hint)
        self.choose_button = QPushButton("Browse\u2026")
        self.choose_button.setProperty("primary", True)
        self.choose_button.setCursor(Qt.PointingHandCursor)
        self.choose_button.clicked.connect(self._pick_files)
        card_layout.addWidget(self.choose_button, 0, Qt.AlignHCenter)
        chooser_layout.addWidget(card, 0, Qt.AlignHCenter)
        chooser_layout.addStretch(3)
        self._states.addWidget(chooser)

        # ---- state 2: the workspace - the pages get the room, options sit beside them ----
        workspace = QWidget()
        work = QVBoxLayout(workspace)
        work.setContentsMargins(0, 0, 0, 0)
        work.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(10)
        pick_btn = QPushButton(self._pick_default_text)
        self._pick_btn = pick_btn
        pick_btn.setObjectName("dropButton")
        pick_btn.setIcon(icon("upload-simple", MUTED_FOREGROUND, 18))
        pick_btn.setCursor(Qt.PointingHandCursor)
        pick_btn.clicked.connect(self._pick_files)
        top.addWidget(pick_btn)
        self.status_label = _StatusLabel()
        self.status_label.setWordWrap(True)
        top.addWidget(self.status_label, 1)
        top.addStretch(1)
        self.run_button = QPushButton("Run")
        self.run_button.setProperty("primary", True)
        self.run_button.setIcon(icon("play", "#ffffff", 16))
        self.run_button.clicked.connect(self._run)
        top.addWidget(self.run_button)
        self.open_folder_button = QPushButton("Show in folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        top.addWidget(self.open_folder_button)
        work.addLayout(top)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(84 if self.allow_multiple_files else 56)
        self.file_list.setVisible(False)
        work.addWidget(self.file_list)
        model = self.file_list.model()
        for changed in (model.rowsInserted, model.rowsRemoved, model.modelReset):
            changed.connect(self._sync_file_list_visibility)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        work.addWidget(self.progress)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.preview_widget = QWidget()
        self.build_preview(self.preview_widget)
        body.addWidget(self.preview_widget, 1)
        self._body_layout = body

        self.options_widget = QWidget()
        self.build_options(self.options_widget)
        self.side_panel = QFrame()
        self.side_panel.setObjectName("sidePanel")
        self.side_panel.setFixedWidth(self.SIDE_PANEL_WIDTH)
        side = QVBoxLayout(self.side_panel)
        side.setContentsMargins(16, 14, 16, 16)
        side.setSpacing(10)
        side_title = QLabel("Options")
        side_title.setObjectName("sidePanelTitle")
        side.addWidget(side_title)
        if self.options_widget.layout() is not None:
            self.options_widget.layout().setContentsMargins(0, 0, 0, 0)
        side.addWidget(self.options_widget)
        side.addStretch(1)
        # A tool with no options (Edit PDF's controls live in its toolbar) gets no panel:
        # its pages take the whole width.
        has_options = self.options_widget.layout() is not None
        self.options_widget.setVisible(has_options)
        self.side_panel.setVisible(has_options)
        body.addWidget(self.side_panel, 0, Qt.AlignTop)
        work.addLayout(body, 1)
        self._states.addWidget(workspace)

    def _show_state(self, has_files: bool) -> None:
        """Chooser until there is a file, then the workspace."""
        self._states.setCurrentIndex(1 if has_files else 0)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        own = cls.__dict__.get("on_files_changed")
        if own is not None:
            # However a tool learns of its files (the picker, a drop, or code), a
            # tool that has files shows its workspace, and one without shows the chooser.
            def on_files_changed(self, paths, _own=own):
                self._show_state(bool(paths))
                return _own(self, paths)

            on_files_changed.__doc__ = own.__doc__
            cls.on_files_changed = on_files_changed

    def _accepted_suffixes(self) -> set[str]:
        return {"." + ext.lower() for ext in re.findall(r"\*\.(\w+)", self.file_filter)}

    def _droppable_paths(self, event) -> list[str]:
        suffixes = self._accepted_suffixes()
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        return [p for p in paths if not suffixes or Path(p).suffix.lower() in suffixes]

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and self._droppable_paths(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        paths = self._droppable_paths(event)
        if not paths:
            return super().dropEvent(event)
        event.acceptProposedAction()
        self._add_files(paths if self.allow_multiple_files else paths[:1])

    def shutdown(self) -> None:
        """Called before the tool goes away; a tool with background work stops it."""
        grid = getattr(self, "page_grid", None)
        if grid is not None:
            grid.shutdown()

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
        """Override in subclasses to replace the default preview with something else
        (e.g. an interactive rectangle-selection widget for Crop/Redact). Default: a
        grid of large page thumbnails, like the web app's."""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.page_grid = PageGridWidget("view")
        layout.addWidget(self.page_grid)

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

    def selected_files(self) -> list[str]:
        return [self.file_list.item(i).text() for i in range(self.file_list.count())]

    def _sync_file_list_visibility(self, *_args) -> None:
        # A list of one file is just noise: a single-file tool shows the name on the
        # (now slim) choose bar instead, and only a multi-file tool lists its files.
        count = self.file_list.count()
        single = not self.allow_multiple_files
        self._show_state(count > 0)
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
            path, _ = QFileDialog.getOpenFileName(self, "Select file", "", self.file_filter)
            paths = [path] if path else []
        else:
            paths, _ = QFileDialog.getOpenFileNames(self, "Select file(s)", "", self.file_filter)
        if not paths and not self.allow_multiple_files:
            # Cancelling a change keeps the file that is already chosen.
            return
        self._add_files(paths)

    def _add_files(self, paths: list[str]) -> None:
        """Adds files (replacing the current one for a single-file tool) and tells the tool."""
        if not self.allow_multiple_files:
            self.file_list.clear()
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
        """Show the chosen file's pages in the default page grid (a tool with its own
        preview has no `page_grid` and does nothing here)."""
        grid = getattr(self, "page_grid", None)
        if grid is None:
            return
        paths = self.selected_files()
        grid.set_document(paths[0] if paths else None)

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
