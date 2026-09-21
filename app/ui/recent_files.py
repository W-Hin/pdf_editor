import os
import subprocess

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core import history
from app.core.errors import PDFError
from app.core.pdf_ops import render_page_thumbnail
from app.ui.theme import MUTED_FOREGROUND, icon, icon_pixmap

THUMB_SIZE = 56
PAGE_SIZE = 50  # entries shown at a time; "Show more" adds another page


class RecentFilesPage(QWidget):
    """Files the tools have produced, newest first (the desktop Recent Files),
    with a search box and "Show more" paging."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by file name, tool or folder\u2026")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(340)
        self.search.setMaximumWidth(420)
        outer.addWidget(self.search, 0, Qt.AlignLeft)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._content.setObjectName("page")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)
        self._limit = PAGE_SIZE
        # Typing searches a moment after the last keystroke, not on every key.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._search_changed)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())

    def reset(self) -> None:
        """Back to a fresh, unfiltered first page (each time the page is opened)."""
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._limit = PAGE_SIZE
        self.refresh()

    def _search_changed(self) -> None:
        self._limit = PAGE_SIZE
        self.refresh()

    def show_more(self) -> None:
        self._limit += PAGE_SIZE
        bar = self._scroll.verticalScrollBar()
        position = bar.value()
        self.refresh()
        bar.setValue(position)  # stay where you were; the new rows are below

    def refresh(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)  # gone now, not whenever the event loop gets to deleteLater
                widget.deleteLater()
        query = self.search.text().strip()
        entries = history.list_entries(limit=self._limit, query=query)
        total = history.count_entries(query=query)
        if not entries:
            message = f"No files match \u201c{query}\u201d." if query else "No files produced yet."
            empty = QLabel(message)
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignCenter)
            self._layout.addWidget(empty)
        for entry in entries:
            self._layout.addWidget(self._row(entry))
        if total > len(entries):
            more = QPushButton(f"Show more ({total - len(entries)} more)")
            more.setObjectName("showMore")
            more.setCursor(Qt.PointingHandCursor)
            more.clicked.connect(self.show_more)
            self._layout.addWidget(more, 0, Qt.AlignHCenter)
        self._layout.addStretch(1)

    def _row(self, entry: dict) -> QFrame:
        row = QFrame()
        row.setObjectName("historyRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        thumb = QLabel()
        thumb.setObjectName("historyThumb")
        thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setPixmap(self._thumbnail(entry))
        layout.addWidget(thumb)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(entry["filename"])
        name.setObjectName("historyName")
        name.setToolTip(entry["path"])
        meta = f'{entry["tool"]} — {entry["created_at"]}'
        if not entry["exists"]:
            meta += " — file not found (moved or deleted)"
        detail = QLabel(meta)
        detail.setObjectName("historyMeta")
        text.addWidget(name)
        text.addWidget(detail)
        layout.addLayout(text, 1)

        path = entry["path"]
        entry_id = entry["id"]
        if entry["exists"]:
            open_button = QPushButton("Open")
            open_button.setIcon(icon("arrow-square-out", MUTED_FOREGROUND, 16))
            open_button.clicked.connect(lambda: self.open_file(path))
            layout.addWidget(open_button)
            folder_button = QPushButton("Show in folder")
            folder_button.setIcon(icon("folder-open", MUTED_FOREGROUND, 16))
            folder_button.clicked.connect(lambda: self.show_in_folder(path))
            layout.addWidget(folder_button)
        remove_button = QPushButton("Remove")
        remove_button.setIcon(icon("trash", MUTED_FOREGROUND, 16))
        remove_button.setToolTip("Remove from this list (the file itself is not deleted)")
        remove_button.clicked.connect(lambda: self.remove(entry_id))
        layout.addWidget(remove_button)
        return row

    def _thumbnail(self, entry: dict) -> QPixmap:
        if entry["exists"] and entry["filename"].lower().endswith(".pdf"):
            try:
                pixmap = QPixmap()
                pixmap.loadFromData(render_page_thumbnail(entry["path"], 1, max_size=THUMB_SIZE * 2))
                if not pixmap.isNull():
                    return pixmap.scaled(THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except PDFError:
                pass
        return icon_pixmap("file-pdf", MUTED_FOREGROUND, 26)

    def remove(self, entry_id: int) -> None:
        history.remove_entry(entry_id)
        self.refresh()

    @staticmethod
    def open_file(path: str) -> None:
        os.startfile(path)

    @staticmethod
    def show_in_folder(path: str) -> None:
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
