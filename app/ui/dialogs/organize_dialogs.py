from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QSpinBox, QLabel, QLineEdit

from app.core.errors import PDFError
from app.core.pdf_ops import merge_pdfs, split_pdf, get_page_count
from app.ui.dialogs.base import ToolDialog


class MergeDialog(ToolDialog):
    title = "Merge PDF"
    allow_multiple_files = True

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Output filename:"))
        self.filename_input = QLineEdit()
        layout.addWidget(self.filename_input)

    def on_files_changed(self, paths: list[str]) -> None:
        if paths and not self.filename_input.text().strip():
            default_name = Path(paths[0]).stem + "_merged.pdf"
            self.filename_input.setText(default_name)

    def gather_params(self) -> dict:
        return {"filename": self.filename_input.text().strip()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        filename = params["filename"]
        if not filename:
            raise PDFError("Enter an output filename.")
        if any(sep in filename for sep in ("/", "\\", ":")):
            raise PDFError("Output filename must be a plain file name, not a path.")
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        output_path = str(Path(input_paths[0]).parent / filename)
        input_resolved = {str(Path(p).resolve()) for p in input_paths}
        if str(Path(output_path).resolve()) in input_resolved:
            raise PDFError("That filename matches one of the input files — choose a different name.")
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

    def gather_params(self) -> dict:
        return {"pages_per_file": self.pages_per_file.value()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        total = get_page_count(input_path)
        step = params["pages_per_file"]
        ranges = [(start, min(start + step - 1, total)) for start in range(1, total + 1, step)]
        output_dir = str(Path(input_path).parent)
        return split_pdf(input_path, output_dir, ranges)
