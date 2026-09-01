from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QLabel,
)

from app.core.errors import PDFError
from app.core.pdf_ops import get_page_count, remove_pages, extract_pages, reorder_pages
from app.ui.dialogs.base import ToolDialog


class _PageCheckList(QListWidget):
    def populate(self, count: int) -> None:
        self.clear()
        for i in range(1, count + 1):
            item = QListWidgetItem(f"Page {i}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, i)
            self.addItem(item)

    def checked_pages(self) -> list[int]:
        return [
            self.item(i).data(Qt.UserRole)
            for i in range(self.count())
            if self.item(i).checkState() == Qt.Checked
        ]


class RemovePagesDialog(ToolDialog):
    title = "Remove pages"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Check the pages to remove:"))
        self.page_list = _PageCheckList()
        layout.addWidget(self.page_list)

    def on_files_changed(self, paths: list[str]) -> None:
        if paths:
            self.page_list.populate(get_page_count(paths[0]))

    def gather_params(self) -> dict:
        return {"pages": self.page_list.checked_pages()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        pages = params["pages"]
        if not pages:
            raise PDFError("Check at least one page to remove.")
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_removed.pdf"))
        remove_pages(input_path, pages, out_path)
        return [out_path]


class ExtractPagesDialog(ToolDialog):
    title = "Extract pages"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Check the pages to extract:"))
        self.page_list = _PageCheckList()
        layout.addWidget(self.page_list)

    def on_files_changed(self, paths: list[str]) -> None:
        if paths:
            self.page_list.populate(get_page_count(paths[0]))

    def gather_params(self) -> dict:
        return {"pages": self.page_list.checked_pages()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        pages = params["pages"]
        if not pages:
            raise PDFError("Check at least one page to extract.")
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_extracted.pdf"))
        extract_pages(input_path, pages, out_path)
        return [out_path]


class ReorderPagesDialog(ToolDialog):
    title = "Reorder pages"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Drag pages into the order you want:"))
        self.page_list = QListWidget()
        self.page_list.setDragDropMode(QAbstractItemView.InternalMove)
        layout.addWidget(self.page_list)

    def on_files_changed(self, paths: list[str]) -> None:
        if not paths:
            return
        count = get_page_count(paths[0])
        self.page_list.clear()
        for i in range(1, count + 1):
            item = QListWidgetItem(f"Page {i}")
            item.setData(Qt.UserRole, i)
            self.page_list.addItem(item)

    def gather_params(self) -> dict:
        order = [self.page_list.item(i).data(Qt.UserRole) for i in range(self.page_list.count())]
        return {"order": order}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        order = params["order"]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_reordered.pdf"))
        reorder_pages(input_path, order, out_path)
        return [out_path]
