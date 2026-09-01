from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QSpinBox, QLabel

from app.core.pdf_ops import merge_pdfs, split_pdf, get_page_count
from app.ui.dialogs.base import ToolDialog


class MergeDialog(ToolDialog):
    title = "Merge PDF"
    allow_multiple_files = True

    def run_operation(self, input_paths: list[str]) -> list[str]:
        first = Path(input_paths[0])
        output_path = str(first.with_name(first.stem + "_merged.pdf"))
        merge_pdfs(input_paths, output_path)
        return [output_path]


class SplitDialog(ToolDialog):
    title = "Split PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Pages per output file:"))
        self.pages_per_file = QSpinBox()
        self.pages_per_file.setRange(1, 9999)
        self.pages_per_file.setValue(1)
        layout.addWidget(self.pages_per_file)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        total = get_page_count(input_path)
        step = self.pages_per_file.value()
        ranges = [(start, min(start + step - 1, total)) for start in range(1, total + 1, step)]
        output_dir = str(Path(input_path).parent)
        return split_pdf(input_path, output_dir, ranges)
