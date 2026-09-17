import html
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QLineEdit, QSlider, QPushButton, QFileDialog, QMessageBox, QScrollArea, QTextEdit, QSpinBox

from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers, crop_pdf, redact_pdf, render_page_thumbnail, get_page_count, edit_pdf, extract_form_fields, fill_form
from app.core.compare_pdf import extract_page_texts, diff_page_text, render_page_image, diff_page_visual
from app.core.errors import PDFError
from app.ui.dialogs.base import ToolDialog
from app.ui.widgets import RectangleOverlayWidget, box_to_insets, insets_to_box, SignaturePadWidget, ImagePlacementWidget, FormFieldsWidget, DiffPreviewWidget


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
        instruction = QLabel(
            "Drag to select the area to KEEP on page 1 (applies to every page - "
            "other pages below show a live preview of the same selection):"
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.overlay = RectangleOverlayWidget(multi=False)
        self.overlay.box_changed.connect(self._propagate_box_to_mirrors)

        self._mirror_scroll = QScrollArea()
        self._mirror_scroll.setWidgetResizable(True)
        self._mirror_container = QWidget()
        self._mirror_layout = QVBoxLayout(self._mirror_container)
        self._mirror_layout.addWidget(self.overlay)
        self._mirror_scroll.setWidget(self._mirror_container)
        layout.addWidget(self._mirror_scroll)
        self._mirrors: list[RectangleOverlayWidget] = []

    def _propagate_box_to_mirrors(self) -> None:
        box = self.overlay.single_box()
        for mirror in self._mirrors:
            mirror.set_boxes([box] if box else [])

    def on_files_changed(self, paths: list[str]) -> None:
        self.overlay.set_boxes([])
        # self.overlay is always the first widget in `_mirror_layout` (see
        # build_preview) - only remove entries AFTER it, so the interactive
        # overlay itself is never torn down and re-created.
        while self._mirror_layout.count() > 1:
            item = self._mirror_layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._mirrors = []
        if not paths:
            return
        try:
            count = get_page_count(paths[0])
            thumb_bytes = render_page_thumbnail(paths[0], 1, max_size=450)
        except PDFError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_bytes)
        self.overlay.set_pixmap(pixmap)
        for page_num in range(2, count + 1):
            try:
                mirror_thumb = render_page_thumbnail(paths[0], page_num, max_size=450)
            except PDFError:
                continue
            mirror_pixmap = QPixmap()
            mirror_pixmap.loadFromData(mirror_thumb)
            mirror = RectangleOverlayWidget(multi=False, interactive=False)
            mirror.set_pixmap(mirror_pixmap)
            self._mirror_layout.addWidget(mirror)
            self._mirrors.append(mirror)

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
        instruction = QLabel("Drag to mark an area to redact; click the × on a box to remove it:")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)
        self._page_widgets: list[RectangleOverlayWidget | None] = []

    def on_files_changed(self, paths: list[str]) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._page_widgets = []
        if not paths:
            return
        try:
            count = get_page_count(paths[0])
        except PDFError:
            return
        for page_num in range(1, count + 1):
            try:
                thumb_bytes = render_page_thumbnail(paths[0], page_num, max_size=450)
            except PDFError:
                self._page_widgets.append(None)
                continue
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            overlay = RectangleOverlayWidget(multi=True)
            overlay.set_pixmap(pixmap)
            self._container_layout.addWidget(overlay)
            self._page_widgets.append(overlay)

    def gather_params(self) -> dict:
        redactions = []
        for page_num, overlay in enumerate(self._page_widgets, start=1):
            if overlay is None:
                continue
            redactions.extend({"page": page_num, **box_to_insets(b)} for b in overlay.boxes)
        return {"redactions": redactions}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_redacted.pdf"))
        redact_pdf(input_path, out_path, params["redactions"])
        return [out_path]


class SignDialog(ToolDialog):
    title = "Sign PDF"
    dialog_size = (650, 780)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)

        self.source_panel = QWidget()
        source_layout = QVBoxLayout(self.source_panel)
        draw_row = QHBoxLayout()
        draw_btn = QPushButton("Draw new")
        draw_btn.clicked.connect(self._toggle_draw_pad)
        draw_row.addWidget(draw_btn)
        upload_btn = QPushButton("Upload new")
        upload_btn.clicked.connect(self._upload_signature)
        draw_row.addWidget(upload_btn)
        source_layout.addLayout(draw_row)

        self.pad_panel = QWidget()
        pad_layout = QVBoxLayout(self.pad_panel)
        self.pad = SignaturePadWidget()
        pad_layout.addWidget(self.pad)
        pad_button_row = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.pad.clear)
        pad_button_row.addWidget(clear_btn)
        save_btn = QPushButton("Save signature")
        save_btn.clicked.connect(self._save_drawn_signature)
        pad_button_row.addWidget(save_btn)
        pad_layout.addLayout(pad_button_row)
        self.pad_panel.setVisible(False)
        source_layout.addWidget(self.pad_panel)
        layout.addWidget(self.source_panel)

        self.placement_panel = QWidget()
        placement_layout = QVBoxLayout(self.placement_panel)
        instruction = QLabel("Click to place your signature; drag to move it, its corner handle to resize, or click the × to remove it:")
        instruction.setWordWrap(True)
        placement_layout.addWidget(instruction)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._scroll.setWidget(self._container)
        placement_layout.addWidget(self._scroll)
        different_btn = QPushButton("Use a different signature")
        different_btn.clicked.connect(self._use_different_signature)
        placement_layout.addWidget(different_btn)
        self.placement_panel.setVisible(False)
        layout.addWidget(self.placement_panel)

        self.signature_path: str | None = None
        self._input_path: str | None = None
        self._page_widgets: list[ImagePlacementWidget | None] = []

    def _toggle_draw_pad(self) -> None:
        self.pad_panel.setVisible(not self.pad_panel.isVisible())

    def _save_drawn_signature(self) -> None:
        if not self.pad.has_drawing():
            QMessageBox.warning(self, "Nothing drawn", "Draw a signature first.")
            return
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        self.pad.save_png(path)
        self.use_signature_file(path)

    def _upload_signature(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select signature image", "", "Image files (*.png *.jpg *.jpeg)")
        if path:
            self.use_signature_file(path)

    def use_signature_file(self, path: str) -> None:
        """Adopts `path` as the current signature source and switches to the
        placement phase - the single entry point both 'Draw new'/'Upload
        new' and tests use."""
        self.signature_path = path
        self.source_panel.setVisible(False)
        self.placement_panel.setVisible(True)
        self._rebuild_page_widgets()

    def _use_different_signature(self) -> None:
        self.signature_path = None
        self.pad.clear()
        self.pad_panel.setVisible(False)
        self.placement_panel.setVisible(False)
        self.source_panel.setVisible(True)
        self._clear_page_widgets()

    def on_files_changed(self, paths: list[str]) -> None:
        self._input_path = paths[0] if paths else None
        self._rebuild_page_widgets()

    def _clear_page_widgets(self) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._page_widgets = []

    def _rebuild_page_widgets(self) -> None:
        self._clear_page_widgets()
        if self._input_path is None or self.signature_path is None:
            return
        try:
            count = get_page_count(self._input_path)
        except PDFError:
            return
        sig_pixmap = QPixmap(self.signature_path)
        for page_num in range(1, count + 1):
            try:
                thumb_bytes = render_page_thumbnail(self._input_path, page_num, max_size=450)
            except PDFError:
                self._page_widgets.append(None)
                continue
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            widget = ImagePlacementWidget()
            widget.set_page_pixmap(pixmap)
            widget.set_signature_pixmap(sig_pixmap)
            self._container_layout.addWidget(widget)
            self._page_widgets.append(widget)

    def gather_params(self) -> dict:
        placements = []
        for page_num, widget in enumerate(self._page_widgets, start=1):
            if widget is None:
                continue
            placements.extend({"page": page_num, **p} for p in widget.placements)
        return {"signature_path": self.signature_path, "placements": placements}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        signature_path = params["signature_path"]
        elements = [
            {
                "type": "image", "page": p["page"], "file_id": signature_path,
                "x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"],
            }
            for p in params["placements"]
        ]
        image_paths = {signature_path: signature_path}
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_signed.pdf"))
        edit_pdf(input_path, out_path, elements, image_paths)
        return [out_path]


class FillFormDialog(ToolDialog):
    title = "PDF Forms"
    dialog_size = (650, 780)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        instruction = QLabel("Fill in the fields below; values are read from the document as-is.")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.empty_label = QLabel("No fillable fields found in this document.")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)
        self.fields_widget = FormFieldsWidget()
        layout.addWidget(self.fields_widget)

    def on_files_changed(self, paths: list[str]) -> None:
        self.fields_widget.set_fields([], [])
        self.empty_label.setVisible(False)
        if not paths:
            return
        input_path = paths[0]
        try:
            fields = extract_form_fields(input_path)
            count = get_page_count(input_path)
        except PDFError:
            return
        pixmaps = []
        for page_num in range(1, count + 1):
            thumb_bytes = render_page_thumbnail(input_path, page_num, max_size=450)
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            pixmaps.append(pixmap)
        self.fields_widget.set_fields(fields, pixmaps)
        self.empty_label.setVisible(not self.fields_widget.has_fields())

    def gather_params(self) -> dict:
        return {"values": self.fields_widget.values()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_filled.pdf"))
        fill_form(input_path, out_path, params["values"])
        return [out_path]


class CompareDialog(ToolDialog):
    title = "Compare PDF"
    dialog_size = (900, 780)
    allow_multiple_files = True

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)

        clear_btn = QPushButton("Clear files")
        clear_btn.clicked.connect(self._clear_files)
        layout.addWidget(clear_btn)

        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Page:"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setValue(1)
        self.page_spin.valueChanged.connect(self._load_current_page)
        page_row.addWidget(self.page_spin)
        layout.addLayout(page_row)

        self.status_label_compare = QLabel(
            "Add exactly 2 files to compare (the first is treated as the original, the second as the changed version)."
        )
        self.status_label_compare.setWordWrap(True)
        layout.addWidget(self.status_label_compare)

        self.text_diff_view = QTextEdit()
        self.text_diff_view.setReadOnly(True)
        self.text_diff_view.setFixedHeight(150)
        layout.addWidget(self.text_diff_view)

        visual_container = QWidget()
        visual_row = QHBoxLayout(visual_container)
        self.visual_a = DiffPreviewWidget()
        self.visual_b = DiffPreviewWidget()
        visual_row.addWidget(self.visual_a)
        visual_row.addWidget(self.visual_b)
        visual_scroll = QScrollArea()
        visual_scroll.setWidgetResizable(True)
        visual_scroll.setWidget(visual_container)
        layout.addWidget(visual_scroll)

        self._path_a: str | None = None
        self._path_b: str | None = None
        self._pages: list[dict] = []
        self._page_count_a = 0
        self._page_count_b = 0
        self._file_count = 0

    def _clear_files(self) -> None:
        self.file_list.clear()
        self.on_files_changed([])

    def _clear_visual_diff(self) -> None:
        self.visual_a.set_pixmap(QPixmap())
        self.visual_a.set_boxes([])
        self.visual_b.set_pixmap(QPixmap())
        self.visual_b.set_boxes([])

    def on_files_changed(self, paths: list[str]) -> None:
        self._pages = []
        self._path_a = None
        self._path_b = None
        self._file_count = len(paths)
        self.text_diff_view.clear()
        if len(paths) != 2:
            self.status_label_compare.setText(
                "Add exactly 2 files to compare (the first is treated as the original, the second as the changed version)."
            )
            self._clear_visual_diff()
            return
        try:
            texts_a = extract_page_texts(paths[0])
            texts_b = extract_page_texts(paths[1])
        except PDFError:
            self.status_label_compare.setText("Could not read one of the selected files. Check that both are valid PDFs.")
            self._clear_visual_diff()
            return
        self._path_a, self._path_b = paths[0], paths[1]
        self._page_count_a, self._page_count_b = len(texts_a), len(texts_b)
        total_pages = max(self._page_count_a, self._page_count_b)
        for i in range(total_pages):
            has_a = i < self._page_count_a
            has_b = i < self._page_count_b
            if has_a and has_b:
                self._pages.append({"text_diff": diff_page_text(texts_a[i], texts_b[i]), "has_counterpart": True})
            else:
                self._pages.append({"text_diff": [], "has_counterpart": False})
        self.status_label_compare.setText(f"Comparing {total_pages} page(s).")
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(total_pages)
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        self._load_current_page()

    def _render_text_diff(self, entries: list[dict]) -> str:
        color_by_op = {"insert": "#c8f7c5", "delete": "#f7c5c5", "equal": "transparent"}
        lines = []
        for entry in entries:
            color = color_by_op.get(entry["op"], "transparent")
            text = html.escape(entry["text"] or " ")
            lines.append(f'<div style="background-color: {color};">{text}</div>')
        return "".join(lines)

    def _load_current_page(self) -> None:
        if self._path_a is None or self._path_b is None or not self._pages:
            return
        page_num = self.page_spin.value()
        page = self._pages[page_num - 1]
        if not page["has_counterpart"]:
            if page_num <= self._page_count_a and page_num > self._page_count_b:
                self.text_diff_view.setHtml("<i>Page removed (only in the first document)</i>")
            else:
                self.text_diff_view.setHtml("<i>Page added (only in the second document)</i>")
            self.visual_a.setVisible(False)
            self.visual_b.setVisible(False)
            return
        self.visual_a.setVisible(True)
        self.visual_b.setVisible(True)
        self.text_diff_view.setHtml(self._render_text_diff(page["text_diff"]))
        try:
            image_a = render_page_image(self._path_a, page_num, 1800)
            image_b = render_page_image(self._path_b, page_num, 1800)
            boxes = diff_page_visual(self._path_a, self._path_b, page_num, 1800)
        except PDFError:
            self.status_label_compare.setText("Could not render this page for comparison.")
            self._clear_visual_diff()
            return
        pixmap_a, pixmap_b = QPixmap(), QPixmap()
        pixmap_a.loadFromData(image_a)
        pixmap_b.loadFromData(image_b)
        display_a = pixmap_a.scaled(400, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        display_b = pixmap_b.scaled(400, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.visual_a.set_pixmap(display_a)
        self.visual_a.set_boxes(boxes)
        self.visual_b.set_pixmap(display_b)
        self.visual_b.set_boxes(boxes)

    def gather_params(self) -> dict:
        return {"file_count": self._file_count}

    def run_operation(self, input_paths: list[str], params: dict) -> tuple[list[str], str]:
        if params["file_count"] != 2:
            raise PDFError("Select exactly 2 files to compare.")
        if self._path_a is None or self._path_b is None:
            raise PDFError("Could not read one of the selected files. Check that both are valid PDFs.")
        return ([], f"Compared {len(self._pages)} page(s).")
