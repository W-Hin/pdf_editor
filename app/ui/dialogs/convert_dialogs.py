from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QLineEdit

from app.core.errors import PDFError
from app.core.pdf_ops import render_to_images, pdf_to_markdown_zip, images_to_pdf
from app.core.convert import convert_to_word
from app.core.pdf_to_office import pdf_to_pptx, pdf_to_xlsx
from app.ui.dialogs.base import ToolDialog


class ToImagesDialog(ToolDialog):
    title = "PDF to JPG"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Format:"))
        self.format_box = QComboBox()
        self.format_box.addItems(["png", "jpg"])
        layout.addWidget(self.format_box)

    def gather_params(self) -> dict:
        return {"image_format": self.format_box.currentText()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        output_dir = str(Path(input_path).parent)
        return render_to_images(input_path, output_dir, image_format=params["image_format"])


class ToWordDialog(ToolDialog):
    title = "PDF to Word"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + ".docx"))
        convert_to_word(input_path, out_path)
        return [out_path]


class PdfToMarkdownDialog(ToolDialog):
    title = "PDF to Markdown"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_markdown.zip"))
        pdf_to_markdown_zip(input_path, out_path)
        return [out_path]


class PdfToPptxDialog(ToolDialog):
    title = "PDF to PowerPoint"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + ".pptx"))
        pdf_to_pptx(input_path, out_path)
        return [out_path]


class PdfToXlsxDialog(ToolDialog):
    title = "PDF to Excel"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + ".xlsx"))
        pdf_to_xlsx(input_path, out_path)
        return [out_path]


class ImagesToPdfDialog(ToolDialog):
    title = "Images to PDF"
    allow_multiple_files = True
    file_filter = "Image files (*.jpg *.jpeg *.png)"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Output filename:"))
        self.filename_input = QLineEdit()
        layout.addWidget(self.filename_input)
        layout.addWidget(QLabel("Fit mode:"))
        self.fit_mode_box = QComboBox()
        self.fit_mode_box.addItem("Fit (show the whole image)", "fit")
        self.fit_mode_box.addItem("Fill (crop to fill the page)", "fill")
        layout.addWidget(self.fit_mode_box)

    def on_files_changed(self, paths: list[str]) -> None:
        if paths and not self.filename_input.text().strip():
            default_name = Path(paths[0]).stem + "_combined.pdf"
            self.filename_input.setText(default_name)

    def gather_params(self) -> dict:
        return {
            "filename": self.filename_input.text().strip(),
            "fit_mode": self.fit_mode_box.currentData(),
        }

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        filename = params["filename"]
        if not filename:
            raise PDFError("Enter an output filename.")
        if any(sep in filename for sep in ("/", "\\", ":")):
            raise PDFError("Output filename must be a plain file name, not a path.")
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        output_path = str(Path(input_paths[0]).parent / filename)
        images_to_pdf(input_paths, output_path, params["fit_mode"])
        return [output_path]
