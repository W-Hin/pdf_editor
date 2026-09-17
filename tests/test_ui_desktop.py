import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.pdf_ops import crop_pdf, render_page_thumbnail
from app.ui.widgets import RectangleOverlayWidget, box_to_insets, insets_to_box

_app = QApplication.instance() or QApplication([])


def test_single_mode_drag_creates_one_box():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert widget.single_box() == {"x0": 0.1, "y0": 0.1, "x1": 0.75, "y1": 0.8}


def test_single_mode_second_drag_replaces_the_box():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    # Deliberately NOT QPoint(0, 0) here: Qt/QTest treats a literal (0,0)
    # position as "unspecified" and substitutes the widget's center instead
    # (the exact gotcha you found) - QPoint(2, 1) is close to the corner
    # without tripping it.
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(2, 1))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    assert len(widget.boxes) == 1
    assert widget.single_box() == {"x0": 0.01, "y0": 0.01, "x1": 0.2, "y1": 0.4}


def test_drag_below_min_fraction_is_ignored():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(21, 11))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(21, 11))
    assert widget.boxes == []


def test_multi_mode_two_boxes_then_remove_one_via_its_marker():
    widget = RectangleOverlayWidget(multi=True)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(10, 60))
    QTest.mouseMove(widget, QPoint(60, 90))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(60, 90))
    assert len(widget.boxes) == 2

    first_box = widget.boxes[0]
    marker = widget._marker_rect(first_box)
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)

    assert len(widget.boxes) == 1
    assert widget.boxes[0] == {"x0": 0.05, "y0": 0.6, "x1": 0.3, "y1": 0.9}


def test_box_to_insets_and_back_round_trip():
    # 0.25/0.75 chosen deliberately: both are exact in IEEE-754 binary
    # floating point, so `1 - 0.75 == 0.25` exactly - unlike `1 - 0.7`
    # (0.30000000000000004), which is the float-precision issue you found.
    box = {"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75}
    insets = box_to_insets(box)
    assert insets == {"top": 0.25, "left": 0.25, "right": 0.25, "bottom": 0.25}
    assert insets_to_box(insets) == box


def test_crop_dialog_offscreen_end_to_end(tmp_path):
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "REMOVE THIS")
    page.insert_text((72, 700), "KEEP THIS")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(input_path)])
    w, h = dlg.overlay.width(), dlg.overlay.height()
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
    QTest.mouseMove(dlg.overlay, QPoint(int(w * 0.6), int(h * 0.15)))
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    params = dlg.gather_params()
    assert params["box"] is not None
    output_paths = dlg.run_operation([str(input_path)], params)

    result = fitz.open(output_paths[0])
    text = result[0].get_text()
    result.close()
    # This drag keeps only a thin strip near the TOP of the page (y-fraction
    # 0.05 to 0.15) - "REMOVE THIS" sits there (inserted at y=72 on an 842pt
    # page) and survives the crop; "KEEP THIS" (inserted at y=700, near the
    # bottom) is cropped away entirely along with the rest of the page below
    # the kept strip. Verified empirically against this exact fixture before
    # this plan was written - the fixture's own naming ("REMOVE THIS") refers
    # to the Redact tests' convention (Task 2), not this crop test's outcome.
    assert "REMOVE THIS" in text
    assert "KEEP THIS" not in text


def test_crop_dialog_raises_when_no_box_drawn(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Some text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(input_path)])
    params = dlg.gather_params()
    assert params["box"] is None
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError as exc:
        assert "crop area" in str(exc)


def test_compress_dialog_still_builds_its_thumbnail_strip():
    from app.ui.dialogs.optimize_dialogs import CompressDialog

    dlg = CompressDialog()
    assert hasattr(dlg, "thumbnail_strip")
    assert hasattr(dlg, "_thumbnail_layout")
    assert dlg.quality_slider.value() == 60
