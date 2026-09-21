from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.core.errors import PDFError
from app.core.pdf_ops import extract_pages, remove_pages, reorder_pages
from app.ui.dialogs.base import ToolDialog
from app.ui.page_grid import PageGridWidget


def _page_list(pages: list[int], limit: int = 12) -> str:
    text = ", ".join(str(p) for p in pages[:limit])
    return text + (f" … (+{len(pages) - limit} more)" if len(pages) > limit else "")


class _PageSelectDialog(ToolDialog):
    """Click pages in the grid to mark them; the marked pages are what the tool acts on
    (the web app's select mode, instead of counting and ticking page numbers)."""

    verb = "select"          # "remove" / "extract"
    past = "selected"        # "removed" / "extracted"
    select_color = "#2563eb"
    select_badge = "check"   # "x" for removal, a tick for keeping

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.page_grid = PageGridWidget("select")
        self.page_grid.select_color = self.select_color
        self.page_grid.select_badge = self.select_badge
        self.page_grid.set_hint(f"Click the pages you want to {self.verb}.")
        layout.addWidget(self.page_grid)

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        intro = QLabel(f"Click pages in the grid to mark them. Marked pages will be {self.past}.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("selectionSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        row = QHBoxLayout()
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.clicked.connect(self.page_grid.select_all)
        row.addWidget(self.select_all_button)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.page_grid.clear_selection)
        row.addWidget(self.clear_button)
        layout.addLayout(row)
        self.page_grid.selection_changed.connect(self._update_summary)
        self._update_summary()

    def _update_summary(self) -> None:
        pages = self.page_grid.selected_pages()
        self.clear_button.setEnabled(bool(pages))
        if not pages:
            self.summary_label.setText("No pages marked yet.")
            return
        noun = "page" if len(pages) == 1 else "pages"
        self.summary_label.setText(f"{len(pages)} {noun} will be {self.past}: {_page_list(pages)}")

    def gather_params(self) -> dict:
        return {"pages": self.page_grid.selected_pages()}


class RemovePagesDialog(_PageSelectDialog):
    title = "Remove pages"
    verb = "remove"
    past = "removed"
    select_color = "#dc2626"
    select_badge = "x"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        pages = params["pages"]
        if not pages:
            raise PDFError("Click at least one page to remove.")
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_removed.pdf"))
        remove_pages(input_path, pages, out_path)
        return [out_path]


class ExtractPagesDialog(_PageSelectDialog):
    title = "Extract pages"
    verb = "extract"
    past = "extracted"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        pages = params["pages"]
        if not pages:
            raise PDFError("Click at least one page to extract.")
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_extracted.pdf"))
        extract_pages(input_path, pages, out_path)
        return [out_path]


class ReorderPagesDialog(ToolDialog):
    title = "Reorder pages"

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.page_grid = PageGridWidget("reorder")
        self.page_grid.set_hint("Drag a page to a new place.")
        layout.addWidget(self.page_grid)

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        intro = QLabel("Drag pages in the grid into the order you want.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("selectionSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.reset_button = QPushButton("Reset order")
        self.reset_button.clicked.connect(self._reset_order)
        layout.addWidget(self.reset_button)
        self.page_grid.order_changed.connect(self._update_summary)
        self._update_summary()

    def _reset_order(self) -> None:
        self.page_grid.reset_order()
        self._update_summary()

    def _update_summary(self) -> None:
        order = self.page_grid.order()
        moved = order != sorted(order)
        self.reset_button.setEnabled(moved)
        if not order:
            self.summary_label.setText("")
        elif not moved:
            self.summary_label.setText("The pages are in their original order.")
        else:
            self.summary_label.setText(f"New order: {_page_list(order, 16)}")

    def _refresh_thumbnails(self) -> None:
        super()._refresh_thumbnails()
        self._update_summary()

    def gather_params(self) -> dict:
        return {"order": self.page_grid.order()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        order = params["order"]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_reordered.pdf"))
        reorder_pages(input_path, order, out_path)
        return [out_path]
