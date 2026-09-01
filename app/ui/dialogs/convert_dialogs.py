from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox

from app.core.pdf_ops import render_to_images
from app.core.convert import convert_to_word
from app.ui.dialogs.base import ToolDialog


class ToImagesDialog(ToolDialog):
    title = "PDF to JPG"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Format:"))
        self.format_box = QComboBox()
        self.format_box.addItems(["png", "jpg"])
        layout.addWidget(self.format_box)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        output_dir = str(Path(input_path).parent)
        return render_to_images(input_path, output_dir, image_format=self.format_box.currentText())


class ToWordDialog(ToolDialog):
    title = "PDF to Word"

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + ".docx"))
        convert_to_word(input_path, out_path)
        return [out_path]
