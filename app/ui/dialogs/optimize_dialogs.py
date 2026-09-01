from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider

from app.core.pdf_ops import compress_pdf
from app.ui.dialogs.base import ToolDialog


class CompressDialog(ToolDialog):
    title = "Compress PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Image quality:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(60)
        layout.addWidget(self.quality_slider)

    def gather_params(self) -> dict:
        return {"image_quality": self.quality_slider.value()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_compressed.pdf"))
        compress_pdf(input_path, out_path, image_quality=params["image_quality"])
        return [out_path]
