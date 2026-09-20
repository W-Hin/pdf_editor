import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
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


class RecentFilesPage(QScrollArea):
    """Files the tools have produced, newest first (the desktop Recent Files)."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._content.setObjectName("page")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.setWidget(self._content)

    def refresh(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)  # gone now, not whenever the event loop gets to deleteLater
                widget.deleteLater()
        entries = history.list_entries()
        if not entries:
            empty = QLabel("No files produced yet.")
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignCenter)
            self._layout.addWidget(empty)
        for entry in entries:
            self._layout.addWidget(self._row(entry))
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
