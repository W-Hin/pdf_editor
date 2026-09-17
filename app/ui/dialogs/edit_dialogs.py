from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QLineEdit, QSlider, QSpinBox

from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers, crop_pdf, redact_pdf, render_page_thumbnail, get_page_count
from app.core.errors import PDFError
from app.ui.dialogs.base import ToolDialog
from app.ui.widgets import RectangleOverlayWidget, box_to_insets, insets_to_box


class RotateDialog(ToolDialog):
    title = "Rotate PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Rotate all pages by:"))
        self.angle_box = QComboBox()
        self.angle_box.addItems(["90", "180", "270"])
        layout.addWidget(self.angle_box)

    def gather_params(self) -> dict:
        return {"angle": int(self.angle_box.currentText())}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        angle = params["angle"]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_rotated.pdf"))
        rotate_pages(input_path, out_path, angle)
        return [out_path]


class WatermarkDialog(ToolDialog):
    title = "Add watermark"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Watermark text:"))
        self.text_input = QLineEdit()
        layout.addWidget(self.text_input)
        layout.addWidget(QLabel("Opacity (%):"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(30)
        layout.addWidget(self.opacity_slider)

    def gather_params(self) -> dict:
        return {
            "text": self.text_input.text(),
            "opacity": self.opacity_slider.value() / 100,
        }

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_watermarked.pdf"))
        add_watermark(input_path, out_path, params["text"], opacity=params["opacity"])
        return [out_path]


class AddPageNumbersDialog(ToolDialog):
    title = "Add page numbers"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Position:"))
        self.position_box = QComboBox()
        self.position_box.addItem("Bottom center", "bottom-center")
        self.position_box.addItem("Bottom right", "bottom-right")
        self.position_box.addItem("Bottom left", "bottom-left")
        self.position_box.addItem("Top center", "top-center")
        self.position_box.addItem("Top right", "top-right")
        self.position_box.addItem("Top left", "top-left")
        layout.addWidget(self.position_box)
        layout.addWidget(QLabel("Format:"))
        self.format_box = QComboBox()
        self.format_box.addItem("3", "number")
        self.format_box.addItem("3 / 12", "number-of-total")
        self.format_box.addItem("Page 3 of 12", "page-x-of-y")
        layout.addWidget(self.format_box)

    def gather_params(self) -> dict:
        return {
            "position": self.position_box.currentData(),
            "format": self.format_box.currentData(),
        }

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_numbered.pdf"))
        add_page_numbers(input_path, out_path, params["position"], params["format"])
        return [out_path]


class CropDialog(ToolDialog):
    title = "Crop PDF"
    dialog_size = (650, 750)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Drag to select the area to KEEP (page 1's layout applies to every page):"))
        self.overlay = RectangleOverlayWidget(multi=False)
        layout.addWidget(self.overlay)

    def on_files_changed(self, paths: list[str]) -> None:
        if not paths:
            return
        from app.core.pdf_ops import render_page_thumbnail
        from PySide6.QtGui import QPixmap
        try:
            thumb_bytes = render_page_thumbnail(paths[0], 1, max_size=600)
        except PDFError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_bytes)
        self.overlay.set_pixmap(pixmap)

    def gather_params(self) -> dict:
        return {"box": self.overlay.single_box()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        box = params["box"]
        if box is None:
            raise PDFError("Drag to select a crop area first.")
        insets = box_to_insets(box)
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_cropped.pdf"))
        crop_pdf(input_path, out_path, **insets)
        return [out_path]


class RedactDialog(ToolDialog):
    title = "Redact PDF"
    dialog_size = (650, 780)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Page:"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setValue(1)
        self.page_spin.valueChanged.connect(self._load_current_page)
        page_row.addWidget(self.page_spin)
        layout.addLayout(page_row)
        layout.addWidget(QLabel("Drag to mark an area to redact; click the × on a box to remove it:"))
        self.overlay = RectangleOverlayWidget(multi=True)
        layout.addWidget(self.overlay)
        self._all_redactions: list[dict] = []
        self._current_page: int | None = None
        self._input_path: str | None = None

    def on_files_changed(self, paths: list[str]) -> None:
        self._all_redactions = []
        self._current_page = None
        self._input_path = paths[0] if paths else None
        if self._input_path is None:
            return
        try:
            count = get_page_count(self._input_path)
        except PDFError:
            return
        self.page_spin.setMaximum(count)
        self.page_spin.setValue(1)
        self._load_current_page()

    def _flush_current_page(self) -> None:
        if self._current_page is None:
            return
        self._all_redactions = [r for r in self._all_redactions if r["page"] != self._current_page]
        self._all_redactions.extend(
            {"page": self._current_page, **box_to_insets(b)} for b in self.overlay.boxes
        )

    def _load_current_page(self) -> None:
        if self._input_path is None:
            return
        self._flush_current_page()
        page_num = self.page_spin.value()
        self._current_page = page_num
        try:
            thumb_bytes = render_page_thumbnail(self._input_path, page_num, max_size=600)
        except PDFError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_bytes)
        self.overlay.set_pixmap(pixmap)
        page_boxes = [insets_to_box(r) for r in self._all_redactions if r["page"] == page_num]
        self.overlay.set_boxes(page_boxes)

    def gather_params(self) -> dict:
        self._flush_current_page()
        return {"redactions": list(self._all_redactions)}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_redacted.pdf"))
        redact_pdf(input_path, out_path, params["redactions"])
        return [out_path]
