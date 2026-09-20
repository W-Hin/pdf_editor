import html
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QLineEdit, QSlider, QPushButton, QFileDialog, QMessageBox, QScrollArea, QTextEdit, QSpinBox, QCheckBox, QColorDialog, QFrame, QMenu

from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers, crop_pdf, redact_pdf, render_page_thumbnail, get_page_count, get_page_size, get_page_rotation, extract_text_runs, edit_pdf, extract_form_fields, fill_form
from app.core.compare_pdf import extract_page_texts, diff_page_text, render_page_image, diff_page_visual
from app.core.errors import PDFError
from app.ui.dialogs.base import ToolDialog
from app.ui.edit_canvas import EditElementsModel, EditPageWidget
from app.ui.theme import ACCENT, MUTED_FOREGROUND, icon_pixmap
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


class EditPdfDialog(ToolDialog):
    title = "Edit PDF"
    dialog_size = (900, 800)

    # Each markup tool owns its OWN colour (and, where it draws strokes, its
    # own width), exactly like the web app's drawColor/shapeColor/
    # highlightColor and drawWidth/shapeWidth: picking "thick" in Shapes must
    # not silently change what Draw produces, and a highlight colour must not
    # leak into the pen. EditPageWidget stays single-valued (one .color, one
    # .width_preset); the dialog is what pushes the ACTIVE tool's values onto
    # every page widget.
    _TOOL_COLOR_DEFAULTS = {"draw": "#ff0000", "shape": "#ff0000", "highlight": "#ffd43b", "marker": "#ffd43b"}
    _TOOL_WIDTH_DEFAULTS = {"draw": "medium", "shape": "medium", "marker": "medium"}
    # The amber is the web's own default highlight colour, so it must be
    # offer-able from the swatch row too, not just be the starting value.
    _PALETTE = ["#000000", "#ff0000", "#0000ff", "#00aa00", "#ffff00", "#ffd43b", "#ffffff"]

    def build_preview(self, container: QWidget) -> None:
        # Toolbar state first: the swatch rows below render their selected
        # state straight from it while they are being built.
        self._page_widgets: list[EditPageWidget] = []
        self._create_mode = "new_text"
        self._draw_tool = "pen"  # Draw's sub-tool: "pen" | "marker" (freehand highlighter)
        self._shape_type = "rectangle"
        self._filled = False
        self._tool_colors = dict(self._TOOL_COLOR_DEFAULTS)
        self._tool_widths = dict(self._TOOL_WIDTH_DEFAULTS)
        self._swatch_buttons: dict[str, list[tuple[str, QPushButton]]] = {}
        self._more_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ONE toolbar row: modes, undo/redo, arrange, clipboard, then the active
        # mode's own options. It scrolls sideways when the window is too narrow
        # rather than wrapping onto more rows and eating the page's room.
        self._toolbar_widget = QWidget()
        self._toolbar_widget.setObjectName("editToolbar")
        bar = QHBoxLayout(self._toolbar_widget)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        self._toolbar_scroll = QScrollArea()
        self._toolbar_scroll.setWidget(self._toolbar_widget)
        self._toolbar_scroll.setWidgetResizable(True)
        self._toolbar_scroll.setFrameShape(QFrame.NoFrame)
        self._toolbar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._toolbar_scroll.setFixedHeight(58)
        layout.addWidget(self._toolbar_scroll)

        # Same order and names as the web app's toolbar.
        self._mode_buttons: dict[str, QPushButton] = {}
        for mode, label, icon_name, attr in self._MODES:
            btn = QPushButton()
            btn.setObjectName("modeButton")
            btn.setCheckable(True)
            btn.setIcon(self._two_state_icon(icon_name))
            btn.setToolTip(label)
            btn.setAccessibleName(label)
            btn.clicked.connect(lambda _=False, m=mode: self._set_create_mode(m))
            setattr(self, attr, btn)
            self._mode_buttons[mode] = btn
            bar.addWidget(btn)
        self._refresh_mode_buttons()
        bar.addWidget(self._divider())

        self.undo_btn = self._toolbar_icon("arrow-u-up-left", "Undo", "Undo (Ctrl+Z)", lambda: self._toolbar_action("undo"))
        self.redo_btn = self._toolbar_icon("arrow-u-up-right", "Redo", "Redo (Ctrl+Y)", lambda: self._toolbar_action("redo"))
        bar.addWidget(self.undo_btn)
        bar.addWidget(self.redo_btn)

        self.arrange_btn = QPushButton("Arrange")
        self.arrange_btn.setIcon(QIcon(icon_pixmap("stack-simple", MUTED_FOREGROUND, 18)))
        self.arrange_btn.setToolTip("Bring the selected item forward or send it back")
        arrange_menu = QMenu(self.arrange_btn)
        for label, direction in (("Bring to Front", "front"), ("Forward", "forward"), ("Backward", "backward"), ("Send to Back", "back")):
            action = QAction(label, arrange_menu)
            action.triggered.connect(lambda _=False, d=direction: self._reorder_from_toolbar(d))
            arrange_menu.addAction(action)
        self.arrange_btn.setMenu(arrange_menu)
        bar.addWidget(self.arrange_btn)

        self.copy_btn = self._toolbar_icon("copy", "Copy", "Copy (Ctrl+C)", lambda: self._toolbar_action("copy"))
        self.cut_btn = self._toolbar_icon("scissors", "Cut", "Cut (Ctrl+X)", lambda: self._toolbar_action("cut"))
        self.paste_btn = self._toolbar_icon("clipboard-text", "Paste", "Paste (Ctrl+V)", lambda: self._toolbar_action("paste"))
        self.delete_btn = self._toolbar_icon("trash", "Delete", "Delete (Del)", lambda: self._toolbar_action("delete"))
        for btn in (self.copy_btn, self.cut_btn, self.paste_btn, self.delete_btn):
            bar.addWidget(btn)
        bar.addWidget(self._divider())

        self._draw_options = QWidget()
        draw_row = QHBoxLayout(self._draw_options)
        self.pen_btn = QPushButton("Pen")
        self.pen_btn.setCheckable(True)
        self.pen_btn.setChecked(True)
        self.pen_btn.clicked.connect(lambda: self._set_draw_tool("pen"))
        draw_row.addWidget(self.pen_btn)
        self.marker_btn = QPushButton("Highlighter")
        self.marker_btn.setCheckable(True)
        self.marker_btn.clicked.connect(lambda: self._set_draw_tool("marker"))
        draw_row.addWidget(self.marker_btn)
        self._pen_options = QWidget()
        pen_row = QHBoxLayout(self._pen_options)
        pen_row.setContentsMargins(0, 0, 0, 0)
        pen_row.addLayout(self._make_swatch_row("draw"))
        self.draw_width_combo = QComboBox()
        self.draw_width_combo.addItems(["thin", "medium", "thick"])
        self.draw_width_combo.setCurrentText(self._tool_widths["draw"])
        self.draw_width_combo.currentTextChanged.connect(lambda preset: self._set_tool_width("draw", preset))
        pen_row.addWidget(self.draw_width_combo)
        draw_row.addWidget(self._pen_options)
        self._marker_options = QWidget()
        marker_row = QHBoxLayout(self._marker_options)
        marker_row.setContentsMargins(0, 0, 0, 0)
        marker_row.addLayout(self._make_swatch_row("marker"))
        self.marker_width_combo = QComboBox()
        self.marker_width_combo.addItems(["thin", "medium", "thick"])
        self.marker_width_combo.setCurrentText(self._tool_widths["marker"])
        self.marker_width_combo.currentTextChanged.connect(lambda preset: self._set_tool_width("marker", preset))
        marker_row.addWidget(self.marker_width_combo)
        draw_row.addWidget(self._marker_options)
        self._marker_options.setVisible(False)
        bar.addWidget(self._draw_options)

        self._shapes_options = QWidget()
        shapes_row = QHBoxLayout(self._shapes_options)
        self.shape_type_combo = QComboBox()
        self.shape_type_combo.addItems(["rectangle", "ellipse", "line", "arrow"])
        self.shape_type_combo.currentTextChanged.connect(self._set_shape_type)
        shapes_row.addWidget(self.shape_type_combo)
        shapes_row.addLayout(self._make_swatch_row("shape"))
        self.shape_width_combo = QComboBox()
        self.shape_width_combo.addItems(["thin", "medium", "thick"])
        self.shape_width_combo.setCurrentText(self._tool_widths["shape"])
        self.shape_width_combo.currentTextChanged.connect(lambda preset: self._set_tool_width("shape", preset))
        shapes_row.addWidget(self.shape_width_combo)
        self.filled_checkbox = QCheckBox("Filled")
        self.filled_checkbox.toggled.connect(self._set_filled)
        shapes_row.addWidget(self.filled_checkbox)
        bar.addWidget(self._shapes_options)

        self._highlight_options = QWidget()
        highlight_row = QHBoxLayout(self._highlight_options)
        highlight_row.addLayout(self._make_swatch_row("highlight"))
        bar.addWidget(self._highlight_options)

        self._text_options = QWidget()
        text_row = QHBoxLayout(self._text_options)
        self.text_family_combo = QComboBox()
        self.text_family_combo.addItems(["helvetica", "times", "courier"])
        self.text_family_combo.currentTextChanged.connect(lambda text: self._apply_text_style(family=text))
        text_row.addWidget(self.text_family_combo)
        self.text_size_spin = QSpinBox()
        self.text_size_spin.setRange(4, 200)
        self.text_size_spin.setValue(12)
        # Typed digits must not apply (and refocus the editor) one at a time.
        self.text_size_spin.setKeyboardTracking(False)
        self.text_size_spin.valueChanged.connect(lambda value: self._apply_text_style(size=value))
        text_row.addWidget(self.text_size_spin)
        self.text_bold_btn = QPushButton("B")
        self.text_bold_btn.setCheckable(True)
        self.text_bold_btn.setFocusPolicy(Qt.NoFocus)
        self.text_bold_btn.clicked.connect(lambda checked: self._apply_text_style(bold=checked))
        text_row.addWidget(self.text_bold_btn)
        self.text_italic_btn = QPushButton("I")
        self.text_italic_btn.setCheckable(True)
        self.text_italic_btn.setFocusPolicy(Qt.NoFocus)
        self.text_italic_btn.clicked.connect(lambda checked: self._apply_text_style(italic=checked))
        text_row.addWidget(self.text_italic_btn)
        self.text_revert_btn = QPushButton("Revert")
        self.text_revert_btn.setFocusPolicy(Qt.NoFocus)
        self.text_revert_btn.clicked.connect(self._revert_open_run)
        text_row.addWidget(self.text_revert_btn)
        bar.addWidget(self._text_options)

        self._width_combos = {"draw": self.draw_width_combo, "shape": self.shape_width_combo, "marker": self.marker_width_combo}

        self._draw_options.setVisible(False)
        self._shapes_options.setVisible(False)
        self._highlight_options.setVisible(False)
        self._text_options.setVisible(False)

        bar.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        self.model = EditElementsModel()
        self.model.on_change.append(self._refresh_toolbar_state)
        self._refresh_toolbar_state()
        self._input_path: str | None = None

        for keys, action in (
            ("Ctrl+Z", "undo"), ("Ctrl+Y", "redo"),
            ("Ctrl+C", "copy"), ("Ctrl+X", "cut"), ("Ctrl+V", "paste"),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda a=action: self._handle_shortcut(a))

    # (mode key, tooltip / label, icon, attribute) in the web toolbar's order.
    _MODES = (
        ("select", "Select", "cursor", "select_btn"),
        ("text", "Edit Text", "cursor-text", "edit_text_btn"),
        ("draw", "Draw", "pencil-simple", "draw_btn"),
        ("shape", "Shapes", "rectangle", "shapes_btn"),
        ("highlight", "Highlight", "highlighter", "highlight_btn"),
        ("image", "Insert Image", "image-square", "image_btn"),
        ("new_text", "Add Text", "text-aa", "new_text_btn"),
        ("eraser", "Eraser", "eraser", "eraser_btn"),
    )

    @staticmethod
    def _two_state_icon(name: str) -> QIcon:
        """Muted when idle, white on the accent fill when the mode is active."""
        icon = QIcon()
        icon.addPixmap(icon_pixmap(name, MUTED_FOREGROUND, 18), QIcon.Normal, QIcon.Off)
        icon.addPixmap(icon_pixmap(name, "#ffffff", 18), QIcon.Normal, QIcon.On)
        return icon

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setObjectName("toolbarDivider")
        line.setFixedSize(1, 24)
        return line

    def _toolbar_icon(self, icon_name: str, name: str, tooltip: str, on_click) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("toolbarIcon")
        btn.setIcon(QIcon(icon_pixmap(icon_name, MUTED_FOREGROUND, 18)))
        btn.setToolTip(tooltip)
        btn.setAccessibleName(name)
        btn.setFocusPolicy(Qt.NoFocus)  # a click must not steal keys from the page
        btn.clicked.connect(lambda _=False: on_click())
        return btn

    def _refresh_mode_buttons(self) -> None:
        """Only the active mode shows its name; the rest are icon-only."""
        labels = {mode: label for mode, label, _icon, _attr in self._MODES}
        for mode, btn in self._mode_buttons.items():
            active = mode == self._create_mode
            btn.setChecked(active)
            btn.setText(labels[mode] if active else "")

    def _refresh_toolbar_state(self) -> None:
        """Greys out what can't act right now (nothing to undo, nothing selected)."""
        model = self.model
        has_selection = model.has_selected_element
        self.undo_btn.setEnabled(model.can_undo)
        self.redo_btn.setEnabled(model.can_redo)
        self.arrange_btn.setEnabled(has_selection)
        self.copy_btn.setEnabled(has_selection)
        self.cut_btn.setEnabled(has_selection)
        self.paste_btn.setEnabled(model.can_paste)
        self.delete_btn.setEnabled(has_selection or bool(model.selected_ids))

    def _make_swatch_row(self, tool: str) -> QHBoxLayout:
        """Builds one tool's colour palette row. Each row writes to - and
        shows its selected state from - only its OWN tool's colour."""
        row = QHBoxLayout()
        buttons: list[tuple[str, QPushButton]] = []
        for hex_color in self._PALETTE:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.clicked.connect(lambda _, c=hex_color, t=tool: self._set_tool_color(t, c))
            row.addWidget(btn)
            buttons.append((hex_color, btn))
        self._swatch_buttons[tool] = buttons
        more = QPushButton("More...")
        more.setFixedHeight(20)
        more.setToolTip("Pick any colour")
        more.clicked.connect(lambda _=False, t=tool: self._pick_custom_color(t))
        row.addWidget(more)
        self._more_buttons[tool] = more
        self._refresh_swatch_row(tool)
        return row

    def _get_color_dialog(self, initial: str):
        """The one place the modal colour dialog opens (tests replace it)."""
        return QColorDialog.getColor(QColor(initial), self, "Choose colour")

    def _pick_custom_color(self, tool: str) -> None:
        picked = self._get_color_dialog(self._tool_colors[tool])
        if picked is None or not isinstance(picked, QColor) or not picked.isValid():
            return
        self._set_tool_color(tool, picked.name(QColor.HexRgb).lower())

    def _refresh_swatch_row(self, tool: str) -> None:
        """A swatch is a bare coloured square, so its BORDER is the only
        place a selected state can show - without this the row gives no
        feedback at all about which colour the tool is actually using."""
        for hex_color, btn in self._swatch_buttons[tool]:
            selected = hex_color == self._tool_colors[tool]
            border = "3px solid #1971c2" if selected else "1px solid #888"
            btn.setStyleSheet(f"background-color: {hex_color}; border: {border};")
        more = self._more_buttons.get(tool)
        if more is not None:
            current = self._tool_colors[tool]
            if current in self._PALETTE:
                more.setStyleSheet("border: 1px solid #888;")
            else:
                # Custom colour: the More button is the selected one and wears it.
                text = "#000000" if QColor(current).lightness() > 128 else "#ffffff"
                more.setStyleSheet(f"background-color: {current}; color: {text}; border: 3px solid #1971c2;")

    def _widget_create_mode(self) -> str:
        """"draw" is this toolbar's label for the stroke tool -
        EditPageWidget's own create_mode value is "stroke" (matching the
        element type name), not "draw". Both the mode-switch path and the
        build-a-new-page path go through here so they can never disagree."""
        return "stroke" if self._create_mode == "draw" else self._create_mode

    def _active_style_tool(self) -> str | None:
        """Which markup tool's colour/width the page widgets should carry
        right now, or None in the two modes (new_text, image) that draw no
        markup at all and so leave the widgets' values untouched. Draw's
        Highlighter sub-tool is its own tool ("marker") with its own colour."""
        if self._create_mode == "draw" and self._draw_tool == "marker":
            return "marker"
        return self._create_mode if self._create_mode in self._tool_colors else None

    def _apply_style_to(self, widget) -> None:
        widget.shape_type = self._shape_type
        widget.filled = self._filled
        widget.draw_tool = self._draw_tool
        widget.marker_color = self._tool_colors["marker"]
        widget.marker_width_preset = self._tool_widths["marker"]
        tool = self._active_style_tool()
        if tool is None or tool == "marker":
            return
        widget.color = self._tool_colors[tool]
        if tool in self._tool_widths:  # the highlight tool has no width
            widget.width_preset = self._tool_widths[tool]

    def _push_style_to_widgets(self) -> None:
        for widget in self._page_widgets:
            self._apply_style_to(widget)

    def _set_draw_tool(self, tool: str) -> None:
        self._draw_tool = tool
        self.pen_btn.setChecked(tool == "pen")
        self.marker_btn.setChecked(tool == "marker")
        self._pen_options.setVisible(tool == "pen")
        self._marker_options.setVisible(tool == "marker")
        self._push_style_to_widgets()

    def _set_create_mode(self, mode: str) -> None:
        self._commit_open_editors()
        # A selection made in one tool means nothing in another (drawings are
        # only selectable with the Select tool), so switching drops it.
        self.model.clear_selection()
        self._create_mode = mode
        self._refresh_mode_buttons()
        self._text_options.setVisible(mode == "text")
        self._draw_options.setVisible(mode == "draw")
        self._shapes_options.setVisible(mode == "shape")
        self._highlight_options.setVisible(mode == "highlight")
        widget_mode = self._widget_create_mode()
        for widget in self._page_widgets:
            widget.create_mode = widget_mode
        # Switching tool is what swaps the newly-active tool's own colour
        # and width onto the page widgets, which keep one value each.
        self._push_style_to_widgets()

    def _set_shape_type(self, shape_type: str) -> None:
        self._shape_type = shape_type
        if self.shape_type_combo.currentText() != shape_type:
            self.shape_type_combo.blockSignals(True)
            self.shape_type_combo.setCurrentText(shape_type)
            self.shape_type_combo.blockSignals(False)
        for widget in self._page_widgets:
            widget.shape_type = shape_type

    def _set_tool_color(self, tool: str, color: str) -> None:
        self._tool_colors[tool] = color
        self._refresh_swatch_row(tool)
        if self._active_style_tool() == tool:
            self._push_style_to_widgets()

    def _set_tool_width(self, tool: str, preset: str) -> None:
        self._tool_widths[tool] = preset
        combo = self._width_combos[tool]
        if combo.currentText() != preset:
            combo.blockSignals(True)
            combo.setCurrentText(preset)
            combo.blockSignals(False)
        if self._active_style_tool() == tool:
            self._push_style_to_widgets()

    def _set_color(self, color: str) -> None:
        """Sets the ACTIVE tool's colour (the tool is taken from the current
        create mode rather than passed in, so the toolbar's own rows and any
        caller that predates per-tool state mean the same thing). In a mode
        with no markup tool of its own, the pen ("draw") is the sensible
        target: it is what the next Draw click will use."""
        self._set_tool_color(self._active_style_tool() or "draw", color)

    def _set_width_preset(self, preset: str) -> None:
        """Sets the ACTIVE tool's stroke width - see _set_color. Highlight
        has no width of its own, so it falls back to the pen too."""
        tool = self._active_style_tool()
        self._set_tool_width(tool if tool in self._tool_widths else "draw", preset)

    def _set_filled(self, filled: bool) -> None:
        self._filled = filled
        if self.filled_checkbox.isChecked() != filled:
            self.filled_checkbox.blockSignals(True)
            self.filled_checkbox.setChecked(filled)
            self.filled_checkbox.blockSignals(False)
        for widget in self._page_widgets:
            widget.filled = filled

    def _commit_open_editors(self) -> None:
        for widget in self._page_widgets:
            widget.commit_open_editors()

    def _commit_open_editors_except(self, keep) -> None:
        for widget in self._page_widgets:
            if widget is not keep:
                widget.commit_open_editors()

    def _toolbar_action(self, action: str) -> None:
        """A toolbar CLICK (unlike a keyboard shortcut, whose keystroke
        belongs to an open text editor) finishes any open editor first so the
        click acts on the committed state."""
        self._commit_open_editors()
        self._handle_shortcut(action)

    def _reorder_from_toolbar(self, direction: str) -> None:
        self._commit_open_editors()
        self._reorder_selected(direction)

    def _open_run_widget(self):
        return next((w for w in self._page_widgets if w._run_editor is not None), None)

    def _apply_text_style(self, **patch) -> None:
        widget = self._open_run_widget()
        if widget is not None:
            widget.apply_run_style(**patch)

    def _revert_open_run(self) -> None:
        widget = self._open_run_widget()
        if widget is not None:
            widget.revert_run_editor()
            self._sync_text_style_row()

    def _sync_text_style_row(self) -> None:
        """Shows the style at the open run editor's cursor in the row's
        controls (signals blocked so reading state never writes it back)."""
        widget = self._open_run_widget()
        state = widget.run_editor_state() if widget is not None else None
        if state is None:
            return
        controls = (self.text_family_combo, self.text_size_spin, self.text_bold_btn, self.text_italic_btn)
        for control in controls:
            control.blockSignals(True)
        self.text_family_combo.setCurrentText(state["family"])
        self.text_size_spin.setValue(int(round(state["size"])))
        self.text_bold_btn.setChecked(state["bold"])
        self.text_italic_btn.setChecked(state["italic"])
        for control in controls:
            control.blockSignals(False)

    def _prompt_for_image(self, widget, point: tuple[float, float]) -> None:
        # Takes the page WIDGET, not a page number: self._page_widgets is
        # not guaranteed to line up 1:1 with page numbers (on_files_changed
        # skips any page whose thumbnail fails to render), so an index
        # lookup could raise IndexError or silently target the wrong page.
        path, _ = QFileDialog.getOpenFileName(self, "Select image", "", "Image files (*.png *.jpg *.jpeg)")
        if not path:
            return
        widget.create_image_at(point[0], point[1], path)

    def _any_text_editor_open(self) -> bool:
        """Every model-level keyboard action (shortcuts AND arrow-key
        nudge) must be suppressed while ANY page's QTextEdit overlay is
        open for editing - e.g. Ctrl+C or Delete must edit the TEXT, not
        the model, matching the web's own "any text-input-like element
        has focus" suppression rule. Deliberately checks "is an editor
        currently open" rather than each editor's own .hasFocus() -
        confirmed empirically that QTextEdit.hasFocus() is unreliable
        under QT_QPA_PLATFORM=offscreen even after an explicit .show()/
        .setFocus() (real window activation never happens without a
        genuine event loop), so it's not a trustworthy signal in tests OR
        in the same code path this app already runs under for CI. "Open"
        is also the semantically right check for the real running app.
        Toolbar clicks do not rely on focus-out: they commit any open
        editor explicitly through _toolbar_action before acting, so this
        check only matters for keyboard shortcuts pressed while still
        actively typing. It must consider both _text_editor (new_text)
        and _run_editor (run editing). Centralized here so both
        _handle_shortcut and keyPressEvent share one check."""
        return any(w._text_editor is not None or w._run_editor is not None for w in self._page_widgets)

    def _handle_shortcut(self, action: str) -> None:
        if self._any_text_editor_open():
            return
        if action == "undo":
            self.model.undo()
        elif action == "redo":
            self.model.redo()
        elif action == "copy":
            self.model.copy()
        elif action == "cut":
            self.model.cut()
        elif action == "paste":
            self.model.paste()
        elif action == "delete":
            if self.model.selected_ids:
                self.model.delete_selected_group()
            elif self.model.selected_id is not None:
                self.model.remove(self.model.selected_id)

    def _reorder_selected(self, direction: str) -> None:
        if self.model.selected_id is not None:
            self.model.reorder(self.model.selected_id, direction)

    def keyPressEvent(self, e) -> None:
        arrow_deltas = {
            Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
            Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1),
        }
        if e.key() == Qt.Key_Escape and not self._any_text_editor_open() and (self.model.selected_ids or self.model.selected_id):
            self.model.clear_selection()  # Esc deselects, like the web app; it must not close a stand-alone dialog
            e.accept()
            return
        if e.key() in arrow_deltas and not self._any_text_editor_open() and self.model.selected_ids:
            step = 0.02 if e.modifiers() & Qt.ShiftModifier else 0.004
            dx, dy = arrow_deltas[e.key()]
            self.model.nudge_group(dx * step, dy * step)
            e.accept()
            return
        if e.key() in arrow_deltas and not self._any_text_editor_open() and self.model.selected_id is not None:
            step = 0.02 if e.modifiers() & Qt.ShiftModifier else 0.004
            dx, dy = arrow_deltas[e.key()]
            self.model.nudge(self.model.selected_id, dx * step, dy * step)
            e.accept()
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and not self._any_text_editor_open():
            self._handle_shortcut("delete")
            e.accept()
            return
        super().keyPressEvent(e)

    def on_files_changed(self, paths: list[str]) -> None:
        # Close any open editors on the outgoing widgets cleanly (the model
        # is replaced below, so this only guarantees nothing is left dangling).
        self._commit_open_editors()
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._page_widgets = []
        self.model.remove_listener(self._refresh_toolbar_state)
        self.model = EditElementsModel()
        self.model.on_change.append(self._refresh_toolbar_state)
        self._refresh_toolbar_state()
        self._input_path = paths[0] if paths else None
        if self._input_path is None:
            return
        try:
            count = get_page_count(self._input_path)
        except PDFError:
            return
        for page_num in range(1, count + 1):
            try:
                thumb_bytes = render_page_thumbnail(self._input_path, page_num, max_size=450)
            except PDFError:
                continue
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            try:
                runs = extract_text_runs(self._input_path, page_num)
                width_pt, height_pt = get_page_size(self._input_path, page_num)
                rotation = get_page_rotation(self._input_path, page_num)
            except PDFError:
                runs, width_pt, height_pt, rotation = [], 0.0, 0.0, 0
            self.model.set_page_text_info(page_num, runs, rotation, width_pt, height_pt)
            widget = EditPageWidget(self.model, page_num)
            widget.run_editor_cursor_moved.connect(self._sync_text_style_row)
            # The callback closes over the WIDGET itself rather than a page
            # number, so it can never index into the wrong page's widget.
            widget.commit_other_editors = lambda w=widget: self._commit_open_editors_except(w)
            widget.on_image_click = lambda point, wgt=widget: self._prompt_for_image(wgt, point)
            # A freshly built page must honour whichever toolbar mode and
            # tool settings are currently in force, not EditPageWidget's own
            # "new_text"/red/medium defaults - otherwise loading a file while
            # "Insert Image" is selected silently reverts the new pages to
            # text mode.
            widget.create_mode = self._widget_create_mode()
            self._apply_style_to(widget)
            # addWidget (reparenting) BEFORE set_page_pixmap: keeps the
            # widget a real child of a shown container from the moment it
            # exists, rather than sitting unparented in between.
            self._container_layout.addWidget(widget)
            widget.set_page_pixmap(pixmap)
            self._page_widgets.append(widget)

    def gather_params(self) -> dict:
        # Commit a typed draft when Run is clicked without clicking the page.
        self._commit_open_editors()
        elements = [{k: v for k, v in el.items() if k != "id"} for el in self.model.elements]
        image_paths = {el["file_id"]: el["file_id"] for el in elements if el["type"] == "image"}
        return {"elements": elements, "image_paths": image_paths}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_edited.pdf"))
        edit_pdf(input_path, out_path, params["elements"], params["image_paths"])
        return [out_path]
