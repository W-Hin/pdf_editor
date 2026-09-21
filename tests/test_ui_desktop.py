import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QTextCharFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton, QTextEdit

from app.core.pdf_ops import crop_pdf, extract_form_fields, render_page_thumbnail
from app.ui.edit_canvas import EditElementsModel, EditPageWidget
from app.ui.widgets import DiffPreviewWidget, FormFieldsWidget, RectangleOverlayWidget, SignaturePadWidget, box_to_insets, insets_to_box

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
    # (a well-known QTest gotcha, confirmed empirically before this test was
    # written) - QPoint(2, 1) is close to the corner without tripping it.
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
    # (0.30000000000000004), a known IEEE-754 float-precision issue
    # confirmed empirically before this test was written.
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


def test_crop_dialog_drag_propagates_the_box_to_every_read_only_mirror(tmp_path):
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    for i in range(3):
        doc.new_page(width=595, height=842).insert_text((72, 72), f"PAGE {i + 1}")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(input_path)])
    assert len(dlg._mirrors) == 2  # pages 2 and 3

    w, h = dlg.overlay.width(), dlg.overlay.height()
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
    QTest.mouseMove(dlg.overlay, QPoint(int(w * 0.6), int(h * 0.15)))
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    box = dlg.overlay.single_box()
    assert box is not None
    for mirror in dlg._mirrors:
        assert mirror.single_box() == box
        # Mirrors must ignore direct interaction too.
        QTest.mousePress(mirror, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        QTest.mouseRelease(mirror, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        assert mirror.single_box() == box  # unchanged by the click


def test_crop_dialog_rebuilds_mirrors_on_file_change(tmp_path):
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    single_page_path = tmp_path / "single.pdf"
    doc.save(str(single_page_path))
    doc.close()

    doc2 = fitz.open()
    for _ in range(3):
        doc2.new_page(width=595, height=842)
    multi_page_path = tmp_path / "multi.pdf"
    doc2.save(str(multi_page_path))
    doc2.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(multi_page_path)])
    assert len(dlg._mirrors) == 2

    dlg.on_files_changed([str(single_page_path)])
    assert dlg._mirrors == []


def test_compress_dialog_still_builds_its_thumbnail_strip():
    from app.ui.dialogs.optimize_dialogs import CompressDialog

    dlg = CompressDialog()
    assert hasattr(dlg, "thumbnail_strip")
    assert hasattr(dlg, "_thumbnail_layout")
    assert dlg.quality_slider.value() == 60


def test_redact_dialog_each_page_holds_its_own_boxes_independently(tmp_path):
    from app.ui.dialogs.edit_dialogs import RedactDialog

    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 72), "PAGE ONE SECRET")
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 72), "PAGE TWO SECRET")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = RedactDialog()
    dlg.on_files_changed([str(input_path)])
    assert len(dlg._page_widgets) == 2

    def draw_box(overlay):
        w, h = overlay.width(), overlay.height()
        QTest.mousePress(overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
        QTest.mouseMove(overlay, QPoint(int(w * 0.6), int(h * 0.15)))
        QTest.mouseRelease(overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    draw_box(dlg._page_widgets[1])  # page 2 only

    params = dlg.gather_params()
    # The drag's pixel positions map to page fractions of whatever size the page
    # is shown at (pages now fit the window rather than a fixed 450px thumbnail).
    page2 = dlg._page_widgets[1]
    w, h = page2.width(), page2.height()
    x0, y0, x1, y1 = int(w * 0.1) / w, int(h * 0.05) / h, int(w * 0.6) / w, int(h * 0.15) / h
    assert params["redactions"] == [{
        "page": 2,
        "top": pytest.approx(y0),
        "left": pytest.approx(x0),
        "right": pytest.approx(1 - x1),
        "bottom": pytest.approx(1 - y1),
    }]

    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    text_p1 = result[0].get_text()
    text_p2 = result[1].get_text()
    result.close()
    assert "PAGE ONE SECRET" in text_p1  # untouched
    assert "PAGE TWO SECRET" not in text_p2  # redacted

    # Removing page 2's box via its own widget's marker works independently
    # of every other page's widget.
    page2_widget = dlg._page_widgets[1]
    marker = page2_widget._marker_rect(page2_widget.boxes[0])
    click = marker.center()
    QTest.mousePress(page2_widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page2_widget, Qt.LeftButton, Qt.NoModifier, click)
    assert page2_widget.boxes == []
    assert dlg.gather_params()["redactions"] == []


def test_redact_dialog_page_numbering_survives_a_mid_document_render_failure(tmp_path, monkeypatch):
    from app.core.errors import PDFError
    from app.core.pdf_ops import render_page_thumbnail as real_render_page_thumbnail
    from app.ui.dialogs import edit_dialogs
    from app.ui.dialogs.edit_dialogs import RedactDialog

    doc = fitz.open()
    for i in range(4):
        doc.new_page(width=595, height=842).insert_text((72, 72), f"PAGE {i + 1} SECRET")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    def flaky_render(path, page_num, max_size=100):
        if page_num == 3:
            raise PDFError("simulated render failure for page 3")
        return real_render_page_thumbnail(path, page_num, max_size=max_size)

    # This codebase's tests patch collaborators with pytest's `monkeypatch`
    # fixture (see tests/test_vendor_ocr_binaries.py, tests/web/conftest.py)
    # rather than unittest.mock; we follow that convention here. Wrapping the
    # real render_page_thumbnail is the cleanest way to make it fail for
    # exactly one interior page while succeeding for its neighbors on a real
    # fixture.
    monkeypatch.setattr(edit_dialogs, "render_page_thumbnail", flaky_render)

    dlg = RedactDialog()
    dlg.on_files_changed([str(input_path)])

    assert len(dlg._page_widgets) == 4
    # Page 3's picture failed to render: it is kept as a blank page (so the
    # numbering can never shift), not dropped.
    assert dlg._page_widgets[2] is not None and not dlg._page_widgets[2].has_pixmap

    # Draw a box on page 4's widget (0-indexed slot 3) - it must be reported
    # as page 4, not silently relabeled as page 3 because page 3's slot is
    # None instead of missing entirely.
    page4_widget = dlg._page_widgets[3]
    w, h = page4_widget.width(), page4_widget.height()
    QTest.mousePress(page4_widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
    QTest.mouseMove(page4_widget, QPoint(int(w * 0.6), int(h * 0.15)))
    QTest.mouseRelease(page4_widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    params = dlg.gather_params()
    assert len(params["redactions"]) == 1
    assert params["redactions"][0]["page"] == 4


def test_signature_pad_starts_blank():
    pad = SignaturePadWidget()
    assert pad.has_drawing() is False


def test_signature_pad_drawing_sets_has_drawing_and_produces_real_pixels(tmp_path):
    pad = SignaturePadWidget()
    QTest.mousePress(pad, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20))
    QTest.mouseMove(pad, QPoint(100, 100))
    QTest.mouseMove(pad, QPoint(200, 50))
    QTest.mouseRelease(pad, Qt.LeftButton, Qt.NoModifier, QPoint(200, 50))
    assert pad.has_drawing() is True

    png_path = str(tmp_path / "sig.png")
    pad.save_png(png_path)
    saved = QImage(png_path)
    assert (saved.width(), saved.height()) == (400, 150)

    # A pixel on the drawn stroke's path is dark; a corner nowhere near any
    # stroke is untouched white - confirmed empirically against this exact
    # drag before this test was written (a real drawn pixel was found by
    # scanning the whole image; corner (390, 5) was picked as clearly
    # outside the (20,20)-(100,100)-(200,50) stroke path).
    found_dark_pixel = any(
        saved.pixelColor(x, y).red() < 100
        for x in range(0, 400, 2)
        for y in range(0, 150, 2)
    )
    assert found_dark_pixel
    corner = saved.pixelColor(390, 5)
    assert corner.red() > 240 and corner.green() > 240 and corner.blue() > 240


def test_signature_pad_clear_resets_has_drawing():
    pad = SignaturePadWidget()
    QTest.mousePress(pad, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20))
    QTest.mouseRelease(pad, Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
    assert pad.has_drawing() is True
    pad.clear()
    assert pad.has_drawing() is False


from app.ui.widgets import ImagePlacementWidget


def _make_placement_widget():
    widget = ImagePlacementWidget()
    page_pixmap = QPixmap(424, 600)
    page_pixmap.fill(Qt.white)
    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    widget.set_page_pixmap(page_pixmap)
    widget.set_signature_pixmap(sig_pixmap)
    return widget


def test_empty_space_click_creates_a_placement_with_default_sizing():
    widget = _make_placement_widget()
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.5), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert len(widget.placements) == 1
    p = widget.placements[0]
    # Verified empirically before this test was written: a 200x80 signature
    # (aspect 0.4) at the default width fraction 0.25 gives height 0.1
    # (0.25 * 0.4), centered on the click point (0.5, 0.3) and unclamped
    # since it's well away from every edge.
    assert p == {"x": 0.375, "y": 0.25, "width": 0.25, "height": 0.1}


def test_marker_and_handle_rects_do_not_overlap_for_a_default_sized_placement():
    widget = _make_placement_widget()
    p = {"x": 0.375, "y": 0.25, "width": 0.25, "height": 0.1}
    marker = widget._marker_rect(p)
    handle = widget._handle_rect(p)
    assert not marker.intersects(handle)


def test_marker_and_handle_rects_do_not_overlap_for_a_short_wide_signature():
    # A 5:1-aspect signature (a common cropped scan) at the default width
    # fraction on this ~450px-tall page preview renders under 28px tall -
    # confirmed empirically to be the case that made the OLD fixed-14px
    # marker/handle rects overlap (marker always won the hit-test, so a
    # click meant for the handle deleted the placement instead of resizing
    # it). This is the exact scenario Finding 1 describes.
    widget = ImagePlacementWidget()
    page_pixmap = QPixmap(318, 450)
    page_pixmap.fill(Qt.white)
    sig_pixmap = QPixmap(500, 100)  # 5:1 aspect
    sig_pixmap.fill(Qt.blue)
    widget.set_page_pixmap(page_pixmap)
    widget.set_signature_pixmap(sig_pixmap)

    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.5), int(h * 0.5))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert len(widget.placements) == 1
    p = widget.placements[0]
    rect = widget._placement_rect_px(p)
    assert rect.height() < 28  # confirms this actually hits the extreme case

    marker = widget._marker_rect(p)
    handle = widget._handle_rect(p)
    assert not marker.intersects(handle)

    # Clicking dead-center on the resize handle must actually start a
    # resize, not fall through to the marker's delete - this is the part
    # that regresses silently if only the static-rect overlap is checked.
    hx, hy = handle.center().x(), handle.center().y()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx, hy))
    assert widget._drag is not None
    assert widget._drag["mode"] == "resize"
    assert len(widget.placements) == 1  # not deleted
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx, hy))


def test_clicking_a_placements_body_moves_it():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.375, "y": 0.25, "width": 0.25, "height": 0.1}])
    w, h = widget.width(), widget.height()
    rect = widget._placement_rect_px(widget.placements[0])
    body = QPoint(rect.left() + rect.width() // 2, rect.top() + rect.height() // 2)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 20, body.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 20, body.y() + 10))
    p = widget.placements[0]
    # Verified empirically: moving by (20, 10) pixels on this exact 424x600
    # widget shifts the fraction position by (20/424, 10/600), unclamped.
    assert p["x"] == pytest.approx(0.4221698113207547)
    assert p["y"] == pytest.approx(0.26666666666666666)
    assert p["width"] == pytest.approx(0.25)  # unchanged by a move
    assert p["height"] == pytest.approx(0.1)


def test_clicking_a_placements_handle_resizes_it_aspect_locked():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.4221698113207547, "y": 0.26666666666666666, "width": 0.25, "height": 0.1}])
    p = widget.placements[0]
    handle = widget._handle_rect(p)
    hx, hy = handle.center().x(), handle.center().y()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx, hy))
    QTest.mouseMove(widget, QPoint(hx + 30, hy + 30))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx + 30, hy + 30))
    resized = widget.placements[0]
    # Verified empirically: dragging the handle +30px horizontally widens
    # the box by 30/424 of the page width, and height follows the locked
    # aspect ratio (0.1/0.25 = 0.4) - not the vertical drag distance at all.
    assert resized["width"] == pytest.approx(0.32075471698113206)
    assert resized["height"] == pytest.approx(0.12830188679245283)


def test_clicking_a_placements_marker_removes_it():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.4221698113207547, "y": 0.26666666666666666, "width": 0.3207547169811321, "height": 0.12830188679245286}])
    marker = widget._marker_rect(widget.placements[0])
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert widget.placements == []


def test_resize_past_the_page_edge_clamps_to_the_available_space():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.6, "y": 0.6, "width": 0.25, "height": 0.1}])
    p = widget.placements[0]
    handle = widget._handle_rect(p)
    hx, hy = handle.center().x(), handle.center().y()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx, hy))
    QTest.mouseMove(widget, QPoint(hx + 500, hy + 500))  # a drag far past any edge
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx + 500, hy + 500))
    resized = widget.placements[0]
    # Verified empirically: at x=0.6, the widthCap (1 - x = 0.4) binds before
    # the raw dragged-width would, so width clamps to exactly 0.4 and height
    # follows the same 0.1/0.25=0.4 aspect ratio (0.4 * 0.4 = 0.16) - not
    # some other value influenced by the vertical drag distance.
    assert resized["width"] == pytest.approx(0.4)
    assert resized["height"] == pytest.approx(0.16)
    assert resized["x"] + resized["width"] <= 1.0 + 1e-9
    assert resized["y"] + resized["height"] <= 1.0 + 1e-9


def test_overlapping_placements_hit_test_the_topmost_last_drawn_one():
    # paintEvent draws self.placements in forward order, so the LAST entry
    # paints on top. Hit-testing must therefore also prefer the last entry
    # on an overlap - clicking should hit what's visually on top, not
    # whichever placement happens to be first in the list.
    widget = _make_placement_widget()
    bottom = {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
    top = {"x": 0.15, "y": 0.15, "width": 0.5, "height": 0.5}
    widget.set_placements([bottom, top])

    overlap_rect = widget._placement_rect_px(top)
    body = QPoint(overlap_rect.left() + 5, overlap_rect.top() + 5)  # inside both bodies
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    assert widget._drag is not None
    assert widget._drag["index"] == 1  # the topmost (last-drawn) placement, not index 0
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, body)


def test_sign_dialog_places_a_signature_and_exports_it(tmp_path):
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_text((72, 72), "Original page text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "signature.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = SignDialog()
    dlg.use_signature_file(sig_path)  # bypasses the draw/upload UI, sets signature_path + natural size directly
    dlg.on_files_changed([str(input_path)])

    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    assert len(page1.placements) == 1

    params = dlg.gather_params()
    assert params["signature_path"] == sig_path
    assert len(params["placements"]) == 1
    assert params["placements"][0]["page"] == 1

    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    page = result[0]
    images = page.get_images()
    assert len(images) == 1
    result.close()


def test_sign_dialog_use_different_signature_clears_the_overlays_placements(tmp_path):
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "signature.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = SignDialog()
    dlg.use_signature_file(sig_path)
    dlg.on_files_changed([str(input_path)])

    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    assert len(page1.placements) == 1

    # Switching to a different signature must discard every per-page widget
    # entirely, not just clear their placements - there's no valid page
    # widget to show until a new signature + file combination exists again.
    dlg._use_different_signature()
    assert dlg._page_widgets == []


def test_sign_dialog_each_page_holds_its_own_placements_independently(tmp_path):
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "signature.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = SignDialog()
    dlg.use_signature_file(sig_path)
    dlg.on_files_changed([str(input_path)])
    assert len(dlg._page_widgets) == 3

    def place(widget):
        w, h = widget.width(), widget.height()
        click = QPoint(int(w * 0.6), int(h * 0.7))
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)

    place(dlg._page_widgets[0])  # page 1
    place(dlg._page_widgets[2])  # page 3
    assert len(dlg._page_widgets[0].placements) == 1
    assert len(dlg._page_widgets[1].placements) == 0
    assert len(dlg._page_widgets[2].placements) == 1

    params = dlg.gather_params()
    assert sorted(p["page"] for p in params["placements"]) == [1, 3]

    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    images_p1 = result[0].get_images()
    images_p2 = result[1].get_images()
    images_p3 = result[2].get_images()
    result.close()
    assert len(images_p1) == 1
    assert len(images_p2) == 0
    assert len(images_p3) == 1


def test_sign_dialog_page_numbering_survives_a_mid_document_render_failure(tmp_path, monkeypatch):
    from app.core.errors import PDFError
    from app.core.pdf_ops import render_page_thumbnail as real_render_page_thumbnail
    from app.ui.dialogs import edit_dialogs
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    for i in range(4):
        doc.new_page(width=595, height=842).insert_text((72, 72), f"PAGE {i + 1}")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "signature.png")
    sig_pixmap.save(sig_path, "PNG")

    def flaky_render(path, page_num, max_size=100):
        if page_num == 3:
            raise PDFError("simulated render failure for page 3")
        return real_render_page_thumbnail(path, page_num, max_size=max_size)

    # Same convention as the RedactDialog equivalent
    # (test_redact_dialog_page_numbering_survives_a_mid_document_render_failure):
    # patch with pytest's monkeypatch fixture, not unittest.mock.
    monkeypatch.setattr(edit_dialogs, "render_page_thumbnail", flaky_render)

    dlg = SignDialog()
    dlg.use_signature_file(sig_path)
    dlg.on_files_changed([str(input_path)])

    assert len(dlg._page_widgets) == 4
    # Page 3's picture failed to render: it is kept as a blank page (so the
    # numbering can never shift), not dropped.
    assert dlg._page_widgets[2] is not None and not dlg._page_widgets[2].has_pixmap

    # Place a signature on page 4's widget (0-indexed slot 3) - it must be
    # reported as page 4, not silently relabeled as page 3 because page 3's
    # slot is None instead of missing entirely.
    page4_widget = dlg._page_widgets[3]
    w, h = page4_widget.width(), page4_widget.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(page4_widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page4_widget, Qt.LeftButton, Qt.NoModifier, click)

    params = dlg.gather_params()
    assert len(params["placements"]) == 1
    assert params["placements"][0]["page"] == 4


def test_sign_dialog_raises_when_no_signature_placed(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Some text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "signature.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = SignDialog()
    dlg.use_signature_file(sig_path)
    dlg.on_files_changed([str(input_path)])
    params = dlg.gather_params()
    assert params["placements"] == []
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError as exc:
        assert "at least one" in str(exc)


def _build_form_fixture(tmp_path, pages: int = 1):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    text_widget = fitz.Widget()
    text_widget.field_name = "full_name"
    text_widget.field_label = "Full Name"
    text_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    text_widget.field_value = "PREFILLED"
    text_widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(text_widget)

    checkbox_widget = fitz.Widget()
    checkbox_widget.field_name = "agree"
    checkbox_widget.field_label = "Agree"
    checkbox_widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    checkbox_widget.rect = fitz.Rect(72, 140, 90, 158)
    page.add_widget(checkbox_widget)

    combo_widget = fitz.Widget()
    combo_widget.field_name = "country"
    combo_widget.field_label = "Country"
    combo_widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    combo_widget.rect = fitz.Rect(72, 180, 250, 200)
    combo_widget.choice_values = ["USA", "Canada", "Mexico"]
    page.add_widget(combo_widget)

    # Additional pages beyond the first each get their own extra text field,
    # so multi-page tests can exercise fields on more than one page.
    for extra_page_num in range(2, pages + 1):
        extra_page = doc.new_page(width=595, height=842)
        extra_widget = fitz.Widget()
        extra_widget.field_name = "extra_field" if extra_page_num == 2 else f"extra_field_{extra_page_num}"
        extra_widget.field_label = "Extra Field" if extra_page_num == 2 else f"Extra Field {extra_page_num}"
        extra_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        extra_widget.rect = fitz.Rect(72, 100, 300, 120)
        extra_page.add_widget(extra_widget)

    path = tmp_path / "form.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_form_fields_widget_creates_the_right_qt_widget_per_field_type(tmp_path):
    input_path = _build_form_fixture(tmp_path)
    fields = extract_form_fields(input_path)
    thumb_bytes = render_page_thumbnail(input_path, 1, max_size=450)
    pixmap = QPixmap()
    pixmap.loadFromData(thumb_bytes)

    widget = FormFieldsWidget()
    widget.set_fields(fields, [pixmap])
    assert widget.has_fields() is True

    text_field = next(f for f in fields if f["type"] == "text")
    checkbox_field = next(f for f in fields if f["type"] == "checkbox")
    combo_field = next(f for f in fields if f["type"] == "combobox")

    text_qwidget = widget._field_widgets[(text_field["page"], text_field["index"])]
    checkbox_qwidget = widget._field_widgets[(checkbox_field["page"], checkbox_field["index"])]
    combo_qwidget = widget._field_widgets[(combo_field["page"], combo_field["index"])]

    assert isinstance(text_qwidget, QLineEdit)
    assert isinstance(checkbox_qwidget, QCheckBox)
    assert isinstance(combo_qwidget, QComboBox)

    # Verified empirically before this test was written: on a 595x842 page
    # rendered at max_size=450, the pixmap is exactly 318x450, and the text
    # field's rect ({"top": 0.1187648456057007, "left": 0.12100840336134454,
    # "right": 0.4957983193277311, "bottom": 0.8574821852731591}) converts
    # to exactly this pixel geometry.
    geom = text_qwidget.geometry()
    assert (geom.x(), geom.y(), geom.width(), geom.height()) == (38, 53, 121, 10)

    # Initial values reflect the fixture's own field_value/default.
    assert text_qwidget.text() == "PREFILLED"
    assert checkbox_qwidget.isChecked() is False
    assert combo_qwidget.currentText() == ""  # fixture's own value ("") isn't in choices, so index 0 (blank) stands
    assert list(combo_field["choices"]) == ["USA", "Canada", "Mexico"]


def test_form_fields_widget_values_reflects_synthetic_user_interaction(tmp_path):
    input_path = _build_form_fixture(tmp_path)
    fields = extract_form_fields(input_path)
    thumb_bytes = render_page_thumbnail(input_path, 1, max_size=450)
    pixmap = QPixmap()
    pixmap.loadFromData(thumb_bytes)

    widget = FormFieldsWidget()
    widget.set_fields(fields, [pixmap])

    text_field = next(f for f in fields if f["type"] == "text")
    checkbox_field = next(f for f in fields if f["type"] == "checkbox")
    combo_field = next(f for f in fields if f["type"] == "combobox")

    text_qwidget = widget._field_widgets[(text_field["page"], text_field["index"])]
    checkbox_qwidget = widget._field_widgets[(checkbox_field["page"], checkbox_field["index"])]
    combo_qwidget = widget._field_widgets[(combo_field["page"], combo_field["index"])]

    text_qwidget.clear()
    QTest.keyClicks(text_qwidget, "Jane Doe")
    QTest.mouseClick(checkbox_qwidget, Qt.LeftButton)
    combo_qwidget.setCurrentText("Canada")

    values_by_key = {(v["page"], v["index"]): v["value"] for v in widget.values()}
    assert values_by_key[(text_field["page"], text_field["index"])] == "Jane Doe"
    assert values_by_key[(checkbox_field["page"], checkbox_field["index"])] is True
    assert values_by_key[(combo_field["page"], combo_field["index"])] == "Canada"
    # values() reports ALL held fields, not only ones the user touched.
    assert len(widget.values()) == 3


def test_form_fields_widget_preserves_an_off_list_combobox_value(tmp_path):
    # A combobox's recorded value not being in its own choice list is a real,
    # valid PDF state (e.g. typed directly, or the choice list changed after
    # the value was set) - PDF_CH_FIELD_IS_EDIT is the flag that lets PyMuPDF
    # accept and keep such a value rather than rejecting it (confirmed
    # empirically while writing this test).
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    combo_widget = fitz.Widget()
    combo_widget.field_name = "country"
    combo_widget.field_label = "Country"
    combo_widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    combo_widget.field_flags = fitz.PDF_CH_FIELD_IS_EDIT
    combo_widget.field_value = "Atlantis"
    combo_widget.choice_values = ["USA", "Canada", "Mexico"]
    combo_widget.rect = fitz.Rect(72, 180, 250, 200)
    page.add_widget(combo_widget)

    input_path = tmp_path / "offlist.pdf"
    doc.save(str(input_path))
    doc.close()

    fields = extract_form_fields(str(input_path))
    thumb_bytes = render_page_thumbnail(str(input_path), 1, max_size=450)
    pixmap = QPixmap()
    pixmap.loadFromData(thumb_bytes)

    combo_field = next(f for f in fields if f["type"] == "combobox")
    assert combo_field["value"] == "Atlantis"
    assert combo_field["choices"] == ["USA", "Canada", "Mexico"]

    widget = FormFieldsWidget()
    widget.set_fields(fields, [pixmap])
    combo_qwidget = widget._field_widgets[(combo_field["page"], combo_field["index"])]

    # The off-list value must be preserved as a synthesized extra choice and
    # selected - not silently dropped to the blank placeholder, which would
    # make fill_form's own "" == clear-field branch erase this untouched
    # field's real value.
    assert combo_qwidget.currentText() == "Atlantis"
    assert combo_qwidget.findText("Atlantis") != -1

    values_by_key = {(v["page"], v["index"]): v["value"] for v in widget.values()}
    assert values_by_key[(combo_field["page"], combo_field["index"])] == "Atlantis"


def test_form_fields_widget_has_fields_false_for_a_fields_free_document():
    widget = FormFieldsWidget()
    widget.set_fields([], [QPixmap(100, 100)])
    assert widget.has_fields() is False
    assert widget.values() == []


def test_fill_form_dialog_fills_and_exports_real_values(tmp_path):
    from app.ui.dialogs.edit_dialogs import FillFormDialog

    input_path = _build_form_fixture(tmp_path)

    dlg = FillFormDialog()
    dlg.on_files_changed([input_path])
    assert dlg.fields_widget.has_fields() is True

    fields = dlg.fields_widget._fields
    text_field = next(f for f in fields if f["type"] == "text")
    combo_field = next(f for f in fields if f["type"] == "combobox")
    text_qwidget = dlg.fields_widget._field_widgets[(text_field["page"], text_field["index"])]
    combo_qwidget = dlg.fields_widget._field_widgets[(combo_field["page"], combo_field["index"])]

    text_qwidget.clear()
    QTest.keyClicks(text_qwidget, "Jane Doe")
    combo_qwidget.setCurrentText("Canada")

    params = dlg.gather_params()
    assert len(params["values"]) == 3

    output_paths = dlg.run_operation([input_path], params)

    # fill_form always bakes (flattens) its output, so extract_form_fields
    # on the OUTPUT returns [] - there are no widgets left to extract
    # (verified empirically while writing this plan; see this plan's Global
    # Constraints). Verify the filled values the same way
    # tests/test_pdf_ops.py's own fill_form tests do: via get_text() on the
    # output page, since text/combobox values render as literal text after
    # baking.
    result = fitz.open(output_paths[0])
    text = result[0].get_text()
    result.close()
    assert "Jane Doe" in text
    assert "Canada" in text


def test_fill_form_dialog_raises_when_document_has_no_fields(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import FillFormDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "No form fields here")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = FillFormDialog()
    dlg.on_files_changed([str(input_path)])
    assert dlg.fields_widget.has_fields() is False

    params = dlg.gather_params()
    assert params["values"] == []
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError as exc:
        assert "at least one" in str(exc)


def test_fill_form_dialog_clears_stale_state_on_a_failed_load(tmp_path):
    from app.ui.dialogs.edit_dialogs import FillFormDialog

    good_path = _build_form_fixture(tmp_path)

    dlg = FillFormDialog()
    dlg.on_files_changed([good_path])
    assert dlg.fields_widget.has_fields() is True

    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"not a real pdf")

    # A failed load must not leave the FIRST document's fields/values live -
    # on_files_changed resets to empty state before attempting the new file,
    # so a PDFError here leaves a clean empty state rather than a stale one.
    dlg.on_files_changed([str(corrupt_path)])
    assert dlg.fields_widget.has_fields() is False
    assert dlg.fields_widget.values() == []


def test_fill_form_dialog_handles_multiple_pages(tmp_path):
    from app.ui.dialogs.edit_dialogs import FillFormDialog

    input_path = _build_form_fixture(tmp_path, pages=2)

    dlg = FillFormDialog()
    dlg.on_files_changed([input_path])
    assert dlg.fields_widget.has_fields() is True
    assert dlg.fields_widget._container_layout.count() == 2

    fields = dlg.fields_widget._fields
    text_field = next(f for f in fields if f["page"] == 1 and f["type"] == "text")
    extra_field = next(f for f in fields if f["page"] == 2)
    text_qwidget = dlg.fields_widget._field_widgets[(text_field["page"], text_field["index"])]
    extra_qwidget = dlg.fields_widget._field_widgets[(extra_field["page"], extra_field["index"])]

    text_qwidget.clear()
    QTest.keyClicks(text_qwidget, "Page One Value")
    extra_qwidget.clear()
    QTest.keyClicks(extra_qwidget, "Page Two Value")

    params = dlg.gather_params()
    pages_seen = {v["page"] for v in params["values"]}
    assert pages_seen == {1, 2}

    output_paths = dlg.run_operation([input_path], params)

    result = fitz.open(output_paths[0])
    page1_text = result[0].get_text()
    page2_text = result[1].get_text()
    result.close()
    assert "Page One Value" in page1_text
    assert "Page Two Value" in page2_text


def test_diff_preview_widget_paints_pixmap_and_boxes():
    widget = DiffPreviewWidget()
    widget.set_pixmap(QPixmap(200, 100))
    widget.set_boxes([{"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}])
    assert widget.pixmap.size() == QPixmap(200, 100).size()
    assert widget.boxes == [{"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}]


def test_diff_preview_widget_ignores_all_mouse_input():
    widget = DiffPreviewWidget()
    widget.set_pixmap(QPixmap(200, 100))
    widget.set_boxes([{"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}])
    before_boxes = list(widget.boxes)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert widget.boxes == before_boxes


def test_box_changed_fires_exactly_once_on_a_successful_drag():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    calls = []
    widget.box_changed.connect(lambda: calls.append(1))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert len(calls) == 1


def test_box_changed_does_not_fire_on_a_too_small_drag():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    calls = []
    widget.box_changed.connect(lambda: calls.append(1))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(21, 11))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(21, 11))
    assert calls == []


def test_interactive_false_blocks_dragging_from_creating_a_box():
    widget = RectangleOverlayWidget(multi=False, interactive=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert widget.boxes == []


def test_compare_dialog_eager_text_diff_and_lazy_visual_diff(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Hello World")
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Second page A")
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Third page only in A")
    path_a = tmp_path / "compare_a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Hello World CHANGED")
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Second page A")
    path_b = tmp_path / "compare_b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    assert dlg.page_spin.maximum() == 3

    # Text diffs for ALL pages are computed eagerly, before the spinner ever
    # moves past page 1 - confirmed by checking page 3's (never-visited via
    # the spinner) already-computed state.
    assert dlg._pages[0]["has_counterpart"] is True
    assert any(op["op"] in ("delete", "insert") for op in dlg._pages[0]["text_diff"])
    assert dlg._pages[1]["has_counterpart"] is True
    assert all(op["op"] == "equal" for op in dlg._pages[1]["text_diff"])
    assert dlg._pages[2]["has_counterpart"] is False  # page 3 only exists in A

    # on_files_changed shows page 1 immediately (matching every other
    # dialog's "show page 1 right after file load" convention) - its own
    # text genuinely differs between A and B, so its visual diff has at
    # least one box.
    assert dlg.visual_a.pixmap is not None
    assert len(dlg.visual_a.boxes) >= 1

    # The visual diff for any OTHER page is only ever computed when the
    # spinner actually reaches it - moving to page 2 (identical text in both
    # documents) must produce zero diff boxes, proving this specific call
    # (not some pre-computed value) is what populated the widgets.
    dlg.page_spin.setValue(2)
    assert dlg.visual_a.pixmap is not None
    assert dlg.visual_a.boxes == []


def test_compare_dialog_hides_visual_diff_on_a_no_counterpart_page(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Hello World")
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Second page A")
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Third page only in A")
    path_a = tmp_path / "compare_a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Hello World CHANGED")
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Second page A")
    path_b = tmp_path / "compare_b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    # Note: isVisible() reflects whether the widget is actually shown on
    # screen, which also depends on the (never-shown-in-this-test) top-level
    # dialog's own visibility, so it is False here even though no
    # setVisible(False) call has happened yet. isHidden() reflects only the
    # widget's own explicit hidden flag (set via setVisible/setHidden),
    # independent of ancestor visibility, so it is the correct check here.
    assert not dlg.visual_a.isHidden()  # page 1 has a counterpart

    dlg.page_spin.setValue(3)  # page 3 only exists in document A
    assert dlg.visual_a.isHidden()
    assert dlg.visual_b.isHidden()

    dlg.page_spin.setValue(1)  # back to a page with a counterpart
    assert not dlg.visual_a.isHidden()
    assert not dlg.visual_b.isHidden()


def test_compare_dialog_run_operation_requires_exactly_two_files(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import CompareDialog

    dlg = CompareDialog()
    for file_count in (0, 1, 3):
        try:
            dlg.run_operation([], {"file_count": file_count})
            assert False, f"expected PDFError for file_count={file_count}"
        except PDFError as exc:
            assert "exactly 2" in str(exc)


def test_compare_dialog_run_operation_returns_no_output_files(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Same text")
    path_a = tmp_path / "a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Same text")
    path_b = tmp_path / "b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    params = dlg.gather_params()
    assert params == {"file_count": 2}
    output_paths, message = dlg.run_operation([str(path_a), str(path_b)], params)
    assert output_paths == []
    assert "1 page" in message


def test_compare_dialog_run_operation_raises_if_a_file_became_unreadable(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Same text")
    path_a = tmp_path / "a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Same text")
    path_b = tmp_path / "b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    assert dlg.gather_params() == {"file_count": 2}

    # Now simulate the second file having become unreadable (corrupt) while
    # exactly 2 files are still selected.
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"not a real pdf")
    dlg.on_files_changed([str(path_a), str(corrupt_path)])
    params = dlg.gather_params()
    assert params["file_count"] == 2

    try:
        dlg.run_operation([str(path_a), str(corrupt_path)], params)
        assert False, "expected PDFError"
    except PDFError as exc:
        assert "valid PDF" in str(exc)


def test_compare_dialog_does_not_force_an_oversized_window(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Hello World")
    path_a = tmp_path / "a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Hello World CHANGED")
    path_b = tmp_path / "b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    assert dlg.minimumSizeHint().width() <= 1280
    assert dlg.minimumSizeHint().height() <= 1280


def test_compare_dialog_text_diff_escapes_html_special_characters(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "if a < b and x > y & z")
    path_a = tmp_path / "a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "if a < b and x > y & z CHANGED")
    path_b = tmp_path / "b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    plain_text = dlg.text_diff_view.toPlainText()
    assert "a < b and x > y & z" in plain_text


def test_compare_dialog_clear_files_button_resets_state(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Hello World")
    path_a = tmp_path / "a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Hello World CHANGED")
    path_b = tmp_path / "b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.file_list.addItem(str(path_a))
    dlg.file_list.addItem(str(path_b))
    dlg.on_files_changed([str(path_a), str(path_b)])
    assert dlg._path_a is not None

    dlg._clear_files()
    assert dlg.file_list.count() == 0
    assert dlg._path_a is None
    assert dlg.gather_params()["file_count"] == 0


from app.ui.edit_canvas import (
    _MIN_TEXT_HEIGHT_FRACTION,
    _MIN_TEXT_WIDTH_FRACTION,
    EditElementsModel,
    EditPageWidget,
    build_segments_document,
    closest_base14_family,
    segments_from_document,
)


def _new_text_element(page, x=0.1, y=0.1, width=0.2, height=0.1, text="Hello"):
    return {
        "page": page, "type": "new_text", "x": x, "y": y, "width": width, "height": height,
        "text": text, "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#1f2937", "align": "left",
    }


def test_edit_model_add_and_elements_for_page():
    model = EditElementsModel()
    id1 = model.add(_new_text_element(page=1))
    id2 = model.add({"page": 2, "type": "image", "x": 0.2, "y": 0.2, "width": 0.25, "height": 0.1, "file_id": "sig.png"})
    assert len(model.elements) == 2
    assert [e["id"] for e in model.elements_for_page(1)] == [id1]
    assert [e["id"] for e in model.elements_for_page(2)] == [id2]


def test_edit_model_undo_redo_are_whole_array_snapshots():
    model = EditElementsModel()
    id1 = model.add(_new_text_element(page=1))
    model.add(_new_text_element(page=1, text="Second"))
    assert len(model.elements) == 2
    model.remove(id1)
    assert len(model.elements) == 1
    model.undo()
    assert len(model.elements) == 2
    model.redo()
    assert len(model.elements) == 1


def test_edit_model_nudge_shifts_position_clamps_and_commits_an_undo_step():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.95, y=0.1, width=0.1, height=0.1))
    model.nudge(el_id, 0.5, 0.0)  # far past the right edge
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(1 - el["width"])  # clamped, not overshot
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["x"] == pytest.approx(0.95)  # nudge is its own undo step


def test_edit_model_reorder_forward_skips_a_different_page_neighbor():
    model = EditElementsModel()
    a = model.add(_new_text_element(page=1, text="a"))
    b_other_page = model.add(_new_text_element(page=2, text="b"))
    c = model.add(_new_text_element(page=1, text="c"))
    # array order is [a(page1), b(page2), c(page1)] - forward on 'a' must swap
    # with 'c' (the nearest SAME-page neighbor), skipping over 'b' (page 2).
    assert [e["id"] for e in model.elements] == [a, b_other_page, c]
    model.reorder(a, "forward")
    assert [e["id"] for e in model.elements] == [c, b_other_page, a]


def test_edit_model_reorder_front_and_back():
    model = EditElementsModel()
    a = model.add(_new_text_element(page=1, text="a"))
    b_other_page = model.add(_new_text_element(page=2, text="b"))
    c = model.add(_new_text_element(page=1, text="c"))
    d = model.add(_new_text_element(page=1, text="d"))
    # order: [a(1), b(2), c(1), d(1)]
    model.reorder(a, "front")  # 'a' becomes last among page-1 elements
    assert [e["id"] for e in model.elements] == [b_other_page, c, d, a]
    model.reorder(d, "back")  # 'd' becomes first among page-1 elements
    assert [e["id"] for e in model.elements] == [b_other_page, d, c, a]


def test_edit_model_copy_paste_shifts_by_the_paste_offset():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.3, y=0.3, width=0.1, height=0.05))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["x"] == pytest.approx(0.33)
    assert pasted["y"] == pytest.approx(0.33)
    assert pasted_id != el_id


def test_edit_model_paste_offset_clamps_near_the_page_edge():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.98, y=0.1, width=0.02, height=0.05))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    # room_x = 1 - (0.98 + 0.02) = 0, so the x-shift clamps to 0.
    assert pasted["x"] == pytest.approx(0.98)


def test_edit_model_cut_removes_the_source_element():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1))
    model.select(el_id)
    model.cut()
    assert model.elements == []
    assert model.selected_id is None
    pasted_id = model.paste()
    assert pasted_id is not None
    assert len(model.elements) == 1


def test_edit_page_widget_empty_click_in_new_text_mode_opens_a_text_editor():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    # isVisible() on the child QTextEdit only reflects reality once this
    # widget itself has been shown - show()/close() are scoped to this one
    # test rather than to set_page_pixmap, so the many other EditPageWidget
    # tests in this file don't each leak a real top-level shown window
    # (shown-and-never-closed windows accumulating across tests was
    # confirmed to hang the full suite once enough of them piled up).
    widget.show()
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert widget._text_editor is not None
    assert widget._text_editor.isVisible()
    widget.close()


def test_edit_page_widget_typing_and_committing_a_new_text_creates_an_element():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(widget._text_editor, "Hello World")
    widget._commit_text_editor()
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "new_text"
    assert el["text"] == "Hello World"
    assert el["page"] == 1


def test_edit_page_widget_blank_text_draft_is_discarded_not_committed():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(widget._text_editor, "   ")  # whitespace only
    widget._commit_text_editor()
    assert model.elements == []


def test_edit_page_widget_moving_a_new_text_element():
    model = EditElementsModel()
    el_id = model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    body = QPoint(int(w * 0.35), int(h * 0.32))  # inside the element's body
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 20, body.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 20, body.y() + 10))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(0.3 + 20 / w)
    assert el["y"] == pytest.approx(0.3 + 10 / h)
    assert model.selected_id == el_id


def test_edit_page_widget_resizing_a_new_text_element():
    model = EditElementsModel()
    el_id = model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    el = model.elements[0]
    rect = widget._element_rect_px(el)
    handle_center = widget._resize_handles(el)["corner"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = model.elements[0]
    assert resized["width"] == pytest.approx(0.2 + 40 / w)
    assert resized["height"] == pytest.approx(0.1 + 40 / h)


def test_edit_page_widget_marker_click_deletes_a_new_text_element():
    model = EditElementsModel()
    el_id = model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    marker = widget._marker_rect(el)
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert model.elements == []


def test_edit_page_widget_creating_an_image_element(tmp_path):
    from PySide6.QtGui import QPixmap as _QPixmap
    sig_pixmap = _QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "sig.png")
    sig_pixmap.save(sig_path, "PNG")

    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "image"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.5), int(h * 0.5))
    widget.create_image_at(click.x() / w, click.y() / h, sig_path)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "image"
    assert el["file_id"] == sig_path
    assert el["page"] == 1
    # 200x80 signature -> aspect 0.4 -> default width 0.25, height 0.1,
    # centered on the click point - same formula ImagePlacementWidget uses.
    assert el["width"] == pytest.approx(0.25)
    assert el["height"] == pytest.approx(0.1)
    assert el["x"] == pytest.approx(0.5 - 0.125)
    assert el["y"] == pytest.approx(0.5 - 0.05)


def test_edit_page_widget_image_corner_handle_resizes_with_locked_aspect(tmp_path):
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    handle_center = widget._resize_handles(el)["corner"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = next(e for e in model.elements if e["id"] == el_id)
    w = widget.width()
    expected_width = 0.2 + 40 / w
    assert resized["width"] == pytest.approx(expected_width)
    assert resized["height"] == pytest.approx(expected_width * 0.5)  # locked aspect 0.1/0.2 = 0.5


def test_edit_page_widget_image_width_only_handle_ignores_height():
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    handle_center = widget._resize_handles(el)["width"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))  # y-movement must be ignored
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = next(e for e in model.elements if e["id"] == el_id)
    w = widget.width()
    assert resized["width"] == pytest.approx(0.2 + 40 / w)
    assert resized["height"] == pytest.approx(0.1)  # unchanged


def test_edit_page_widget_image_height_only_handle_ignores_width():
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    handle_center = widget._resize_handles(el)["height"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))  # x-movement must be ignored
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = next(e for e in model.elements if e["id"] == el_id)
    h = widget.height()
    assert resized["width"] == pytest.approx(0.2)  # unchanged
    assert resized["height"] == pytest.approx(0.1 + 40 / h)


def test_edit_page_widget_selecting_an_image_does_not_require_new_text_mode():
    # An existing image element must remain selectable/movable/deletable
    # even while create_mode is "new_text" - matching the web's "mode only
    # gates empty-space creation" behavior.
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"  # deliberately the OTHER mode
    w, h = widget.width(), widget.height()
    marker = widget._marker_rect(model.elements[0])
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert model.elements == []  # deleted, despite create_mode being "new_text"


def test_edit_pdf_dialog_places_new_text_and_image_across_pages_and_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "sig.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    assert len(dlg._page_widgets) == 2

    page1 = dlg._page_widgets[0]
    page1.create_mode = "new_text"
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(page1._text_editor, "New text element")
    page1._commit_text_editor()

    page2 = dlg._page_widgets[1]
    page2.create_image_at(0.3, 0.3, sig_path)

    assert len(dlg.model.elements) == 2

    # Undo the image placement, then redo it, proving the model's history
    # survives into the actual export.
    dlg.model.undo()
    assert len(dlg.model.elements) == 1
    dlg.model.redo()
    assert len(dlg.model.elements) == 2

    params = dlg.gather_params()
    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    page1_text = result[0].get_text()
    page2_images = result[1].get_images()
    result.close()
    assert "New text element" in page1_text
    assert len(page2_images) == 1


def test_edit_pdf_dialog_undo_redo_and_delete_keyboard_shortcuts(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    page1.create_mode = "new_text"
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(page1._text_editor, "Some text")
    page1._commit_text_editor()
    assert len(dlg.model.elements) == 1

    dlg._handle_shortcut("undo")
    assert dlg.model.elements == []
    dlg._handle_shortcut("redo")
    assert len(dlg.model.elements) == 1

    dlg._handle_shortcut("delete")
    assert dlg.model.elements == []


def test_edit_pdf_dialog_arrow_key_nudges_the_selected_element(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    el_id = dlg.model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.05,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    dlg.model.select(el_id)
    QTest.keyClick(dlg, Qt.Key_Right)
    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(0.3 + 0.004)
    QTest.keyClick(dlg, Qt.Key_Down, Qt.ShiftModifier)
    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    assert el["y"] == pytest.approx(0.3 + 0.02)


def test_edit_pdf_dialog_shortcuts_are_suppressed_while_a_text_editor_is_open(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    el_id = dlg.model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.05,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    dlg.model.select(el_id)
    page1 = dlg._page_widgets[0]
    page1._open_text_editor_for_existing(dlg.model.elements[0])
    assert page1._text_editor is not None
    # A "delete" shortcut fired while a text editor is still open (e.g. a
    # keyboard shortcut pressed mid-edit, before the editor has been
    # committed) must NOT delete at the model level - matching the web's
    # own "any text-input-like element has focus" suppression rule.
    # _handle_shortcut simply returns early here: the action no-ops
    # entirely, it is not forwarded on to the QTextEdit.
    dlg._handle_shortcut("delete")
    assert len(dlg.model.elements) == 1


def test_edit_pdf_dialog_gather_params_raises_when_no_elements_placed(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Some text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    params = dlg.gather_params()
    assert params["elements"] == []
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError:
        pass


def test_edit_page_widget_clicking_elsewhere_commits_the_open_text_draft():
    # Deliberately never calls _commit_text_editor() itself: every other
    # text test does, which is exactly why "nothing in production code ever
    # calls it" shipped unnoticed. This drives the REAL user gesture -
    # click empty space, type, click somewhere else - end to end.
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(widget._text_editor, "Committed by clicking away")

    elsewhere = QPoint(int(w * 0.8), int(h * 0.8))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, elsewhere)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, elsewhere)

    assert len(model.elements) == 1
    assert model.elements[0]["text"] == "Committed by clicking away"
    assert model.elements[0]["type"] == "new_text"


def test_edit_page_widget_opening_a_second_editor_commits_the_first_draft():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    widget._open_text_editor_for_new((0.3, 0.3))
    QTest.keyClicks(widget._text_editor, "First")
    widget._open_text_editor_for_new((0.7, 0.7))  # directly opens another
    assert len(model.elements) == 1
    assert model.elements[0]["text"] == "First"  # committed, not discarded


def test_edit_page_widget_editing_existing_text_is_undoable_to_the_old_text():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, text="original"))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget._open_text_editor_for_existing(model.elements[0])
    widget._text_editor.selectAll()
    QTest.keyClicks(widget._text_editor, "CHANGED")
    widget._commit_text_editor()
    assert next(e for e in model.elements if e["id"] == el_id)["text"] == "CHANGED"

    model.undo()
    # commit() snapshots the state BEFORE the mutation, so undo must reach
    # the pre-edit text - not the post-edit text it had already become.
    assert next(e for e in model.elements if e["id"] == el_id)["text"] == "original"


def test_edit_page_widget_undo_after_a_drag_restores_the_pre_drag_position():
    # The gesture's undo step has to be pushed BEFORE its first mutation:
    # mouseMoveEvent mutates the live element in place, so committing at
    # release time would snapshot the already-moved element and undo would
    # pop the state it already has - a silent no-op.
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.3, y=0.3, width=0.2, height=0.1))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()

    body = QPoint(int(w * 0.35), int(h * 0.33))
    moved_to = QPoint(body.x() + 20, body.y() + 10)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, moved_to)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, moved_to)
    dragged = next(e for e in model.elements if e["id"] == el_id)
    assert dragged["x"] == pytest.approx(0.3 + 20 / w)

    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["x"] == pytest.approx(0.3)
    assert reverted["y"] == pytest.approx(0.3)


def test_edit_page_widget_undo_after_a_resize_restores_the_pre_resize_size():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.3, y=0.3, width=0.2, height=0.1))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    handle_center = widget._resize_handles(model.elements[0])["corner"].center()
    moved_to = QPoint(handle_center.x() + 40, handle_center.y() + 40)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, moved_to)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, moved_to)
    assert next(e for e in model.elements if e["id"] == el_id)["width"] > 0.2

    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["width"] == pytest.approx(0.2)
    assert reverted["height"] == pytest.approx(0.1)


def test_edit_page_widget_a_drag_pushes_exactly_one_undo_step():
    # Many intermediate mouse-move events, ONE undo step - the gesture must
    # commit lazily on its first real change and never again.
    model = EditElementsModel()
    model.add(_new_text_element(page=1, x=0.3, y=0.3, width=0.2, height=0.1))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    body = QPoint(int(widget.width() * 0.35), int(widget.height() * 0.33))
    depth_before = len(model._undo_stack)

    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    for step in (5, 12, 20, 31):
        QTest.mouseMove(widget, QPoint(body.x() + step, body.y() + step))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 31, body.y() + 31))

    assert len(model._undo_stack) == depth_before + 1


def test_edit_page_widget_zero_movement_click_pushes_no_undo_step():
    model = EditElementsModel()
    id1 = model.add(_new_text_element(page=1, x=0.3, y=0.3, width=0.2, height=0.1, text="first"))
    model.add(_new_text_element(page=1, x=0.6, y=0.6, width=0.2, height=0.1, text="second"))
    model.undo()  # drops "second"; a redo of it is now pending
    assert len(model.elements) == 1

    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    undo_depth = len(model._undo_stack)
    redo_depth = len(model._redo_stack)
    assert redo_depth == 1

    # A plain click-to-select on the element's body: press and release at
    # the SAME point, i.e. a gesture that changes nothing.
    body = QPoint(int(widget.width() * 0.35), int(widget.height() * 0.33))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, body)
    assert model.selected_id == id1  # it did select

    assert len(model._undo_stack) == undo_depth  # no junk entry pushed
    assert len(model._redo_stack) == redo_depth  # pending redo not wiped
    model.redo()
    assert len(model.elements) == 2  # the real redo still works


def test_edit_page_widget_marker_and_handle_do_not_overlap_at_minimum_size():
    # Mirrors ImagePlacementWidget's own overlap test. At the minimum text
    # box size on a small page preview the old fixed-14px rects overlapped,
    # and since markers are hit-tested first, a click meant to resize
    # deleted the element instead.
    model = EditElementsModel()
    model.add(_new_text_element(
        page=1, x=0.3, y=0.3,
        width=_MIN_TEXT_WIDTH_FRACTION, height=_MIN_TEXT_HEIGHT_FRACTION,
    ))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(318, 450))
    el = model.elements[0]
    rect = widget._element_rect_px(el)
    assert rect.height() < 28  # confirms this really is the extreme case

    marker = widget._marker_rect(el)
    handle = widget._resize_handles(el)["corner"]
    assert not marker.intersects(handle)
    assert not marker.contains(handle.center())


def test_edit_pdf_dialog_image_lands_on_its_own_page_after_a_render_failure(tmp_path, monkeypatch):
    from app.core.errors import PDFError
    from app.core.pdf_ops import render_page_thumbnail as real_render_page_thumbnail
    from app.ui.dialogs import edit_dialogs
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "sig.png")
    sig_pixmap.save(sig_path, "PNG")

    def flaky_render(path, page_num, max_size=100):
        if page_num == 1:
            raise PDFError("simulated render failure for page 1")
        return real_render_page_thumbnail(path, page_num, max_size=max_size)

    monkeypatch.setattr(edit_dialogs, "render_page_thumbnail", flaky_render)
    monkeypatch.setattr(
        edit_dialogs.QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (sig_path, "")),
    )

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    # A page whose picture can't be drawn is kept (blank white) rather than
    # dropped, so it can still be edited and the pages stay in order.
    assert [w.page_number for w in dlg._page_widgets] == [1, 2, 3]
    assert not dlg._page_widgets[0].has_pixmap and dlg._page_widgets[1].has_pixmap

    page2 = dlg._page_widgets[1]
    page2.create_mode = "image"
    click = QPoint(int(page2.width() * 0.5), int(page2.height() * 0.5))
    QTest.mousePress(page2, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page2, Qt.LeftButton, Qt.NoModifier, click)

    assert len(dlg.model.elements) == 1
    # The image lands on the page that was clicked (the callback closes over
    # the widget itself, not an index into the list).
    assert dlg.model.elements[0]["page"] == 2


def test_edit_pdf_dialog_new_page_widgets_honor_the_current_create_mode(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg._set_create_mode("image")
    # Loading a file AFTER picking a mode must not silently revert the new
    # page widgets to EditPageWidget's own "new_text" default while the
    # toolbar still shows "Insert Image" checked.
    dlg.on_files_changed([str(input_path)])
    assert dlg.image_btn.isChecked()
    assert dlg._page_widgets[0].create_mode == "image"


def test_edit_model_remove_listener_unsubscribes_a_callback():
    model = EditElementsModel()
    calls = []
    callback = lambda: calls.append(1)
    model.on_change.append(callback)
    model.add(_new_text_element(page=1))
    assert len(calls) == 1

    model.remove_listener(callback)
    model.add(_new_text_element(page=1, text="Second"))
    assert len(calls) == 1  # not fired again
    model.remove_listener(callback)  # removing twice is a no-op, not an error


def _shape_element(page=1, shape="rectangle", x0=0.2, y0=0.2, x1=0.5, y1=0.4, color="#ff0000", width=3, filled=False):
    return {"page": page, "type": "shape", "shape": shape, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "color": color, "width": width, "filled": filled}


def test_edit_model_shape_paste_offset_shifts_both_corners_and_clamps_near_edge():
    model = EditElementsModel()
    el_id = model.add(_shape_element(x0=0.2, y0=0.2, x1=0.4, y1=0.3))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["x0"] == pytest.approx(0.23)
    assert pasted["x1"] == pytest.approx(0.43)
    assert pasted["y0"] == pytest.approx(0.23)
    assert pasted["y1"] == pytest.approx(0.33)

    el_id2 = model.add(_shape_element(x0=0.9, y0=0.2, x1=0.99, y1=0.3))
    model.select(el_id2)
    model.copy()
    pasted_id2 = model.paste()
    pasted2 = next(e for e in model.elements if e["id"] == pasted_id2)
    # room_x = 1 - max(0.9, 0.99) = 0.01, clamped to 0.01 (not the full 0.03 offset)
    assert pasted2["x1"] == pytest.approx(1.0)
    assert pasted2["x0"] == pytest.approx(0.91)


def test_edit_model_shape_nudge_shifts_both_corners_and_clamps_at_the_page_edge():
    model = EditElementsModel()
    el_id = model.add(_shape_element(x0=0.9, y0=0.3, x1=0.98, y1=0.4))
    model.nudge(el_id, 0.5, 0.0)  # far past the right edge
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x1"] == pytest.approx(1.0)
    assert el["x0"] == pytest.approx(0.92)  # bbox width (0.08) preserved
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["x0"] == pytest.approx(0.9) and reverted["x1"] == pytest.approx(0.98)


def test_edit_model_shape_nudge_clamps_correctly_even_when_drawn_backwards():
    model = EditElementsModel()
    # x0 > x1: the shape was drawn from bottom-right to top-left.
    el_id = model.add(_shape_element(x0=0.98, y0=0.3, x1=0.9, y1=0.4))
    model.nudge(el_id, 0.5, 0.0)
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x0"] == pytest.approx(1.0)  # x0 is the bbox max here, still clamps correctly
    assert el["x1"] == pytest.approx(0.92)


def test_edit_page_widget_dragging_creates_a_rectangle_shape():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "rectangle"
    widget.color = "#0000ff"
    widget.width_preset = "thick"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.5), int(h * 0.4))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "shape" and el["shape"] == "rectangle"
    assert el["x0"] == pytest.approx(0.2) and el["y0"] == pytest.approx(0.2)
    assert el["x1"] == pytest.approx(0.5) and el["y1"] == pytest.approx(0.4)
    assert el["color"] == "#0000ff" and el["width"] == 6 and el["filled"] is False


def test_edit_page_widget_below_threshold_rectangle_drag_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "rectangle"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.205), int(h * 0.205))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements == []


def test_edit_page_widget_arrow_only_needs_one_axis_to_clear_the_threshold():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "arrow"
    w, h = widget.width(), widget.height()
    # A horizontal drag: dx is large, dy is a real but sub-threshold
    # 2px wobble (2/600 = 0.0033, under _MIN_DRAG_FRACTION's 0.02).
    start = QPoint(int(w * 0.1), int(h * 0.5))
    end = QPoint(int(w * 0.4), int(h * 0.5) + 2)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    assert model.elements[0]["shape"] == "arrow"


def test_edit_page_widget_arrow_with_both_axes_below_threshold_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "arrow"
    w, h = widget.width(), widget.height()
    # The mouse really does move - 2px on each axis (0.005 of the width,
    # 0.0033 of the height) - but neither axis reaches 0.02, so even an
    # arrow (which needs only ONE axis) is discarded.
    start = QPoint(int(w * 0.5), int(h * 0.5))
    end = QPoint(int(w * 0.5) + 2, int(h * 0.5) + 2)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements == []


def test_edit_page_widget_line_or_arrow_shape_forces_filled_false_at_creation():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "line"
    widget.filled = True  # toolbar checkbox happens to be checked
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.1), int(h * 0.1))
    end = QPoint(int(w * 0.4), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements[0]["filled"] is False


def test_edit_page_widget_shape_resize_handle_always_drags_x1_y1_even_when_drawn_backwards():
    model = EditElementsModel()
    el_id = model.add(_shape_element(x0=0.6, y0=0.6, x1=0.3, y1=0.3))  # drawn backwards
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    el = next(e for e in model.elements if e["id"] == el_id)
    handle = widget._resize_handles(el)["corner"]
    center = handle.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(widget, QPoint(center.x() + 20, center.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(center.x() + 20, center.y() + 10))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x0"] == 0.6 and el["y0"] == 0.6  # untouched
    assert el["x1"] == pytest.approx(0.3 + 20 / w)
    assert el["y1"] == pytest.approx(0.3 + 10 / h)
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["x1"] == 0.3 and reverted["y1"] == 0.3  # undo restores the pre-resize corner


def test_edit_page_widget_shape_move_shifts_all_four_coordinates():
    model = EditElementsModel()
    el_id = model.add(_shape_element(shape="line", x0=0.3, y0=0.3, x1=0.5, y1=0.3))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    # A horizontal line's bbox has zero height - click must still hit its
    # (margin-inflated) body, not fall through to empty-space handling.
    body = QPoint(int(w * 0.4), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 10, body.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 10, body.y() + 10))
    el = next(e for e in model.elements if e["id"] == el_id)
    dx, dy = 10 / w, 10 / h
    assert el["x0"] == pytest.approx(0.3 + dx) and el["x1"] == pytest.approx(0.5 + dx)
    assert el["y0"] == pytest.approx(0.3 + dy) and el["y1"] == pytest.approx(0.3 + dy)
    assert model.selected_id == el_id


def test_edit_page_widget_clicking_a_shapes_marker_removes_it():
    model = EditElementsModel()
    el_id = model.add(_shape_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    marker = widget._marker_rect(el)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def _stroke_element(page=1, points=None, color="#00aa00", width=3):
    return {"page": page, "type": "stroke", "points": points or [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.2}], "color": color, "width": width}


def test_edit_model_stroke_paste_offset_shifts_every_point_and_clamps_near_edge():
    model = EditElementsModel()
    el_id = model.add(_stroke_element(points=[{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.2}]))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["points"][0]["x"] == pytest.approx(0.13)
    assert pasted["points"][1]["y"] == pytest.approx(0.23)

    el_id2 = model.add(_stroke_element(points=[{"x": 0.9, "y": 0.1}, {"x": 0.99, "y": 0.2}]))
    model.select(el_id2)
    model.copy()
    pasted_id2 = model.paste()
    pasted2 = next(e for e in model.elements if e["id"] == pasted_id2)
    # room_x = 1 - max(0.9, 0.99) = 0.01, clamped to 0.01
    assert pasted2["points"][1]["x"] == pytest.approx(1.0)
    assert pasted2["points"][0]["x"] == pytest.approx(0.91)


def test_edit_model_stroke_nudge_shifts_every_point_and_clamps_at_the_page_edge():
    model = EditElementsModel()
    el_id = model.add(_stroke_element(points=[{"x": 0.9, "y": 0.3}, {"x": 0.98, "y": 0.4}]))
    model.nudge(el_id, 0.5, 0.0)
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["points"][1]["x"] == pytest.approx(1.0)
    assert el["points"][0]["x"] == pytest.approx(0.92)
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["points"][0]["x"] == pytest.approx(0.9)


def test_edit_page_widget_freehand_drag_captures_every_move_as_a_point():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    widget.color = "#123456"
    widget.width_preset = "thin"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.1), int(h * 0.1))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, QPoint(int(w * 0.15), int(h * 0.15)))
    QTest.mouseMove(widget, QPoint(int(w * 0.2), int(h * 0.2)))
    end = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "stroke" and len(el["points"]) == 4  # start + 2 moves + end
    assert el["color"] == "#123456" and el["width"] == 1


def test_edit_page_widget_stroke_click_with_one_axis_of_jitter_is_kept():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    w, h = widget.width(), widget.height()
    # dx clears the threshold; dy is a real 2px wobble (0.0033 of the
    # page) that does not - kept per the web's own "discard only if BOTH
    # axes are below threshold" rule.
    start = QPoint(int(w * 0.1), int(h * 0.5))
    end = QPoint(int(w * 0.3), int(h * 0.5) + 2)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1


def test_edit_page_widget_stroke_with_both_axes_of_jitter_is_kept():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    w, h = widget.width(), widget.height()
    # Two real points 2px apart on each axis. This used to be discarded as
    # "too short"; a short line must register (as on the web app).
    start = QPoint(int(w * 0.5), int(h * 0.5))
    end = QPoint(int(w * 0.5) + 2, int(h * 0.5) + 2)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1 and model.elements[0]["type"] == "stroke"


def test_edit_page_widget_stroke_single_point_click_makes_a_dot():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    click = QPoint(40, 60)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert len(model.elements) == 1
    assert len(model.elements[0]["points"]) == 1
    assert model.selected_id is None  # drawings are only selectable with Select


def test_edit_page_widget_stroke_has_no_resize_handle():
    model = EditElementsModel()
    el_id = model.add(_stroke_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert widget._resize_handles(el) == {}


def test_edit_page_widget_moving_a_stroke_shifts_every_point():
    model = EditElementsModel()
    el_id = model.add(_stroke_element(points=[{"x": 0.2, "y": 0.2}, {"x": 0.25, "y": 0.25}, {"x": 0.3, "y": 0.2}]))
    widget = EditPageWidget(model, page_number=1)
    widget.create_mode = "select"  # strokes are only selectable with the Select tool
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    body = QPoint(int(w * 0.25), int(h * 0.22))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 8, body.y() + 4))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 8, body.y() + 4))
    el = next(e for e in model.elements if e["id"] == el_id)
    dx, dy = 8 / w, 4 / h
    assert el["points"][0]["x"] == pytest.approx(0.2 + dx)
    assert el["points"][2]["y"] == pytest.approx(0.2 + dy)


def test_edit_page_widget_clicking_a_strokes_marker_removes_it():
    model = EditElementsModel()
    el_id = model.add(_stroke_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    marker = widget._marker_rect(el)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def _highlight_element(page=1, top=0.2, left=0.2, right=0.5, bottom=0.5, color="#ffff00"):
    return {"page": page, "type": "highlight", "top": top, "left": left, "right": right, "bottom": bottom, "color": color}


def test_edit_model_highlight_paste_offset_uses_insets_directly_as_room():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.2, left=0.2, right=0.5, bottom=0.5))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["left"] == pytest.approx(0.23) and pasted["right"] == pytest.approx(0.47)
    assert pasted["top"] == pytest.approx(0.23) and pasted["bottom"] == pytest.approx(0.47)

    el_id2 = model.add(_highlight_element(top=0.2, left=0.2, right=0.01, bottom=0.5))
    model.select(el_id2)
    model.copy()
    pasted_id2 = model.paste()
    pasted2 = next(e for e in model.elements if e["id"] == pasted_id2)
    # right=0.01 IS the room (no separate max-corner calc needed for this type) - clamps to itself
    assert pasted2["right"] == pytest.approx(0.0)
    assert pasted2["left"] == pytest.approx(0.21)


def test_edit_model_highlight_nudge_shifts_left_top_and_shrinks_right_bottom():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.2, left=0.2, right=0.01, bottom=0.5))
    model.nudge(el_id, 0.5, 0.0)  # far past the right edge
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["right"] == pytest.approx(0.0)
    assert el["left"] == pytest.approx(0.21)
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["right"] == pytest.approx(0.01) and reverted["left"] == pytest.approx(0.2)


def test_edit_page_widget_dragging_creates_a_highlight_with_sorted_insets():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "highlight"
    widget.color = "#ff00ff"
    w, h = widget.width(), widget.height()
    # drag from bottom-right to top-left - insets must still sort correctly
    start = QPoint(int(w * 0.6), int(h * 0.5))
    end = QPoint(int(w * 0.3), int(h * 0.2))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "highlight" and el["color"] == "#ff00ff"
    assert el["left"] == pytest.approx(0.3) and el["top"] == pytest.approx(0.2)
    assert el["right"] == pytest.approx(1 - 0.6) and el["bottom"] == pytest.approx(1 - 0.5)


def test_edit_page_widget_below_threshold_highlight_drag_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "highlight"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.205), int(h * 0.4))  # dx below threshold even though dy clears it
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements == []


def test_edit_page_widget_highlight_resize_only_changes_right_and_bottom():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.2, left=0.2, right=0.5, bottom=0.5))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    handle = widget._resize_handles(el)["corner"]
    center = handle.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(widget, QPoint(center.x() + 15, center.y() + 15))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(center.x() + 15, center.y() + 15))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["top"] == 0.2 and el["left"] == 0.2  # untouched
    assert el["right"] < 0.5 and el["bottom"] < 0.5  # box grew -> insets shrank
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["right"] == 0.5 and reverted["bottom"] == 0.5


def test_edit_page_widget_moving_a_highlight_shifts_left_top_up_and_right_bottom_down():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.3, left=0.3, right=0.4, bottom=0.4))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    body = QPoint(int(w * 0.35), int(h * 0.35))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 12, body.y() + 6))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 12, body.y() + 6))
    el = next(e for e in model.elements if e["id"] == el_id)
    dx, dy = 12 / w, 6 / h
    # Moving right/down must INCREASE left/top and DECREASE right/bottom -
    # a sign error here was caught during this plan's own verification.
    assert el["left"] == pytest.approx(0.3 + dx) and el["top"] == pytest.approx(0.3 + dy)
    assert el["right"] == pytest.approx(0.4 - dx) and el["bottom"] == pytest.approx(0.4 - dy)


def test_edit_page_widget_clicking_a_highlights_marker_removes_it():
    model = EditElementsModel()
    el_id = model.add(_highlight_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    marker = widget._marker_rect(el)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def test_edit_pdf_dialog_shape_mode_places_a_shape_and_exports_it(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]

    dlg._set_create_mode("shape")
    dlg._set_shape_type("ellipse")
    dlg._set_color("#00ff00")
    dlg._set_width_preset("thick")
    dlg._set_filled(True)
    assert page1.create_mode == "shape"
    assert page1.shape_type == "ellipse"
    assert page1.color == "#00ff00"
    assert page1.width_preset == "thick"
    assert page1.filled is True

    w, h = page1.width(), page1.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.5), int(h * 0.4))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(page1, end)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, end)
    assert len(dlg.model.elements) == 1
    assert dlg.model.elements[0]["shape"] == "ellipse" and dlg.model.elements[0]["width"] == 6

    params = dlg.gather_params()
    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    result_pix = result[0].get_pixmap()
    result.close()
    control = fitz.open(str(input_path))
    control_pix = control[0].get_pixmap()
    control.close()
    assert result_pix.samples != control_pix.samples


def test_edit_pdf_dialog_draw_and_highlight_modes_place_and_export_both(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()

    dlg._set_create_mode("draw")
    start = QPoint(int(w * 0.1), int(h * 0.1))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(page1, QPoint(int(w * 0.2), int(h * 0.2)))
    end = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mouseMove(page1, end)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, end)

    dlg._set_create_mode("highlight")
    start2 = QPoint(int(w * 0.5), int(h * 0.5))
    end2 = QPoint(int(w * 0.7), int(h * 0.6))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, start2)
    QTest.mouseMove(page1, end2)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, end2)

    assert len(dlg.model.elements) == 2
    types = {el["type"] for el in dlg.model.elements}
    assert types == {"stroke", "highlight"}

    params = dlg.gather_params()
    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    result_pix = result[0].get_pixmap()
    result.close()
    control = fitz.open(str(input_path))
    control_pix = control[0].get_pixmap()
    control.close()
    assert result_pix.samples != control_pix.samples


def test_edit_pdf_dialog_new_pages_inherit_the_current_shape_style(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path_a = tmp_path / "input_a.pdf"
    doc.save(str(input_path_a))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path_a)])
    dlg._set_create_mode("shape")
    dlg._set_shape_type("line")
    dlg._set_color("#abcdef")
    dlg._set_width_preset("thin")

    doc2 = fitz.open()
    doc2.new_page(width=595, height=842)
    doc2.new_page(width=595, height=842)
    input_path_b = tmp_path / "input_b.pdf"
    doc2.save(str(input_path_b))
    doc2.close()

    dlg.on_files_changed([str(input_path_b)])
    for widget in dlg._page_widgets:
        assert widget.create_mode == "shape"
        assert widget.shape_type == "line"
        assert widget.color == "#abcdef"
        assert widget.width_preset == "thin"


def test_edit_pdf_dialog_mode_buttons_are_mutually_exclusive_across_all_five(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    dlg._set_create_mode("highlight")
    assert dlg.highlight_btn.isChecked() is True
    assert dlg.new_text_btn.isChecked() is False
    assert dlg.image_btn.isChecked() is False
    assert dlg.draw_btn.isChecked() is False
    assert dlg.shapes_btn.isChecked() is False


def _single_page_pdf(tmp_path, name="input.pdf"):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _drag_body_past_top_left(widget, body):
    """Grabs an element by `body` and drags it into the widget's top-left
    corner - which, for an element created mid-page, is further than it can
    legally travel, so the move MUST clamp rather than run off the page.
    Deliberately (0, 1) and not (0, 0): QPoint(0, 0) is a NULL QPoint, and
    QTest.mouseMove silently substitutes the widget's centre for one."""
    corner = QPoint(0, 1)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, corner)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, corner)


def _assert_exports_cleanly(dlg, input_path):
    """Runs the REAL export path the dialog's Run button uses. edit_pdf
    validates every element and raises on the first bad coordinate, which
    fails the export of the whole document - so this is what actually
    catches an element dragged off the page."""
    params = dlg.gather_params()
    output_paths = dlg.run_operation([str(input_path)], params)
    assert os.path.exists(output_paths[0])


def test_edit_pdf_dialog_dragging_a_shape_off_the_page_clamps_and_still_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()
    el_id = dlg.model.add(_shape_element(page=1, x0=0.3, y0=0.3, x1=0.5, y1=0.45))

    _drag_body_past_top_left(page1, QPoint(int(w * 0.4), int(h * 0.37)))

    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    assert all(0 <= el[k] <= 1 for k in ("x0", "y0", "x1", "y1"))
    assert el["x0"] == pytest.approx(0.0) and el["y0"] == pytest.approx(0.0)
    assert el["x1"] - el["x0"] == pytest.approx(0.2)  # size preserved, not squashed
    assert el["y1"] - el["y0"] == pytest.approx(0.15)
    _assert_exports_cleanly(dlg, input_path)


def test_edit_pdf_dialog_dragging_a_stroke_off_the_page_clamps_and_still_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    page1.create_mode = "select"  # strokes are only selectable with the Select tool
    w, h = page1.width(), page1.height()
    points = [{"x": 0.3, "y": 0.3}, {"x": 0.35, "y": 0.4}, {"x": 0.45, "y": 0.35}]
    el_id = dlg.model.add(_stroke_element(page=1, points=points))

    _drag_body_past_top_left(page1, QPoint(int(w * 0.36), int(h * 0.35)))

    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    xs = [p["x"] for p in el["points"]]
    ys = [p["y"] for p in el["points"]]
    assert all(0 <= v <= 1 for v in xs + ys)
    assert min(xs) == pytest.approx(0.0) and min(ys) == pytest.approx(0.0)
    assert max(xs) - min(xs) == pytest.approx(0.15)  # whole stroke translated as one
    assert max(ys) - min(ys) == pytest.approx(0.1)
    _assert_exports_cleanly(dlg, input_path)


def test_edit_pdf_dialog_dragging_a_highlight_off_the_page_clamps_and_still_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()
    el_id = dlg.model.add(_highlight_element(page=1, top=0.3, left=0.3, right=0.4, bottom=0.4))

    _drag_body_past_top_left(page1, QPoint(int(w * 0.4), int(h * 0.4)))

    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    assert all(0 <= el[k] < 1 for k in ("top", "right", "bottom", "left"))
    assert el["left"] == pytest.approx(0.0) and el["top"] == pytest.approx(0.0)
    # insets move in opposite directions, so the box keeps its size
    assert 1 - el["left"] - el["right"] == pytest.approx(0.3)
    assert 1 - el["top"] - el["bottom"] == pytest.approx(0.3)
    _assert_exports_cleanly(dlg, input_path)


def test_edit_page_widget_a_clamped_drag_that_changes_nothing_pushes_no_undo_step():
    model = EditElementsModel()
    el_id = model.add(_shape_element(x0=0.0, y0=0.0, x1=0.2, y1=0.2))  # already at the corner
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    _drag_body_past_top_left(widget, QPoint(int(w * 0.1), int(h * 0.1)))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x0"] == pytest.approx(0.0) and el["x1"] == pytest.approx(0.2)
    # The drag clamped to a no-op, so undo must still reach past it to the
    # element's own creation rather than popping a junk step.
    model.undo()
    assert model.elements == []


def test_edit_page_widget_right_button_in_stroke_mode_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.5), int(h * 0.5))
    QTest.mousePress(widget, Qt.RightButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.RightButton, Qt.NoModifier, end)
    assert widget._create_drag is None
    assert model.elements == []


def test_edit_page_widget_right_button_during_a_left_drag_keeps_the_stroke():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.1), int(h * 0.1))
    mid = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.4), int(h * 0.4))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, mid)
    # A stray right-click partway through: it must not re-arm the gesture
    # at its own position, which used to discard everything drawn so far.
    QTest.mousePress(widget, Qt.RightButton, Qt.NoModifier, QPoint(int(w * 0.9), int(h * 0.9)))
    QTest.mouseRelease(widget, Qt.RightButton, Qt.NoModifier, QPoint(int(w * 0.9), int(h * 0.9)))
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "stroke"
    assert len(el["points"]) == 3  # start + both moves, none lost
    assert el["points"][0]["x"] == pytest.approx(start.x() / w)


def test_edit_pdf_dialog_draw_and_shape_widths_are_independent(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]

    dlg._set_create_mode("shape")
    dlg._set_width_preset("thick")
    assert dlg.shape_width_combo.currentText() == "thick"
    assert page1.width_preset == "thick"

    dlg._set_create_mode("draw")
    # The Draw combo must keep reading - and the pen must keep drawing at -
    # its OWN width, not the one just picked in Shapes.
    assert dlg.draw_width_combo.currentText() == "medium"
    assert page1.width_preset == "medium"

    w, h = page1.width(), page1.height()
    start = QPoint(int(w * 0.1), int(h * 0.1))
    end = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(page1, end)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, end)
    assert dlg.model.elements[0]["width"] == 3  # "medium", not the shape tool's 6


def test_edit_pdf_dialog_highlight_colour_defaults_to_amber_and_stays_its_own(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()

    dlg._set_create_mode("highlight")
    assert page1.color == "#ffd43b"
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.2), int(h * 0.2)))
    QTest.mouseMove(page1, QPoint(int(w * 0.5), int(h * 0.4)))
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.5), int(h * 0.4)))
    assert dlg.model.elements[0]["color"] == "#ffd43b"

    dlg._set_color("#00aa00")  # picked from the HIGHLIGHT row
    assert dlg._tool_colors["highlight"] == "#00aa00"
    assert dlg._tool_colors["shape"] == "#ff0000" and dlg._tool_colors["draw"] == "#ff0000"
    selected = [c for c, btn in dlg._swatch_buttons["highlight"] if "3px" in btn.styleSheet()]
    assert selected == ["#00aa00"]  # the row shows which swatch is active

    dlg._set_create_mode("shape")
    assert page1.color == "#ff0000"


def test_edit_pdf_dialog_file_loaded_in_draw_mode_gives_pages_stroke_mode(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    dlg = EditPdfDialog()
    dlg._set_create_mode("draw")
    dlg._set_color("#0000ff")
    dlg._set_width_preset("thin")

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "two_pages.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg.on_files_changed([str(input_path)])
    assert len(dlg._page_widgets) == 2
    for widget in dlg._page_widgets:
        # the toolbar says "draw"; the widget's own vocabulary is "stroke"
        assert widget.create_mode == "stroke"
        assert widget.color == "#0000ff"
        assert widget.width_preset == "thin"


def _run(index=0, text="Hello", font="Helvetica", size=14.0, bold=False, italic=False,
         top=0.1, left=0.2, right=0.5, bottom=0.8):
    return {"index": index, "text": text, "font": font, "size": size, "bold": bold,
            "italic": italic, "bbox": {"top": top, "left": left, "right": right, "bottom": bottom}}


def _text_edit_element(page=1, run_index=0, text="Edited", **extra):
    el = {"page": page, "type": "text_edit", "run_index": run_index,
          "segments": [{"text": text, "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]}
    el.update(extra)
    return el


def test_closest_base14_family_matches_the_web_apps_rules():
    assert closest_base14_family("Times-Roman") == "times"
    assert closest_base14_family("DejaVuSerif") == "times"
    assert closest_base14_family("Georgia") == "times"
    assert closest_base14_family("Courier-Bold") == "courier"
    assert closest_base14_family("Consolas") == "courier"
    assert closest_base14_family("LucidaMono") == "courier"
    assert closest_base14_family("Helvetica") == "helvetica"
    assert closest_base14_family("Arial") == "helvetica"
    assert closest_base14_family("") == "helvetica"
    assert closest_base14_family(None) == "helvetica"


def test_edit_model_stores_page_text_info_and_finds_runs():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0), _run(1, text="Second")], rotation=0, width_pt=595, height_pt=842)
    assert model.find_run(1, 1)["text"] == "Second"
    assert model.find_run(1, 9) is None
    assert model.find_run(2, 0) is None
    assert model.page_info[1] == {"rotation": 0, "width_pt": 595, "height_pt": 842}


def test_edit_model_text_edit_box_defaults_to_the_runs_own_box_and_moves_with_xy():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0, top=0.1, left=0.2, right=0.5, bottom=0.8)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    el = next(e for e in model.elements if e["id"] == el_id)
    box = model.text_edit_box(el)
    assert box == pytest.approx({"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.1})
    el.update(x=0.4, y=0.5)
    moved = model.text_edit_box(el)
    assert moved == pytest.approx({"x": 0.4, "y": 0.5, "width": 0.3, "height": 0.1})  # rotation 0: no swap
    assert model.text_edit_box({"page": 1, "type": "text_edit", "run_index": 9, "segments": []}) is None


def test_edit_model_text_edit_box_swaps_dimensions_in_points_when_moved_on_a_rotated_page():
    model = EditElementsModel()
    # displayed page 842 x 595 (a 90-degree page); the run is tall and narrow (sideways text)
    model.set_page_text_info(1, [_run(0, top=0.121, left=0.876, right=0.101, bottom=0.719)], rotation=90, width_pt=842, height_pt=595)
    el_id = model.add(_text_edit_element())
    el = next(e for e in model.elements if e["id"] == el_id)
    unmoved = model.text_edit_box(el)
    assert unmoved["width"] == pytest.approx(1 - 0.876 - 0.101)
    assert unmoved["height"] == pytest.approx(1 - 0.121 - 0.719)  # never swapped while unmoved
    el.update(x=0.3, y=0.3)
    moved = model.text_edit_box(el)
    w_pt, h_pt = unmoved["width"] * 842, unmoved["height"] * 595
    assert moved["width"] == pytest.approx(h_pt / 842)  # transposed extent, converted back to fractions
    assert moved["height"] == pytest.approx(w_pt / 595)


def test_edit_model_clamped_translate_for_text_edit_returns_only_xy_and_clamps_to_the_page():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0, top=0.1, left=0.2, right=0.5, bottom=0.8)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    el = next(e for e in model.elements if e["id"] == el_id)
    changes = model.clamped_translate(el, 0.1, 0.1)
    assert set(changes) == {"x", "y"}
    assert changes["x"] == pytest.approx(0.3) and changes["y"] == pytest.approx(0.2)
    far = model.clamped_translate(el, 5.0, 5.0)  # far past the bottom-right
    assert far["x"] == pytest.approx(1 - 0.3) and far["y"] == pytest.approx(1 - 0.1)
    away = model.clamped_translate(el, -5.0, -5.0)
    assert away["x"] == pytest.approx(0.0) and away["y"] == pytest.approx(0.0)


def test_edit_model_nudge_moves_a_text_edit_and_never_stores_width_or_height():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    model.nudge(el_id, 0.02, 0.0)
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(0.22) and el["y"] == pytest.approx(0.1)
    assert "width" not in el and "height" not in el
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert "x" not in reverted and "y" not in reverted  # nudge was its own undo step


def test_edit_model_text_edit_for_run_finds_the_pending_edit():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0), _run(1)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element(run_index=1))
    assert model.text_edit_for_run(1, 1)["id"] == el_id
    assert model.text_edit_for_run(1, 0) is None
    assert model.text_edit_for_run(2, 1) is None


def test_edit_model_copy_and_cut_are_complete_no_ops_for_a_text_edit():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    model.select(el_id)
    model.copy()
    assert model._clipboard is None
    model.cut()
    assert [e["id"] for e in model.elements] == [el_id]  # NOT deleted
    assert model.selected_id == el_id
    assert model.paste() is None


def _text_widget(model=None, runs=None, rotation=0, page=1, w=400, h=600):
    model = model or EditElementsModel()
    model.set_page_text_info(page, runs if runs is not None else [_run(0, text="Hello world", top=0.1, left=0.1, right=0.5, bottom=0.8)],
                             rotation=rotation, width_pt=595, height_pt=842)
    widget = EditPageWidget(model, page_number=page)
    widget.set_page_pixmap(QPixmap(w, h))
    widget.create_mode = "text"
    return model, widget


def _dclick_run(widget, run_index=0):
    run = widget.model.find_run(widget.page_number, run_index)
    b = run["bbox"]
    x = (b["left"] + (1 - b["right"])) / 2 * widget.width()
    y = (b["top"] + (1 - b["bottom"])) / 2 * widget.height()
    QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(y)))


def _fmt(family="helvetica", bold=False, italic=False, size=14.0, ppp=1.0):
    from PySide6.QtGui import QTextFormat
    f = QTextCharFormat()
    f.setFontFamilies([family])
    f.setFontWeight(QFont.Bold if bold else QFont.Normal)
    f.setFontItalic(italic)
    f.setProperty(QTextFormat.FontPixelSize, max(1, round(size * ppp)))
    f.setProperty(QTextFormat.UserProperty + 1, float(size))
    return f


_DEFAULT_STYLE = {"family": "helvetica", "bold": False, "italic": False, "size": 14.0}


def test_segments_from_document_walks_fragments_into_exact_segments():
    from PySide6.QtGui import QTextCursor
    doc = build_segments_document([], 1.0)
    cur = QTextCursor(doc)
    cur.insertText("Hello ", _fmt())
    cur.insertText("BOLD", _fmt(bold=True))
    cur.insertText(" and ", _fmt(italic=True))
    cur.insertText("plain", _fmt())
    cur.insertText("more", _fmt())  # identical neighbour - must merge
    cur.insertText("Mono", _fmt(family="courier", size=11.5))
    assert segments_from_document(doc, _DEFAULT_STYLE) == [
        {"text": "Hello ", "family": "helvetica", "bold": False, "italic": False, "size": 14.0},
        {"text": "BOLD", "family": "helvetica", "bold": True, "italic": False, "size": 14.0},
        {"text": " and ", "family": "helvetica", "bold": False, "italic": True, "size": 14.0},
        {"text": "plainmore", "family": "helvetica", "bold": False, "italic": False, "size": 14.0},
        {"text": "Mono", "family": "courier", "bold": False, "italic": False, "size": 11.5},
    ]


def test_segments_from_document_of_an_empty_document_is_one_empty_default_segment():
    doc = build_segments_document([], 1.0)
    assert segments_from_document(doc, _DEFAULT_STYLE) == [{"text": "", **_DEFAULT_STYLE}]


def test_build_segments_document_round_trips_segments_exactly():
    segs = [
        {"text": "a", "family": "times", "bold": True, "italic": False, "size": 12.0},
        {"text": "b", "family": "courier", "bold": False, "italic": True, "size": 9.5},
    ]
    doc = build_segments_document(segs, 0.534)
    assert segments_from_document(doc, _DEFAULT_STYLE) == segs


def test_segments_from_document_joins_multiple_blocks_with_a_single_space():
    from PySide6.QtGui import QTextCursor
    doc = build_segments_document([], 1.0)
    cur = QTextCursor(doc)
    cur.insertText("ab", _fmt())
    cur.insertBlock()
    cur.insertText("cd", _fmt())
    assert "".join(s["text"] for s in segments_from_document(doc, _DEFAULT_STYLE)) == "ab cd"


def test_double_click_on_a_run_in_edit_text_mode_opens_the_editor_seeded_with_the_run():
    model, widget = _text_widget()
    _dclick_run(widget)
    assert widget._run_editor is not None
    assert widget._run_editor.toPlainText() == "Hello world"
    assert model.elements == []  # opening adds nothing


def test_double_click_on_a_run_outside_edit_text_mode_does_nothing():
    model, widget = _text_widget()
    widget.create_mode = "new_text"
    _dclick_run(widget)
    assert widget._run_editor is None


def test_double_click_off_any_run_opens_nothing():
    model, widget = _text_widget()
    QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(widget.width() * 0.9), int(widget.height() * 0.9)))
    assert widget._run_editor is None


def test_opening_and_closing_an_untouched_run_editor_adds_no_element_and_no_undo_step():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget.commit_open_editors()
    assert widget._run_editor is None
    assert model.elements == []
    assert model._undo_stack == []


def test_editing_a_run_and_clicking_elsewhere_commits_a_text_edit_with_segments():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Brand new")
    # a real click on empty page space is the production commit path
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(widget.width() * 0.9), int(widget.height() * 0.9)))
    assert widget._run_editor is None
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "text_edit" and el["run_index"] == 0 and el["page"] == 1
    assert el["segments"] == [{"text": "Brand new", "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]
    assert "x" not in el and "y" not in el and "width" not in el and "height" not in el


def test_a_run_editor_edits_the_existing_text_edit_instead_of_adding_a_second():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "First")
    widget.commit_open_editors()
    _dclick_run(widget)
    assert widget._run_editor.toPlainText() == "First"  # reopened from the stored segments
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Second")
    widget.commit_open_editors()
    assert len(model.elements) == 1  # exactly one text_edit per run
    assert model.elements[0]["segments"][0]["text"] == "Second"


def test_editing_an_existing_text_edit_is_undoable_back_to_the_previous_text():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "First")
    widget.commit_open_editors()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Second")
    widget.commit_open_editors()
    model.undo()
    assert model.elements[0]["segments"][0]["text"] == "First"  # commit-before-mutate
    model.undo()
    assert model.elements == []


def test_reopening_a_styled_text_edit_rebuilds_its_rich_content():
    model, widget = _text_widget()
    segs = [
        {"text": "Hi ", "family": "helvetica", "bold": False, "italic": False, "size": 14.0},
        {"text": "there", "family": "times", "bold": True, "italic": True, "size": 12.0},
    ]
    model.add({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs})
    _dclick_run(widget)
    assert segments_from_document(widget._run_editor.document(), _DEFAULT_STYLE) == segs


def test_an_intentionally_emptied_run_commits_as_a_real_erase():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClick(widget._run_editor, Qt.Key_Delete)
    widget.commit_open_editors()
    assert len(model.elements) == 1
    assert model.elements[0]["segments"] == [{"text": "", "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]


def test_apply_run_style_restyles_only_the_selection():
    from PySide6.QtGui import QTextCursor
    model, widget = _text_widget(runs=[_run(0, text="abcdef", top=0.1, left=0.1, right=0.5, bottom=0.8)])
    _dclick_run(widget)
    cur = widget._run_editor.textCursor()
    cur.setPosition(2)
    cur.setPosition(4, QTextCursor.KeepAnchor)
    widget._run_editor.setTextCursor(cur)
    widget.apply_run_style(bold=True)
    widget.commit_open_editors()
    assert [(s["text"], s["bold"]) for s in model.elements[0]["segments"]] == [("ab", False), ("cd", True), ("ef", False)]


def test_apply_run_style_with_no_selection_styles_what_is_typed_next():
    model, widget = _text_widget(runs=[_run(0, text="", top=0.1, left=0.1, right=0.5, bottom=0.8)])
    _dclick_run(widget)
    widget.apply_run_style(bold=True, family="times", size=20)
    QTest.keyClicks(widget._run_editor, "typed")
    widget.commit_open_editors()
    assert model.elements[0]["segments"] == [{"text": "typed", "family": "times", "bold": True, "italic": False, "size": 20.0}]


def test_revert_run_editor_discards_the_pending_edit_and_reseeds_from_the_run():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Changed")
    widget.commit_open_editors()
    assert len(model.elements) == 1
    _dclick_run(widget)
    widget.revert_run_editor()
    assert model.elements == []
    assert widget._run_editor.toPlainText() == "Hello world"  # editor still open, reseeded
    widget.commit_open_editors()
    assert model.elements == []  # reverted and unchanged: still nothing


def test_opening_a_run_editor_and_moving_its_cursor_emit_the_style_row_signal():
    model, widget = _text_widget()
    seen = []
    widget.run_editor_cursor_moved.connect(lambda: seen.append(1))
    _dclick_run(widget)
    assert len(seen) >= 1  # emitted on open so the style row shows the run's style straight away
    before = len(seen)
    cur = widget._run_editor.textCursor()
    cur.setPosition(3)
    widget._run_editor.setTextCursor(cur)
    assert len(seen) > before


def test_run_editor_ignores_the_return_key():
    model, widget = _text_widget()
    _dclick_run(widget)
    QTest.keyClick(widget._run_editor, Qt.Key_Return)
    QTest.keyClick(widget._run_editor, Qt.Key_Enter)
    assert widget._run_editor.document().blockCount() == 1


def test_a_text_edit_is_selectable_and_movable_and_the_move_is_clamped_and_undoable():
    model, widget = _text_widget()
    el_id = model.add(_text_edit_element())
    w, h = widget.width(), widget.height()
    box = model.text_edit_box(model.elements[0])
    body = QPoint(int((box["x"] + box["width"] / 2) * w), int((box["y"] + box["height"] / 2) * h))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 30, body.y() + 20))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 30, body.y() + 20))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(box["x"] + 30 / w) and el["y"] == pytest.approx(box["y"] + 20 / h)
    assert "width" not in el and "height" not in el
    assert model.selected_id == el_id
    model.undo()
    assert "x" not in model.elements[0]  # back to un-moved

    # drag far past the top-left: must clamp to the page, not leave it
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(1, 1))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    el = model.elements[0]
    assert 0 <= el["x"] <= 1 - box["width"] + 1e-9 and 0 <= el["y"] <= 1 - box["height"] + 1e-9


def test_a_zero_movement_click_on_a_text_edit_pushes_no_undo_step():
    model, widget = _text_widget()
    model.add(_text_edit_element())
    before = len(model._undo_stack)
    box = model.text_edit_box(model.elements[0])
    pt = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, pt)
    assert len(model._undo_stack) == before
    assert "x" not in model.elements[0]


def test_a_text_edit_dragged_against_its_own_clamp_does_not_pin_xy_without_a_move():
    # a box already flush with the top-left corner: dragging further up-left
    # changes nothing, so it must not add x/y or push an undo step
    model, widget = _text_widget(runs=[_run(0, top=0.0, left=0.0, right=0.7, bottom=0.9)])
    model.add(_text_edit_element())
    before = len(model._undo_stack)
    pt = QPoint(int(0.15 * widget.width()), int(0.05 * widget.height()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.mouseMove(widget, QPoint(1, 1))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    assert "x" not in model.elements[0] and len(model._undo_stack) == before


def test_a_text_edits_marker_click_removes_it_and_restores_the_original_run():
    model, widget = _text_widget()
    model.add(_text_edit_element())
    model.select(model.elements[0]["id"])
    marker = widget._marker_rect(model.elements[0])
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def _painted_text_edit_image(text):
    model, widget = _text_widget()
    pm = QPixmap(400, 600)
    pm.fill(Qt.black)  # a dark "page" so the white-out is unmistakable
    widget.set_page_pixmap(pm)
    run_box = model.find_run(1, 0)["bbox"]
    model.add({"page": 1, "type": "text_edit", "run_index": 0,
               "segments": [{"text": text, "family": "helvetica", "bold": False, "italic": False, "size": 40.0}]})
    model.select(None)
    rect = widget._run_bbox_rect_px(model.find_run(1, 0))
    return widget.grab().toImage(), rect, run_box


def _count_dark(img, rect):
    return sum(1 for x in range(rect.left(), rect.right() + 1) for y in range(rect.top(), rect.bottom() + 1)
               if img.pixelColor(x, y).lightness() < 128)


def test_a_text_edit_paints_the_replacement_and_whites_out_the_original_run():
    img, rect, run_box = _painted_text_edit_image("WWWW")
    assert _count_dark(img, rect) > 0  # the replacement text is really drawn (dark on the white-out)
    # just outside the original run bbox the dark page is untouched
    assert img.pixelColor(rect.left() - 3, rect.top() - 3).lightness() < 50
    assert img.pixelColor(rect.right() + 3, rect.bottom() + 3).lightness() < 50


def test_an_empty_text_edit_leaves_the_run_area_fully_white():
    img, rect, run_box = _painted_text_edit_image("")
    assert _count_dark(img, QRect(rect.left(), rect.top(), rect.width() - 1, rect.height() - 1)) == 0
    assert img.pixelColor(rect.left() + 2, rect.top() + 2).lightness() > 200


def test_text_edit_elements_paint_before_other_elements_like_the_export_applies_them():
    model, widget = _text_widget()
    pm = QPixmap(400, 600)
    pm.fill(Qt.black)
    widget.set_page_pixmap(pm)
    run_box = model.find_run(1, 0)["bbox"]
    # a filled red rectangle covering the run, added BEFORE the text_edit in the array
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0,
               "color": "#ff0000", "width": 1, "filled": True})
    model.add({"page": 1, "type": "text_edit", "run_index": 0,
               "segments": [{"text": "", "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]})
    model.select(None)
    img = widget.grab().toImage()
    cx = int(((run_box["left"] + (1 - run_box["right"])) / 2) * 400)
    cy = int(((run_box["top"] + (1 - run_box["bottom"])) / 2) * 600)
    c = img.pixelColor(cx, cy)
    assert c.red() > 200 and c.green() < 60  # the shape is on top of the white-out, as in the export


def test_a_run_with_a_pending_edit_still_opens_by_double_click_on_its_element():
    model, widget = _text_widget()
    model.add(_text_edit_element(text="Pending"))
    box = model.text_edit_box(model.elements[0])
    pt = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, pt)
    assert widget._run_editor is not None and widget._run_editor.toPlainText() == "Pending"


def test_run_edit_move_and_export_through_the_real_core(tmp_path):
    from app.core.pdf_ops import edit_pdf, extract_text_runs, get_page_size

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "First line of text", fontname="helv", fontsize=14)
    page.insert_text((72, 160), "Second line", fontname="helv", fontsize=12)
    src = tmp_path / "in.pdf"
    doc.save(str(src))
    doc.close()

    runs = extract_text_runs(str(src), 1)
    w_pt, h_pt = get_page_size(str(src), 1)
    model, widget = _text_widget(runs=runs)
    widget.px_per_pt = 400 / w_pt

    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Edited")
    widget.commit_open_editors()

    # drag it hard toward the top-left corner: must clamp, and must still export
    box = model.text_edit_box(model.elements[0])
    body = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(1, 1))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    el = model.elements[0]
    assert 0 <= el["x"] <= 1 and 0 <= el["y"] <= 1

    out = tmp_path / "out.pdf"
    elements = [{k: v for k, v in e.items() if k != "id"} for e in model.elements]
    edit_pdf(str(src), str(out), elements, {})
    result = fitz.open(str(out))
    text = result[0].get_text()
    result.close()
    assert "Edited" in text
    assert "First line of text" not in text  # the original run was erased
    assert "Second line" in text             # untouched runs survive


def test_pasted_rich_text_never_puts_a_non_base14_family_into_a_segment():
    from PySide6.QtCore import QMimeData
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    mime = QMimeData()
    mime.setText("Pasted")  # real clipboards carry plain text alongside the HTML
    mime.setHtml('<span style="font-family:Calibri; font-size:30pt">Pasted</span>')
    widget._run_editor.insertFromMimeData(mime)
    widget.commit_open_editors()
    segs = model.elements[0]["segments"]
    assert "".join(s["text"] for s in segs) == "Pasted"
    assert all(s["family"] in ("helvetica", "times", "courier") for s in segs)


def test_segments_from_document_snaps_foreign_families_to_base14():
    from PySide6.QtGui import QTextCursor
    doc = build_segments_document([], 1.0)
    cur = QTextCursor(doc)
    cur.insertText("a", _fmt(family="Calibri"))
    cur.insertText("b", _fmt(family="Georgia"))
    cur.insertText("c", _fmt(family="Consolas"))
    assert [s["family"] for s in segments_from_document(doc, _DEFAULT_STYLE)] == ["helvetica", "times", "courier"]


def test_reopening_and_closing_an_existing_text_edit_untouched_pushes_no_undo_step():
    model, widget = _text_widget()
    model.add(_text_edit_element(text="Pending"))
    model.add({"page": 1, "type": "shape", "shape": "line", "x0": 0.1, "y0": 0.9, "x1": 0.2, "y1": 0.95,
               "color": "#ff0000", "width": 1, "filled": False})
    model.undo()  # redo stack now non-empty
    assert len(model._redo_stack) == 1
    undo_n, redo_n = len(model._undo_stack), len(model._redo_stack)
    _dclick_run(widget)
    widget.commit_open_editors()
    assert (len(model._undo_stack), len(model._redo_stack)) == (undo_n, redo_n)
    assert len(model.elements) == 1


def test_a_run_with_a_nbsp_opened_and_closed_untouched_adds_nothing():
    model, widget = _text_widget(runs=[_run(0, text="Hello\u00a0world", top=0.1, left=0.1, right=0.5, bottom=0.8)])
    _dclick_run(widget)
    widget.commit_open_editors()
    assert model.elements == [] and model._undo_stack == []


def _export(model, src, out):
    from app.core.pdf_ops import edit_pdf
    elements = [{k: v for k, v in e.items() if k != "id"} for e in model.elements]
    edit_pdf(str(src), str(out), elements, {})
    result = fitz.open(str(out))
    text = result[0].get_text()
    result.close()
    return text


def _two_run_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "First line of text", fontname="helv", fontsize=14)
    page.insert_text((72, 160), "Second line", fontname="helv", fontsize=12)
    src = tmp_path / "in.pdf"
    doc.save(str(src))
    doc.close()
    return src


def _model_for(src):
    from app.core.pdf_ops import extract_text_runs, get_page_size, get_page_rotation
    model = EditElementsModel()
    w, h = get_page_size(str(src), 1)
    model.set_page_text_info(1, extract_text_runs(str(src), 1), get_page_rotation(str(src), 1), w, h)
    return model


def test_nudging_a_text_edit_to_the_page_edge_stays_in_bounds_and_exports(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    el_id = model.add(_text_edit_element(text="Nudged"))
    start = model.text_edit_box(next(e for e in model.elements if e["id"] == el_id))
    for _ in range(400):  # far more than enough to hit the right edge
        model.nudge(el_id, 0.02, 0.02)
    el = next(e for e in model.elements if e["id"] == el_id)
    box = model.text_edit_box(el)
    assert box["x"] + box["width"] <= 1 + 1e-9 and box["y"] + box["height"] <= 1 + 1e-9
    assert 0 <= el["x"] <= 1 and 0 <= el["y"] <= 1
    assert "width" not in el and "height" not in el
    assert "x" in el and "y" in el
    assert el["x"] != start["x"] and el["y"] != start["y"]  # it really moved
    assert box["x"] + box["width"] == pytest.approx(1) and box["y"] + box["height"] == pytest.approx(1)
    text = _export(model, src, tmp_path / "out.pdf")
    assert "Nudged" in text and "First line of text" not in text


def test_undo_and_redo_of_a_text_edit_round_trip_through_export(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add(_text_edit_element(text="Undone"))
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
               "color": "#ff0000", "width": 3, "filled": False})
    model.undo()  # removes the shape
    model.undo()  # removes the text_edit
    assert model.elements == []
    model.redo()
    assert len(model.elements) == 1 and model.elements[0]["type"] == "text_edit"
    text = _export(model, src, tmp_path / "o.pdf")
    assert "Undone" in text and "First line of text" not in text


def test_a_text_edit_and_a_shape_on_the_same_page_export_together(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
               "color": "#ff0000", "width": 3, "filled": False})
    model.add(_text_edit_element(text="With shape"))
    text = _export(model, src, tmp_path / "o.pdf")
    assert "With shape" in text and "Second line" in text
    assert "First line of text" not in text


def test_reordering_a_text_edit_never_breaks_the_export(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
               "color": "#ff0000", "width": 3, "filled": False})
    te = model.add(_text_edit_element(text="Reordered"))
    def order():
        return [e["type"] for e in model.elements if e["page"] == 1]
    model.reorder(te, "back")
    assert order() == ["text_edit", "shape"]
    model.reorder(te, "forward")
    assert order() == ["shape", "text_edit"]
    model.reorder(te, "backward")
    assert order() == ["text_edit", "shape"]
    model.reorder(te, "front")
    assert order() == ["shape", "text_edit"]
    text = _export(model, src, tmp_path / "o.pdf")
    assert "Reordered" in text and "First line of text" not in text


def test_two_different_runs_each_get_their_own_text_edit_and_both_export(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add(_text_edit_element(run_index=0, text="One"))
    model.add(_text_edit_element(run_index=1, text="Two"))
    text = _export(model, src, tmp_path / "o.pdf")
    assert "One" in text and "Two" in text
    assert "First line of text" not in text and "Second line" not in text


def _dialog_with_text(tmp_path, pages=1):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "First line of text", fontname="helv", fontsize=14)
        page.insert_text((72, 160), "Second line", fontname="tiro", fontsize=12)
    src = tmp_path / "in.pdf"
    doc.save(str(src))
    doc.close()
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    return dlg, src


def test_edit_pdf_dialog_loads_each_pages_text_runs_and_scale_on_file_open(tmp_path):
    dlg, src = _dialog_with_text(tmp_path, pages=2)
    assert [r["text"] for r in dlg.model.text_runs[1]] == ["First line of text", "Second line"]
    assert dlg.model.page_info[2]["width_pt"] == 595 and dlg.model.page_info[2]["height_pt"] == 842
    assert dlg._page_widgets[0].px_per_pt == pytest.approx(dlg._page_widgets[0].width() / 595)


def test_edit_pdf_dialog_a_page_whose_runs_cannot_be_read_still_loads_without_runs(tmp_path, monkeypatch):
    from app.core.errors import PDFError
    import app.ui.dialogs.edit_dialogs as mod
    dlg, src = _dialog_with_text(tmp_path)

    def boom(path, page):
        raise PDFError("no text layer")
    monkeypatch.setattr(mod, "extract_text_runs", boom)
    dlg.on_files_changed([str(src)])
    assert len(dlg._page_widgets) == 1
    assert 1 in dlg.model.text_runs and dlg.model.text_runs[1] == []
    assert dlg.model.page_info[1]["width_pt"] == 0
    widget = dlg._page_widgets[0]
    dlg._set_create_mode("text")
    QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(widget.width() // 2, widget.height() // 2))
    assert widget._run_editor is None and widget._text_editor is None


def test_edit_pdf_dialog_edit_text_mode_button_is_mutually_exclusive_with_the_others(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    assert dlg.edit_text_btn.isChecked() is True
    for other in (dlg.new_text_btn, dlg.image_btn, dlg.draw_btn, dlg.shapes_btn, dlg.highlight_btn):
        assert other.isChecked() is False
    assert dlg._page_widgets[0].create_mode == "text"
    assert dlg._text_options.isHidden() is False
    dlg._set_create_mode("shape")
    assert dlg.edit_text_btn.isChecked() is False and dlg._text_options.isHidden() is True


def test_edit_pdf_dialog_pages_opened_while_edit_text_is_active_inherit_that_mode(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    dlg.on_files_changed([str(src)])
    assert dlg._page_widgets[0].create_mode == "text"


def test_edit_pdf_dialog_edit_a_run_and_export_through_the_real_ui_path(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Rewritten")
    # the user clicks straight on Run - no click back on the page first
    params = dlg.gather_params()
    assert widget._run_editor is None  # gather_params committed the open editor
    assert [e["type"] for e in dlg.model.elements] == ["text_edit"]
    out = dlg.run_operation([str(src)], params)
    result = fitz.open(out[0])
    text = result[0].get_text()
    result.close()
    assert "Rewritten" in text and "First line of text" not in text and "Second line" in text


def test_edit_pdf_dialog_typed_new_text_is_not_lost_when_run_is_clicked_first(tmp_path):
    # Phase 6A shipped with this bug: a new_text draft only committed on the
    # next click on the PAGE, so clicking Run first silently dropped it.
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("new_text")
    widget = dlg._page_widgets[0]
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(widget.width() * 0.5), int(widget.height() * 0.6)))
    QTest.keyClicks(widget._text_editor, "Typed then Run")
    params = dlg.gather_params()
    assert widget._text_editor is None
    assert [e["type"] for e in dlg.model.elements] == ["new_text"]
    assert params["elements"][0]["text"] == "Typed then Run"


def test_edit_pdf_dialog_toolbar_buttons_commit_an_open_editor_before_acting(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Committed by button")
    dlg._toolbar_action("undo")  # a real toolbar click, not the (suppressed) keyboard shortcut
    assert widget._run_editor is None
    # commit pushed the edit, then undo took it back out
    assert dlg.model.elements == []


def test_edit_pdf_dialog_keyboard_shortcuts_stay_suppressed_while_a_run_editor_is_open(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    el_id = dlg.model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
                           "color": "#ff0000", "width": 3, "filled": False})
    dlg.model.select(el_id)
    dlg._handle_shortcut("delete")  # a keystroke that belongs to the text editor
    assert len(dlg.model.elements) == 1
    assert widget._run_editor is not None


def test_edit_pdf_dialog_style_row_restyles_the_selection_and_reflects_the_cursor(tmp_path):
    from PySide6.QtGui import QTextCursor
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    cur = widget._run_editor.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, QTextCursor.KeepAnchor)
    widget._run_editor.setTextCursor(cur)
    dlg.text_bold_btn.click()
    dlg.text_family_combo.setCurrentText("courier")
    dlg.text_size_spin.setValue(20)
    dlg.text_italic_btn.click()
    widget.commit_open_editors()
    first = dlg.model.elements[0]["segments"][0]
    assert first["text"] == "First" and first["bold"] is True and first["italic"] is True
    assert first["family"] == "courier" and first["size"] == 20.0
    # the rest of the run kept the run's own style
    assert dlg.model.elements[0]["segments"][1]["bold"] is False


def test_edit_pdf_dialog_style_row_follows_the_cursor_position(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    model = dlg.model
    model.add({"page": 1, "type": "text_edit", "run_index": 1, "segments": [
        {"text": "Plain ", "family": "helvetica", "bold": False, "italic": False, "size": 12.0},
        {"text": "Loud", "family": "times", "bold": True, "italic": False, "size": 18.0}]})
    _dclick_run(widget, 1)
    cur = widget._run_editor.textCursor()
    cur.setPosition(9)  # inside "Loud"
    widget._run_editor.setTextCursor(cur)
    dlg._sync_text_style_row()
    assert dlg.text_bold_btn.isChecked() is True
    assert dlg.text_family_combo.currentText() == "times"
    assert dlg.text_size_spin.value() == 18


def test_edit_pdf_dialog_revert_button_restores_the_original_run(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Changed")
    widget.commit_open_editors()
    _dclick_run(widget, 0)
    dlg.text_revert_btn.click()
    assert dlg.model.elements == []
    assert widget._run_editor.toPlainText() == "First line of text"


def test_edit_pdf_dialog_a_text_edit_moved_by_mouse_still_exports(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Dragged")
    widget.commit_open_editors()
    box = dlg.model.text_edit_box(dlg.model.elements[0])
    body = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(widget.width() - 2, widget.height() - 2))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(widget.width() - 2, widget.height() - 2))
    el = dlg.model.elements[0]
    assert 0 <= el["x"] <= 1 and 0 <= el["y"] <= 1 and "width" not in el
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    assert "Dragged" in result[0].get_text()
    result.close()


def test_edit_pdf_dialog_mixed_styling_end_to_end_lands_in_the_exported_pdf(tmp_path):
    from PySide6.QtGui import QTextCursor
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Plain and BOLD")
    cur = widget._run_editor.textCursor()
    cur.setPosition(10)
    cur.setPosition(14, QTextCursor.KeepAnchor)
    widget._run_editor.setTextCursor(cur)
    dlg.text_bold_btn.click()
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    spans = [s for b in result[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    result.close()
    by_text = {s["text"].strip(): s for s in spans}
    assert "Plain and" in by_text and "BOLD" in by_text
    assert by_text["BOLD"]["flags"] & 16          # bold font flag
    assert not by_text["Plain and"]["flags"] & 16

def test_nudging_a_text_edit_through_the_dialogs_arrow_keys_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    src = _two_run_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    el_id = dlg.model.add(_text_edit_element(text="Arrow nudged"))
    dlg.model.select(el_id)
    QTest.keyClick(dlg, Qt.Key_Right)
    QTest.keyClick(dlg, Qt.Key_Down, Qt.ShiftModifier)
    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    box = dlg.model.text_edit_box({**el, "x": None, "y": None})  # the run's own top-left
    assert el["x"] == pytest.approx(box["x"] + 0.004)
    assert el["y"] == pytest.approx(box["y"] + 0.02)
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    assert "Arrow nudged" in result[0].get_text()
    result.close()


def test_deleting_a_text_edit_via_the_dialog_restores_the_original_run_on_export(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    src = _two_run_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    dlg.model.add(_text_edit_element(text="Temporary"))
    dlg.model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
                   "color": "#ff0000", "width": 3, "filled": False})  # export needs some element left
    text_edit_id = dlg.model.elements[0]["id"]
    dlg.model.select(text_edit_id)
    dlg._handle_shortcut("delete")
    assert all(e["type"] != "text_edit" for e in dlg.model.elements)
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    text = result[0].get_text()
    result.close()
    assert "First line of text" in text and "Temporary" not in text


def test_edit_pdf_dialog_size_spin_does_not_track_keystrokes(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    assert dlg.text_size_spin.keyboardTracking() is False


def test_edit_pdf_dialog_typing_a_multi_digit_size_never_leaks_digits_into_the_run_text(tmp_path):
    from PySide6.QtGui import QTextCursor
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    cur = widget._run_editor.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, QTextCursor.KeepAnchor)
    widget._run_editor.setTextCursor(cur)
    before = widget._run_editor.toPlainText()
    dlg.text_size_spin.selectAll()
    QTest.keyClicks(dlg.text_size_spin, "100")  # no Enter: nothing may have been applied or leaked
    assert widget._run_editor.toPlainText() == before
    # committing the value (what Enter/focus-out does) applies it once, text untouched
    dlg.text_size_spin.setValue(100)
    assert widget._run_editor.toPlainText() == before
    widget.commit_open_editors()
    assert dlg.model.elements[0]["segments"][0]["size"] == 100.0


# ---------------------------------------------------------------------------
# Final-review fixes
# ---------------------------------------------------------------------------

_LONG_LINE = ("The quick brown fox jumps over the lazy dog. The quick brown fox jumps over "
              "the lazy dog. Pack my box with five")


def _rotated_long_line_pdf(tmp_path, rotation):
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((30, 300), _LONG_LINE, fontname="helv", fontsize=14)
    page.set_rotation(rotation)
    src = tmp_path / f"rot{rotation}.pdf"
    doc.save(str(src))
    doc.close()
    return src


def _rotated_dialog(tmp_path, rotation):
    from app.core.pdf_ops import extract_text_runs
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    src = _rotated_long_line_pdf(tmp_path, rotation)
    run = extract_text_runs(str(src), 1)[0]
    hfrac = 1 - run["bbox"]["top"] - run["bbox"]["bottom"]
    assert hfrac > 0.72  # spans > 71% of the displayed height once rotated
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    dlg._set_create_mode("text")
    return dlg, src


def _assert_in_page(model, el_id):
    el = next(e for e in model.elements if e["id"] == el_id)
    assert 0 <= el["x"] <= 1 and 0 <= el["y"] <= 1
    assert "width" not in el and "height" not in el
    box = model.text_edit_box(el)
    assert box["width"] <= 1 and box["height"] <= 1


def _drag_element(widget, el, dx, dy):
    start = widget._element_rect_px(el).center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, start + QPoint(dx // 2, dy // 2))
    QTest.mouseMove(widget, start + QPoint(dx, dy))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, start + QPoint(dx, dy))


@pytest.mark.parametrize("rotation", [90, 270])
def test_moving_and_nudging_a_text_edit_twice_on_a_rotated_page_stays_in_bounds_and_exports(tmp_path, rotation):
    dlg, src = _rotated_dialog(tmp_path, rotation)
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Rotated rewrite")
    widget.commit_open_editors()
    el_id = dlg.model.elements[0]["id"]
    # two mouse drags in different directions
    for dx, dy in ((-30, 40), (25, -20)):
        el = next(e for e in dlg.model.elements if e["id"] == el_id)
        _drag_element(widget, el, dx, dy)
        _assert_in_page(dlg.model, el_id)
    # three nudges in different directions
    for key, mod in ((Qt.Key_Left, Qt.ShiftModifier), (Qt.Key_Down, Qt.NoModifier), (Qt.Key_Up, Qt.ShiftModifier)):
        dlg.model.select(el_id)
        QTest.keyClick(dlg, key, mod)
        _assert_in_page(dlg.model, el_id)
    assert "x" in dlg.model.elements[0]
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    assert "Rotated rewrite" in result[0].get_text()
    result.close()


@pytest.mark.parametrize("rotation", [90, 270])
def test_a_rotated_long_runs_box_never_exceeds_the_page_and_translate_never_leaves_it(tmp_path, rotation):
    dlg, src = _rotated_dialog(tmp_path, rotation)
    model = dlg.model
    el_id = model.add(_text_edit_element(text="Long"))
    el = next(e for e in model.elements if e["id"] == el_id)
    el.update({"x": 0.5, "y": 0.5})
    box = model.text_edit_box(el)
    assert box["width"] <= 1.0 and box["height"] <= 1.0
    assert box["width"] == pytest.approx(1.0)  # the unclamped swap would exceed 1
    for dx, dy in ((0.9, 0.9), (-0.9, -0.9), (0.3, -0.2), (-2, 2)):
        out = model.clamped_translate(el, dx, dy)
        assert 0 <= out["x"] <= 1 and 0 <= out["y"] <= 1
        assert set(out) == {"x", "y"}


def test_nudging_a_text_edit_with_an_unknown_run_pushes_no_undo_step():
    model = EditElementsModel()
    el_id = model.add(_text_edit_element(run_index=99))
    before = len(model._undo_stack)
    model.nudge(el_id, 0.1, 0.1)
    assert len(model._undo_stack) == before
    assert "x" not in model.elements[0]
    model.nudge("no-such-id", 0.1, 0.1)
    assert len(model._undo_stack) == before


def test_unselected_text_edit_has_no_invisible_delete_hotspot():
    model, widget = _text_widget()
    model.add(_text_edit_element())
    model.select(None)
    marker = widget._marker_rect(model.elements[0])
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert len(model.elements) == 1
    assert model.selected_id == model.elements[0]["id"]  # it selected instead
    # now selected, its marker is live and still deletes
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def _two_page_dialog(tmp_path):
    dlg, src = _dialog_with_text(tmp_path, pages=2)
    dlg._set_create_mode("text")
    return dlg, src


def test_opening_a_run_editor_on_page_two_commits_page_ones_editor(tmp_path):
    dlg, src = _two_page_dialog(tmp_path)
    w1, w2 = dlg._page_widgets
    _dclick_run(w1, 0)
    w1._run_editor.selectAll()
    QTest.keyClicks(w1._run_editor, "Page one edit")
    _dclick_run(w2, 0)
    assert w1._run_editor is None
    assert w2._run_editor is not None
    assert sum(1 for w in dlg._page_widgets if w._run_editor is not None) == 1
    assert dlg._open_run_widget() is w2
    assert [(e["page"], e["segments"][0]["text"]) for e in dlg.model.elements] == [(1, "Page one edit")]
    # the style row acts on page 2's selection only
    w2._run_editor.selectAll()
    dlg.text_bold_btn.click()
    w2.commit_open_editors()
    page2 = next(e for e in dlg.model.elements if e["page"] == 2)
    assert all(seg["bold"] for seg in page2["segments"])
    page1 = next(e for e in dlg.model.elements if e["page"] == 1)
    assert not any(seg["bold"] for seg in page1["segments"])
    assert not dlg._any_text_editor_open()
    dlg.model.select(page2["id"])
    QTest.keyClick(dlg, Qt.Key_Right)
    assert next(e for e in dlg.model.elements if e["id"] == page2["id"]).get("x") is not None


def test_clicking_page_two_commits_page_ones_new_text_editor(tmp_path):
    dlg, src = _two_page_dialog(tmp_path)
    dlg._set_create_mode("new_text")
    w1, w2 = dlg._page_widgets
    QTest.mouseClick(w1, Qt.LeftButton, Qt.NoModifier, QPoint(60, 60))
    assert w1._text_editor is not None
    QTest.keyClicks(w1._text_editor, "Draft one")
    QTest.mouseClick(w2, Qt.LeftButton, Qt.NoModifier, QPoint(60, 300))
    assert w1._text_editor is None
    assert [e["text"] for e in dlg.model.elements if e["type"] == "new_text" and e["page"] == 1] == ["Draft one"]
    assert w2._text_editor is not None
    assert sum(1 for w in dlg._page_widgets if w._text_editor is not None) == 1


def test_reopening_a_file_with_an_editor_open_leaves_no_editor_open(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    assert dlg._any_text_editor_open()
    dlg.on_files_changed([str(src)])
    assert not dlg._any_text_editor_open()
    assert len(dlg._page_widgets) == 1


def test_arrow_nudge_is_a_no_op_on_a_shape_while_a_run_editor_is_open_then_works(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    shape_id = dlg.model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5,
                              "x1": 0.3, "y1": 0.6, "color": "#ff0000", "width": 3, "filled": False})
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    dlg.model.select(shape_id)
    before = dict(next(e for e in dlg.model.elements if e["id"] == shape_id))
    QTest.keyClick(dlg, Qt.Key_Right)
    assert next(e for e in dlg.model.elements if e["id"] == shape_id) == before
    widget.commit_open_editors()
    dlg.model.select(shape_id)
    QTest.keyClick(dlg, Qt.Key_Right)
    now = next(e for e in dlg.model.elements if e["id"] == shape_id)
    assert now["x0"] == pytest.approx(before["x0"] + 0.004)


def test_revert_restores_the_run_editors_default_font():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget.revert_run_editor()
    run = model.find_run(1, 0)
    assert widget._run_editor.document().defaultFont().pixelSize() == max(1, round(run["size"] * widget.px_per_pt))


def test_preview_segments_shrink_an_over_wide_replacement_like_the_export():
    from app.core.pdf_ops import text_edit_final_sizes
    model, widget = _text_widget(runs=[_run(0, text="Hi", top=0.1, left=0.1, right=0.8, bottom=0.85, size=14.0)])
    segs = [{"text": "A replacement far wider than the tiny original run", "family": "helvetica",
             "bold": False, "italic": False, "size": 14.0}]
    el_id = model.add({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs})
    el = next(e for e in model.elements if e["id"] == el_id)
    run = model.find_run(1, 0)
    preview = widget._text_edit_preview_segments(el, run)
    original_width = (1 - 0.1 - 0.8) * 595  # displayed width == raw width at rotation 0
    assert preview[0]["size"] == pytest.approx(text_edit_final_sizes(segs, original_width)[0])
    assert preview[0]["size"] < 14
    assert el["segments"][0]["size"] == 14.0          # the stored element is untouched
    assert preview[0]["text"] == segs[0]["text"]


def test_preview_segments_are_unchanged_when_the_text_fits():
    model, widget = _text_widget(runs=[_run(0, text="Hello world", top=0.1, left=0.1, right=0.1, bottom=0.85)])
    import copy
    segs = [{"text": "Hi", "family": "helvetica", "bold": False, "italic": False, "size": 12.0}]
    stored = copy.deepcopy(segs)
    assert widget._text_edit_preview_segments({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs},
                                              model.find_run(1, 0)) == segs
    assert segs == stored  # the stored dicts were not mutated


def test_preview_segments_use_the_displayed_height_as_the_original_width_on_a_rotated_page():
    from app.core.pdf_ops import text_edit_final_sizes
    # 90-degree page: displayed 842 x 595; the run is tall and narrow (sideways text)
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0, top=0.1, left=0.5, right=0.45, bottom=0.2)], rotation=90, width_pt=842, height_pt=595)
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 300))
    segs = [{"text": "W" * 40, "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]
    run = model.find_run(1, 0)
    displayed_h_pt = (1 - 0.1 - 0.2) * 595
    preview = widget._text_edit_preview_segments({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs}, run)
    assert preview[0]["size"] == pytest.approx(text_edit_final_sizes(segs, displayed_h_pt)[0])


def test_preview_segments_fall_back_to_the_stored_sizes_without_page_info():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    segs = [{"text": "abc", "family": "helvetica", "bold": False, "italic": False, "size": 12.0}]
    assert widget._text_edit_preview_segments({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs},
                                              _run(0)) == segs


def test_a_shrunk_preview_is_actually_painted_smaller(tmp_path, monkeypatch):
    import copy
    import app.ui.edit_canvas as ec
    from app.core.pdf_ops import text_edit_final_sizes
    model, widget = _text_widget(runs=[_run(0, text="Hi", top=0.1, left=0.1, right=0.8, bottom=0.85, size=14.0)])
    widget.px_per_pt = 400 / 595
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    long_segs = [{"text": "W" * 60, "family": "helvetica", "bold": False, "italic": False, "size": 30.0}]
    model.add({"page": 1, "type": "text_edit", "run_index": 0, "segments": long_segs})
    model.select(None)
    recorded = []
    real = ec.build_segments_document

    def spy(segments, px_per_pt):
        recorded.append(copy.deepcopy(segments))
        return real(segments, px_per_pt)

    monkeypatch.setattr(ec, "build_segments_document", spy)
    img = widget.grab().toImage()
    # direct check: the painted document was built from the export's final sizes, not the stored 30pt
    expected = text_edit_final_sizes(long_segs, (1 - 0.1 - 0.8) * 595)
    assert recorded, "the preview should have built a document"
    assert [s["size"] for s in recorded[-1]] == pytest.approx(expected)
    assert all(s["size"] < 30.0 for s in recorded[-1])
    assert long_segs[0]["size"] == 30.0
    # pixel check: measured dark-row span is 5px shrunk vs 15px unshrunk, so <= 9 separates them
    dark_rows = [y for y in range(600) if any(img.pixelColor(x, y).lightness() < 128 for x in range(0, 400, 2))]
    assert dark_rows, "the replacement text should have been painted"
    assert (max(dark_rows) - min(dark_rows)) <= 9


def _typed_elements():
    return [
        ("new_text", {"page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.3, "height": 0.1, "text": "Hi",
                      "family": "helvetica", "bold": False, "italic": False, "underline": False, "size": 14,
                      "color": "#000000", "align": "left"}),
        ("image", {"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.3, "height": 0.2, "file_id": "x.png"}),
        ("shape", _shape_element(x0=0.3, y0=0.3, x1=0.6, y1=0.5)),
        ("stroke", _stroke_element(points=[{"x": 0.3, "y": 0.3}, {"x": 0.6, "y": 0.5}])),
        ("highlight", _highlight_element(top=0.3, left=0.3, right=0.4, bottom=0.5)),
    ]


@pytest.mark.parametrize("kind,element", _typed_elements(), ids=[k for k, _ in _typed_elements()])
def test_an_unselected_elements_invisible_marker_area_does_not_delete_it(kind, element):
    model = EditElementsModel()
    model.add(element)
    model.select(None)
    widget = EditPageWidget(model, page_number=1)
    widget.create_mode = "select"
    widget.set_page_pixmap(QPixmap(400, 600))
    marker = widget._marker_rect(model.elements[0])
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert len(model.elements) == 1  # not deleted
    assert model.selected_id == model.elements[0]["id"]  # the click selected it instead


@pytest.mark.parametrize("kind,element", _typed_elements(), ids=[k for k, _ in _typed_elements()])
def test_a_selected_elements_marker_still_deletes_it(kind, element):
    model = EditElementsModel()
    el_id = model.add(element)  # add() selects
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    marker = widget._marker_rect(model.elements[0])
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def test_clicking_an_unselected_elements_marker_area_then_clicking_again_deletes_it():
    model = EditElementsModel()
    model.add(_shape_element(x0=0.3, y0=0.3, x1=0.6, y1=0.5))
    model.select(None)
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    marker = widget._marker_rect(model.elements[0])
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, marker.center())   # selects
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, marker.center())   # now the visible marker is hit
    assert model.elements == []


def _line_thickness(widget, y):
    img = widget.grab().toImage()
    x = widget.width() // 2
    ys = [yy for yy in range(widget.height()) if img.pixelColor(x, yy).lightness() < 128]
    return len(ys), (min(ys), max(ys)) if ys else None


def test_shape_pen_width_is_scaled_from_pdf_points_to_pixels():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    widget.px_per_pt = 0.5
    el_id = model.add(_shape_element(shape="line", x0=0.1, y0=0.5, x1=0.9, y1=0.5, color="#000000", width=6))
    model.select(None)
    thickness, _ = _line_thickness(widget, 300)
    assert 2 <= thickness <= 4   # 6pt at 0.5 px/pt is a 3px line, not the raw 6px


def test_stroke_pen_width_is_scaled_from_pdf_points_to_pixels():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    widget.px_per_pt = 0.5
    model.add(_stroke_element(points=[{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}], color="#000000", width=6))
    model.select(None)
    thickness, _ = _line_thickness(widget, 300)
    assert 2 <= thickness <= 4


def test_pen_width_is_unchanged_when_the_page_scale_is_unknown():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)   # no page info -> px_per_pt stays 1.0
    assert widget.px_per_pt == 1.0
    model.add(_shape_element(shape="line", x0=0.1, y0=0.5, x1=0.9, y1=0.5, color="#000000", width=6))
    model.select(None)
    thickness, _ = _line_thickness(widget, 300)
    assert 5 <= thickness <= 7


def test_arrowhead_length_follows_the_page_scale(monkeypatch):
    # width=1 pins the PEN out of the measurement: max(1.0, 1 * px_per_pt)
    # saturates at the 1px floor at both scales, so only the head can shrink.
    from PySide6.QtGui import QPainter
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    model.add(_shape_element(shape="arrow", x0=0.1, y0=0.5, x1=0.9, y1=0.5, color="#000000", width=1))
    model.select(None)

    polygons = []
    real_draw_polygon = QPainter.drawPolygon

    def spy(self, *args, **kwargs):
        polygons.append(args[0])
        return real_draw_polygon(self, *args, **kwargs)

    monkeypatch.setattr(QPainter, "drawPolygon", spy)

    def head_height_and_extent():
        polygons.clear()
        widget.update()
        img = widget.grab().toImage()
        x = int(0.9 * 400) - 3          # just behind the tip, inside the head
        ys = [y for y in range(600) if img.pixelColor(x, y).lightness() < 128]
        poly = polygons[-1]
        xs = [poly.at(k).x() for k in range(poly.size())]
        return ((max(ys) - min(ys)) if ys else 0), (max(xs) - min(xs))

    widget.px_per_pt = 1.0
    big, big_extent = head_height_and_extent()
    widget.px_per_pt = 0.5
    small, small_extent = head_height_and_extent()
    assert big > small > 0
    assert small_extent == pytest.approx(big_extent * 0.5, abs=2)


def test_new_text_font_pixel_size_follows_the_page_scale():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = {"family": "helvetica", "bold": False, "italic": False, "underline": False, "size": 20}
    widget.px_per_pt = 1.0
    assert widget._qfont_for(el).pixelSize() == 20
    widget.px_per_pt = 0.5
    assert widget._qfont_for(el).pixelSize() == 10
    widget.px_per_pt = 0.01
    assert widget._qfont_for(el).pixelSize() >= 1   # never zero


def test_new_text_editor_and_painted_text_use_the_same_scaled_font():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.px_per_pt = 0.5
    widget.create_mode = "new_text"
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300))
    assert widget._text_editor.font().pixelSize() == 7    # the default new-text size is 14pt x 0.5
    widget.commit_open_editors()


def _handle_elements():
    return [e for e in _typed_elements() if e[0] in ("new_text", "image", "shape", "highlight")]


def _geometry(el):
    keys = ("x", "y", "width", "height", "x0", "y0", "x1", "y1", "top", "left", "right", "bottom")
    return {k: el[k] for k in keys if k in el}


def _drag_from(widget, start, d=60):
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, start + QPoint(d // 2, d // 2))
    QTest.mouseMove(widget, start + QPoint(d, d))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, start + QPoint(d, d))


@pytest.mark.parametrize("kind,element", _handle_elements(), ids=[k for k, _ in _handle_elements()])
def test_an_unselected_elements_invisible_resize_handle_does_not_resize_it(kind, element):
    model = EditElementsModel()
    model.add(element)
    model.select(None)
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    before = _geometry(model.elements[0])
    _drag_from(widget, widget._resize_handles(model.elements[0])["corner"].center())
    after = _geometry(model.elements[0])
    # the press fell through to the body and armed a MOVE: extents are unchanged
    if kind == "shape":
        assert after["x1"] - after["x0"] == pytest.approx(before["x1"] - before["x0"])
        assert after["y1"] - after["y0"] == pytest.approx(before["y1"] - before["y0"])
    elif kind == "highlight":
        assert (1 - after["left"] - after["right"]) == pytest.approx(1 - before["left"] - before["right"])
        assert (1 - after["top"] - after["bottom"]) == pytest.approx(1 - before["top"] - before["bottom"])
    else:
        assert after["width"] == pytest.approx(before["width"])
        assert after["height"] == pytest.approx(before["height"])
    assert model.selected_id == model.elements[0]["id"]


@pytest.mark.parametrize("kind,element", _handle_elements(), ids=[k for k, _ in _handle_elements()])
def test_a_selected_elements_resize_handle_still_resizes_it(kind, element):
    model = EditElementsModel()
    model.add(element)  # add() selects
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    before = _geometry(model.elements[0])
    _drag_from(widget, widget._resize_handles(model.elements[0])["corner"].center())
    after = _geometry(model.elements[0])
    assert after != before
    if kind == "shape":
        assert after["x0"] == before["x0"] and after["x1"] > before["x1"]
    elif kind == "highlight":
        assert after["left"] == before["left"] and after["top"] == before["top"]
    else:
        assert after["x"] == before["x"] and after["y"] == before["y"]


def test_a_thin_lines_hit_margin_uses_the_pen_width_in_pixels():
    model = EditElementsModel()
    model.add(_shape_element(shape="line", x0=0.2, y0=0.5, x1=0.8, y1=0.5, width=40))
    model.select(None)
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.px_per_pt = 0.5           # 40pt pen -> 20px margin
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 + 18))
    assert model.selected_id == model.elements[0]["id"]
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 + 18))
    model.select(None)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 + 26))
    assert model.selected_id is None
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 + 26))


@pytest.mark.parametrize("rotation", [0, 90])
def test_text_edit_preview_size_equals_the_exported_span_size_in_the_ratio_branch(tmp_path, rotation):
    from app.core.pdf_ops import edit_pdf, text_edit_final_sizes
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    doc = fitz.open()
    page = doc.new_page(width=842, height=400)
    page.insert_text((60, 200), "Hello World", fontname="helv", fontsize=14)
    page.set_rotation(rotation)
    src = tmp_path / f"ratio{rotation}.pdf"
    doc.save(str(src))
    doc.close()
    raw_w = fitz.get_text_length("Hello World", fontname="helv", fontsize=14)
    replacement = "Hello World"
    seg = None
    for extra in "abcdefghijklmnop":
        replacement += extra
        seg = {"text": replacement, "family": "helvetica", "bold": False, "italic": False, "size": 14.0}
        if fitz.get_text_length(replacement, fontname="helv", fontsize=14) > raw_w * 1.3:
            break
    sizes = text_edit_final_sizes([seg], raw_w)
    assert 7 < sizes[0] < 14   # ratio branch: 0.5 < scale < 1 (and not the 6pt floor)

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, replacement)
    widget.commit_open_editors()
    el = dlg.model.elements[0]
    run = dlg.model.find_run(1, 0)
    preview = widget._text_edit_preview_segments(el, run)[0]["size"]

    out = tmp_path / "out.pdf"
    elements = [{k: v for k, v in e.items() if k != "id"} for e in dlg.model.elements]
    edit_pdf(str(src), str(out), elements, {})
    result = fitz.open(str(out))
    spans = [sp for blk in result[0].get_text("dict")["blocks"] for ln in blk.get("lines", [])
             for sp in ln["spans"] if replacement in sp["text"]]
    result.close()
    assert spans, "the replacement should be in the export"
    assert preview == pytest.approx(spans[0]["size"], abs=0.1)
    assert preview == pytest.approx(sizes[0], abs=0.1)


# ---- desktop Edit PDF: white swatch, "More..." colour picker, Delete/Backspace ----

def _draw_shape_on(dlg, page_widget):
    w, h = page_widget.width(), page_widget.height()
    start, end = QPoint(int(w * 0.2), int(h * 0.2)), QPoint(int(w * 0.5), int(h * 0.4))
    QTest.mousePress(page_widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(page_widget, end)
    QTest.mouseRelease(page_widget, Qt.LeftButton, Qt.NoModifier, end)


def _stub_picker(monkeypatch, dlg, result):
    calls = []

    def fake(initial):
        calls.append(initial)
        return result
    monkeypatch.setattr(dlg, "_get_color_dialog", fake)
    return calls


def test_edit_pdf_dialog_white_is_in_the_palette_and_a_white_shape_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    dlg, src = _dialog_with_text(tmp_path)
    assert "#ffffff" in EditPdfDialog._PALETTE
    dlg._set_create_mode("shape")
    white = next(b for c, b in dlg._swatch_buttons["shape"] if c == "#ffffff")
    white.click()
    assert dlg._tool_colors["shape"] == "#ffffff"
    assert "border: 3px solid #1971c2" in white.styleSheet()
    dlg._set_tool_color("shape", "#ff0000")
    assert "1px solid #888" in white.styleSheet()
    white.click()
    _draw_shape_on(dlg, dlg._page_widgets[0])
    assert dlg.model.elements[0]["color"] == "#ffffff"
    out = dlg.run_operation([str(src)], dlg.gather_params())
    assert out and os.path.exists(out[0])


def test_edit_pdf_dialog_each_tool_row_has_its_own_more_button():
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    dlg = EditPdfDialog()
    assert set(dlg._more_buttons) == {"draw", "shape", "highlight", "marker"}
    assert len({id(b) for b in dlg._more_buttons.values()}) == 4


def test_edit_pdf_dialog_more_button_sets_only_its_tools_custom_colour(tmp_path, monkeypatch):
    from PySide6.QtGui import QColor
    dlg, src = _dialog_with_text(tmp_path)
    calls = _stub_picker(monkeypatch, dlg, QColor("#12ABef"))
    dlg._set_create_mode("shape")
    dlg._more_buttons["shape"].click()
    assert calls == ["#ff0000"]  # initial = the tool's current colour
    assert dlg._tool_colors == {"draw": "#ff0000", "shape": "#12abef", "highlight": "#ffd43b", "marker": "#ffd43b"}
    more = dlg._more_buttons["shape"]
    assert "border: 3px solid #1971c2" in more.styleSheet() and "#12abef" in more.styleSheet()
    assert "3px" not in dlg._more_buttons["draw"].styleSheet()
    assert all("3px" not in b.styleSheet() for _, b in dlg._swatch_buttons["shape"])
    _draw_shape_on(dlg, dlg._page_widgets[0])
    assert dlg.model.elements[0]["color"] == "#12abef"
    out = dlg.run_operation([str(src)], dlg.gather_params())
    assert out and os.path.exists(out[0])
    # picking a palette colour again de-selects the More button
    dlg._set_tool_color("shape", "#000000")
    assert "3px" not in more.styleSheet()


def test_edit_pdf_dialog_cancelled_or_invalid_colour_pick_changes_nothing(tmp_path, monkeypatch):
    from PySide6.QtGui import QColor
    dlg, src = _dialog_with_text(tmp_path)
    before = dict(dlg._tool_colors)
    for bad in (QColor(), None):  # QColorDialog.getColor returns an invalid QColor on cancel
        _stub_picker(monkeypatch, dlg, bad)
        for tool in ("draw", "shape", "highlight", "marker"):
            dlg._more_buttons[tool].click()
    assert dlg._tool_colors == before
    assert all("3px" not in b.styleSheet() for b in dlg._more_buttons.values())


def _dlg_with_selected(tmp_path, kind):
    dlg, src = _dialog_with_text(tmp_path)
    base = {"page": 1}
    if kind == "shape":
        el = _shape_element()
    elif kind == "stroke":
        el = _stroke_element()
    elif kind == "highlight":
        el = _highlight_element()
    elif kind == "new_text":
        el = {"page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.05,
              "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
              "underline": False, "size": 14, "color": "#000000", "align": "left"}
    elif kind == "image":
        el = {"page": 1, "type": "image", "file_id": "x.png", "x": 0.2, "y": 0.2, "width": 0.2, "height": 0.1}
    else:
        el = _text_edit_element()
    dlg.model.add(el)
    dlg.model.select(dlg.model.elements[-1]["id"])
    return dlg


@pytest.mark.parametrize("key", [Qt.Key_Delete, Qt.Key_Backspace])
@pytest.mark.parametrize("kind", ["shape", "stroke", "highlight", "new_text", "image", "text_edit"])
def test_edit_pdf_dialog_delete_and_backspace_keys_delete_the_selected_element(tmp_path, kind, key):
    dlg = _dlg_with_selected(tmp_path, kind)
    extra = dlg.model.add(_shape_element(x0=0.6, y0=0.6, x1=0.8, y1=0.8))
    dlg.model.select(dlg.model.elements[0]["id"])
    target_id = dlg.model.elements[0]["id"]
    undo_depth = len(dlg.model._undo_stack)
    QTest.keyClick(dlg, key)
    assert [e["id"] for e in dlg.model.elements] == [extra]
    assert len(dlg.model._undo_stack) == undo_depth + 1
    dlg.model.undo()
    assert target_id in [e["id"] for e in dlg.model.elements]


def test_edit_pdf_dialog_delete_key_with_nothing_selected_does_nothing(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg.model.add(_shape_element())
    dlg.model.select(None)
    depth = len(dlg.model._undo_stack)
    QTest.keyClick(dlg, Qt.Key_Delete)
    QTest.keyClick(dlg, Qt.Key_Backspace)
    assert len(dlg.model.elements) == 1 and len(dlg.model._undo_stack) == depth


def test_edit_pdf_dialog_delete_key_is_left_to_an_open_new_text_editor(tmp_path):
    dlg = _dlg_with_selected(tmp_path, "shape")
    dlg._page_widgets[0]._open_text_editor_for_new((0.6, 0.6))
    assert dlg._page_widgets[0]._text_editor is not None
    depth = len(dlg.model._undo_stack)
    QTest.keyClick(dlg, Qt.Key_Delete)
    QTest.keyClick(dlg, Qt.Key_Backspace)
    assert len(dlg.model.elements) == 1 and len(dlg.model._undo_stack) == depth


def test_edit_pdf_dialog_delete_key_is_left_to_an_open_run_editor(tmp_path):
    dlg = _dlg_with_selected(tmp_path, "shape")
    dlg._set_create_mode("text")
    _dclick_run(dlg._page_widgets[0], 0)
    assert dlg._page_widgets[0]._run_editor is not None
    dlg.model.select(dlg.model.elements[0]["id"])
    QTest.keyClick(dlg, Qt.Key_Delete)
    QTest.keyClick(dlg, Qt.Key_Backspace)
    assert len(dlg.model.elements) == 1


def test_edit_pdf_dialog_delete_key_works_after_clicking_a_toolbar_button(tmp_path):
    dlg = _dlg_with_selected(tmp_path, "shape")
    dlg.new_text_btn.click()
    dlg.model.select(dlg.model.elements[0]["id"])
    QTest.keyClick(dlg, Qt.Key_Delete)
    assert dlg.model.elements == []


def test_edit_pdf_dialog_does_not_register_delete_or_backspace_as_shortcuts():
    from PySide6.QtGui import QShortcut
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    dlg = EditPdfDialog()
    keys = {s.key().toString() for s in dlg.findChildren(QShortcut)}
    assert "Delete" not in keys and "Backspace" not in keys
    assert {"Ctrl+Z", "Ctrl+Y", "Ctrl+C", "Ctrl+X", "Ctrl+V"} <= keys


# ---- main window: tools open in-window with a Back link ----


from app.ui.dialogs.edit_dialogs import RotateDialog  # noqa: E402


def _themed_main_window():
    from app.main import build_main_window
    from app.ui.theme import apply_theme

    apply_theme(QApplication.instance())
    return build_main_window()


def test_main_window_has_a_card_for_every_tool():
    from app.ui.main_window import ToolCard

    window = _themed_main_window()
    cards = window._home.findChildren(ToolCard)
    assert len(cards) == 26
    assert "Desktop" in window.windowTitle()


def test_clicking_a_card_opens_the_tool_in_the_window_and_back_returns_home():
    window = _themed_main_window()
    window.show()
    card = next(c for c in window._home.findChildren(QPushButton) if c.accessibleName() == "Rotate PDF")
    card.click()
    assert window._stack.currentWidget() is window._tool_page
    assert window._tool_title.text() == "Rotate PDF"
    tool = window._current_tool
    assert tool.parent() is not None and not tool.isWindow()  # embedded, not a pop-up
    window._back_button.click()
    assert window._stack.currentWidget() is window._home
    assert window._current_tool is None


def test_escape_does_not_close_an_embedded_tool():
    window = _themed_main_window()
    window.show()
    window.open_tool("Rotate PDF", RotateDialog)
    tool = window._current_tool
    tool.reject()
    tool.accept()
    assert tool.isVisible()


def test_back_is_refused_while_a_tool_is_still_running(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window = _themed_main_window()
    window.open_tool("Rotate PDF", RotateDialog)

    class Busy:
        def isRunning(self):
            return True

    window._current_tool._worker = Busy()
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a))
    window.show_home()
    assert shown
    assert window._stack.currentWidget() is window._tool_page


def test_theme_loads_the_bundled_font_and_icons():
    from PySide6.QtGui import QFontDatabase

    from app.ui.theme import icon_pixmap

    _themed_main_window()
    assert "Inter" in QFontDatabase.families()
    assert not icon_pixmap("stack").isNull()


# ---- Recent Files ----


def _row_names(window):
    from PySide6.QtWidgets import QFrame, QLabel

    rows = window._recent_list.findChildren(QFrame, "historyRow")
    return [r.findChild(QLabel, "historyName").text() for r in rows]


def test_a_finished_tool_is_recorded_in_recent_files(tmp_path):
    from app.core import history

    out = tmp_path / "result.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(out))
    doc.close()
    dlg = RotateDialog()
    dlg._on_success([str(out)])
    entries = history.list_entries()
    assert [e["filename"] for e in entries] == ["result.pdf"]
    assert entries[0]["tool"] == dlg.title
    assert entries[0]["page_count"] == 1


def test_a_history_write_failure_does_not_break_the_operation(tmp_path, monkeypatch):
    from app.core import history

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(history, "add_entry", boom)
    dlg = RotateDialog()
    dlg._on_success([str(tmp_path / "x.pdf")])
    assert dlg.status_label.text().startswith("Done")


def test_recent_files_page_lists_newest_first_and_remove_keeps_the_file(tmp_path):
    from app.core import history

    a = tmp_path / "a.pdf"
    a.write_bytes(b"x")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"x")
    history.add_entry(str(a), "Merge PDF")
    history.add_entry(str(b), "Rotate PDF")
    window = _themed_main_window()
    window.show_recent()
    assert window._stack.currentWidget() is window._recent_page
    assert _row_names(window) == ["b.pdf", "a.pdf"]
    window._recent_list.remove(history.list_entries()[0]["id"])
    assert _row_names(window) == ["a.pdf"]
    assert b.exists()


def test_recent_files_shows_an_empty_message_and_flags_missing_files(tmp_path):
    from PySide6.QtWidgets import QLabel

    from app.core import history

    window = _themed_main_window()
    window.show_recent()
    assert window._recent_list.findChild(QLabel, "emptyState") is not None
    history.add_entry(str(tmp_path / "gone.pdf"), "Merge PDF")
    window.show_recent()
    row = window._recent_list.findChildren(QPushButton)
    assert [b.text() for b in row] == ["Remove"]  # no Open / Show in folder for a missing file


def test_recent_files_open_and_show_in_folder_use_the_saved_path(tmp_path, monkeypatch):
    from app.core import history
    from app.ui import recent_files

    f = tmp_path / "keep.pdf"
    f.write_bytes(b"x")
    history.add_entry(str(f), "Merge PDF")
    opened, revealed = [], []
    monkeypatch.setattr(recent_files.RecentFilesPage, "open_file", staticmethod(opened.append))
    monkeypatch.setattr(recent_files.RecentFilesPage, "show_in_folder", staticmethod(revealed.append))
    window = _themed_main_window()
    window.show_recent()
    buttons = {b.text(): b for b in window._recent_list.findChildren(QPushButton)}
    buttons["Open"].click()
    buttons["Show in folder"].click()
    assert opened == [str(f)] and revealed == [str(f)]


def test_recent_files_link_is_refused_while_a_tool_is_running(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window = _themed_main_window()
    window.open_tool("Rotate PDF", RotateDialog)

    class Busy:
        def isRunning(self):
            return True

    window._current_tool._worker = Busy()
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a))
    window._recent_link.click()
    assert shown and window._stack.currentWidget() is window._tool_page


# ---- EditElementsModel: group selection and group operations ----


def _group_model():
    model = EditElementsModel()
    ids = {
        "stroke": model.add({"page": 1, "type": "stroke", "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}], "color": "#000000", "width": 3}),
        "shape": model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.4, "y0": 0.4, "x1": 0.5, "y1": 0.5, "color": "#ff0000", "width": 3, "filled": False}),
        "image": model.add({"page": 1, "type": "image", "x": 0.6, "y": 0.1, "width": 0.2, "height": 0.1, "file_path": "x.png"}),
        "highlight": model.add({"page": 1, "type": "highlight", "top": 0.7, "right": 0.5, "bottom": 0.2, "left": 0.3, "color": "#ffd43b"}),
    }
    model._undo_stack.clear()
    return model, ids


def test_select_many_sets_the_group_and_clears_the_single_selection():
    model, ids = _group_model()
    model.select(ids["shape"])
    model.select_many([ids["stroke"], ids["image"]])
    assert model.selected_ids == [ids["stroke"], ids["image"]]
    assert model.selected_id is None
    model.select(ids["shape"])  # picking one element drops the group
    assert model.selected_ids == []
    model.select_many([ids["stroke"]])
    model.clear_selection()
    assert model.selected_ids == [] and model.selected_id is None


def test_delete_selected_group_is_one_undo_step():
    model, ids = _group_model()
    model.select_many([ids["stroke"], ids["shape"], ids["highlight"]])
    model.delete_selected_group()
    assert [e["id"] for e in model.elements] == [ids["image"]]
    assert model.selected_ids == []
    model.undo()
    assert len(model.elements) == 4
    model.redo()
    assert len(model.elements) == 1


def test_nudge_group_moves_every_type_together_in_one_undo_step():
    model, ids = _group_model()
    model.select_many(list(ids.values()))
    model.nudge_group(0.02, 0.03)
    by_id = {e["id"]: e for e in model.elements}
    assert by_id[ids["stroke"]]["points"][0]["x"] == pytest.approx(0.12)
    assert by_id[ids["stroke"]]["points"][0]["y"] == pytest.approx(0.13)
    assert by_id[ids["shape"]]["x0"] == pytest.approx(0.42)
    assert by_id[ids["image"]]["y"] == pytest.approx(0.13)
    assert by_id[ids["highlight"]]["left"] == pytest.approx(0.32)
    assert by_id[ids["highlight"]]["top"] == pytest.approx(0.73)
    model.undo()
    assert {e["id"]: e for e in model.elements}[ids["shape"]]["x0"] == 0.4


def test_group_move_is_clamped_as_a_whole_not_per_element():
    model, ids = _group_model()
    model.select_many([ids["stroke"], ids["shape"]])
    # The stroke starts at x=0.1, so a -0.5 move can only go -0.1 for the group;
    # the shape must slide by the SAME amount, not be squashed against the edge.
    model.nudge_group(-0.5, 0)
    by_id = {e["id"]: e for e in model.elements}
    assert by_id[ids["stroke"]]["points"][0]["x"] == pytest.approx(0.0)
    assert by_id[ids["shape"]]["x0"] == pytest.approx(0.3)
    assert by_id[ids["shape"]]["x1"] == pytest.approx(0.4)


def test_translate_group_is_live_from_the_snapshot_and_commits_nothing():
    model, ids = _group_model()
    base = [dict(e) for e in model.elements]
    model.translate_group([ids["shape"], ids["image"]], 0.1, 0.0, base=base)
    model.translate_group([ids["shape"], ids["image"]], 0.2, 0.0, base=base)  # from the snapshot, not cumulative
    by_id = {e["id"]: e for e in model.elements}
    assert by_id[ids["shape"]]["x0"] == pytest.approx(0.6)
    assert by_id[ids["image"]]["x"] == pytest.approx(0.8)
    assert model._undo_stack == []
    assert by_id[ids["stroke"]]["points"][0]["x"] == 0.1  # not in the group: untouched


def test_group_operations_skip_a_text_edit_whose_run_has_not_loaded():
    model, ids = _group_model()
    orphan = model.add({"page": 1, "type": "text_edit", "run_index": 7, "segments": []})
    model._undo_stack.clear()
    model.select_many([ids["shape"], orphan])
    model.nudge_group(0.05, 0)  # must not raise
    by_id = {e["id"]: e for e in model.elements}
    assert by_id[ids["shape"]]["x0"] == pytest.approx(0.45)
    assert "x" not in by_id[orphan]


def test_undo_drops_group_members_that_no_longer_exist():
    model, ids = _group_model()
    extra = model.add({"page": 1, "type": "shape", "shape": "line", "x0": 0.1, "y0": 0.9, "x1": 0.2, "y1": 0.9, "color": "#000000", "width": 1, "filled": False})
    model.select_many([ids["stroke"], extra])
    model.undo()  # undoes the add of `extra`
    assert model.selected_ids == [ids["stroke"]]


def test_removing_an_element_drops_it_from_the_group():
    model, ids = _group_model()
    model.select_many([ids["stroke"], ids["shape"]])
    model.remove(ids["shape"])
    assert model.selected_ids == [ids["stroke"]]


# ---- Edit PDF: dots, drawing wins, freehand highlighter, eraser ----


def _white_page_widget(model, create_mode):
    widget = EditPageWidget(model, page_number=1)
    pixmap = QPixmap(400, 600)
    pixmap.fill(Qt.white)
    widget.set_page_pixmap(pixmap)
    widget.create_mode = create_mode
    return widget


def _drag(widget, points):
    """Press at points[0], move through the rest, release at the last."""
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, points[0])
    for p in points[1:]:
        QTest.mouseMove(widget, p)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, points[-1])


def _px(widget, fx, fy):
    return QPoint(int(widget.width() * fx), int(widget.height() * fy))


def _stroke_at(y, x0=0.1, x1=0.9, width=3):
    return {"page": 1, "type": "stroke", "points": [{"x": x0, "y": y}, {"x": x1, "y": y}], "color": "#000000", "width": width}


def test_drawing_over_an_existing_shape_draws_instead_of_selecting_or_moving_it():
    model = EditElementsModel()
    shape_id = model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.2, "y0": 0.2, "x1": 0.8, "y1": 0.8, "color": "#ff0000", "width": 3, "filled": True})
    model.clear_selection()
    before = dict(model.elements[0])
    widget = _white_page_widget(model, "stroke")
    _drag(widget, [_px(widget, 0.5, 0.5), _px(widget, 0.6, 0.6)])  # starts INSIDE the filled shape
    assert [e["type"] for e in model.elements] == ["shape", "stroke"]
    assert model.elements[0] == before  # not moved
    assert model.selected_id is None  # not selected


def test_drawing_starting_on_an_existing_stroke_draws_a_new_one():
    model = EditElementsModel()
    model.add(_stroke_at(0.5))
    model.clear_selection()
    widget = _white_page_widget(model, "stroke")
    _drag(widget, [_px(widget, 0.5, 0.5), _px(widget, 0.5, 0.7)])
    assert len(model.elements) == 2
    assert model.selected_id is None


def test_strokes_are_not_selectable_outside_the_select_tool():
    for mode in ("new_text", "shape", "highlight", "text", "image"):
        model = EditElementsModel()
        model.add(_stroke_at(0.5))
        model.clear_selection()
        widget = _white_page_widget(model, mode)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.5, 0.5))
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.5, 0.5))
        assert model.selected_id is None, mode
    model = EditElementsModel()
    stroke_id = model.add(_stroke_at(0.5))
    model.clear_selection()
    widget = _white_page_widget(model, "select")
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.5, 0.5))
    assert model.selected_id == stroke_id


def test_a_dot_is_visible_and_round():
    model = EditElementsModel()
    widget = _white_page_widget(model, "stroke")
    widget.width_preset = "thick"
    widget.color = "#000000"
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300))
    image = widget.grab().toImage()
    assert QColor(image.pixel(200, 300)).lightness() < 100
    assert QColor(image.pixel(300, 400)).lightness() > 240  # nothing far away


def test_marker_stroke_is_translucent_and_carries_opacity():
    model = EditElementsModel()
    widget = _white_page_widget(model, "stroke")
    widget.draw_tool = "marker"
    widget.marker_color = "#ffff00"
    widget.marker_width_preset = "medium"
    _drag(widget, [_px(widget, 0.1, 0.5), _px(widget, 0.5, 0.5), _px(widget, 0.9, 0.5)])
    stroke = model.elements[0]
    assert stroke["opacity"] == 0.4 and stroke["color"] == "#ffff00" and stroke["width"] == 14
    color = QColor(widget.grab().toImage().pixel(int(400 * 0.5), int(600 * 0.5)))
    assert color.red() > 240 and color.green() > 240  # yellow over white...
    assert 100 < color.blue() < 220  # ...but see-through, not solid


def test_a_pen_stroke_has_no_opacity_field():
    model = EditElementsModel()
    widget = _white_page_widget(model, "stroke")
    _drag(widget, [_px(widget, 0.1, 0.5), _px(widget, 0.9, 0.5)])
    assert "opacity" not in model.elements[0]


def test_eraser_removes_every_stroke_a_sparse_drag_crosses_in_one_undo_step():
    model = EditElementsModel()
    for y in (0.2, 0.4, 0.6):
        model.add(_stroke_at(y))
    shape_id = model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.3, "y0": 0.1, "x1": 0.4, "y1": 0.9, "color": "#ff0000", "width": 3, "filled": True})
    model.clear_selection()
    model._undo_stack.clear()
    widget = _white_page_widget(model, "eraser")
    # One jump from above the first stroke to below the second: the eraser must
    # still get both (it tests the segment, not just the endpoints)...
    _drag(widget, [_px(widget, 0.5, 0.1), _px(widget, 0.5, 0.5)])
    remaining = [e for e in model.elements if e["type"] == "stroke"]
    assert len(remaining) == 1 and remaining[0]["points"][0]["y"] == 0.6
    # ...and never the shape it drags over (x=0.3-0.4 is not crossed; press on it too).
    _drag(widget, [_px(widget, 0.35, 0.05), _px(widget, 0.35, 0.95)])
    assert any(e["id"] == shape_id for e in model.elements)
    assert len(model._undo_stack) == 2  # one step per sweep
    model.undo()
    assert len([e for e in model.elements if e["type"] == "stroke"]) == 1
    model.undo()
    assert len([e for e in model.elements if e["type"] == "stroke"]) == 3
    model.redo()
    assert len([e for e in model.elements if e["type"] == "stroke"]) == 1


def test_eraser_hides_strokes_while_sweeping_and_a_miss_commits_nothing():
    model = EditElementsModel()
    model.add(_stroke_at(0.5))
    model.clear_selection()
    model._undo_stack.clear()
    widget = _white_page_widget(model, "eraser")
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.5, 0.5))
    assert widget._erase["ids"]  # marked...
    assert len(model.elements) == 1  # ...but not yet removed
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.5, 0.5))
    assert model.elements == [] and len(model._undo_stack) == 1
    model.undo()
    widget2 = _white_page_widget(model, "eraser")
    model._undo_stack.clear()
    _drag(widget2, [_px(widget2, 0.5, 0.9), _px(widget2, 0.6, 0.95)])  # nowhere near
    assert len(model.elements) == 1 and model._undo_stack == []


def test_eraser_hits_a_thin_stroke_only_within_its_reach():
    model = EditElementsModel()
    model.add(_stroke_at(0.5, width=1))
    widget = _white_page_widget(model, "eraser")
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 - 40))  # 40px away
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 - 40))
    assert len(model.elements) == 1
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 - 6))  # within reach
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300 - 6))
    assert model.elements == []


def test_dialog_draw_subtool_switch_swaps_options_and_style():
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    dlg = EditPdfDialog()
    dlg.on_files_changed([])
    dlg._set_create_mode("draw")
    assert dlg.pen_btn.isChecked() and not dlg.marker_btn.isChecked()
    assert not dlg._pen_options.isHidden() and dlg._marker_options.isHidden()
    dlg._set_draw_tool("marker")
    assert dlg.marker_btn.isChecked() and not dlg.pen_btn.isChecked()
    assert dlg._pen_options.isHidden() and not dlg._marker_options.isHidden()
    assert dlg._active_style_tool() == "marker"
    dlg._set_tool_color("marker", "#69db7c")
    assert dlg._tool_colors["marker"] == "#69db7c" and dlg._tool_colors["draw"] == "#ff0000"


def test_dialog_switching_mode_clears_selection_and_eraser_button_sets_the_mode(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    shape_id = dlg.model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.2, "y0": 0.2, "x1": 0.5, "y1": 0.5, "color": "#ff0000", "width": 3, "filled": False})
    assert dlg.model.selected_id == shape_id
    dlg.eraser_btn.click()
    assert dlg.model.selected_id is None
    assert dlg._page_widgets[0].create_mode == "eraser" and dlg.eraser_btn.isChecked()
    dlg.draw_btn.click()
    assert dlg._page_widgets[0].create_mode == "stroke" and not dlg.eraser_btn.isChecked()


def test_marker_and_dot_export_end_to_end(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page = dlg._page_widgets[0]
    dlg._set_create_mode("draw")
    dlg._set_draw_tool("marker")
    dlg._set_tool_color("marker", "#ffff00")
    _drag(page, [_px(page, 0.2, 0.5), _px(page, 0.5, 0.5), _px(page, 0.8, 0.5)])
    dlg._set_draw_tool("pen")
    dlg._set_tool_color("draw", "#000000")
    dlg._set_tool_width("draw", "thick")
    QTest.mousePress(page, Qt.LeftButton, Qt.NoModifier, _px(page, 0.5, 0.8))  # a plain click
    QTest.mouseRelease(page, Qt.LeftButton, Qt.NoModifier, _px(page, 0.5, 0.8))
    elements = dlg.gather_params()["elements"]
    assert [e["type"] for e in elements] == ["stroke", "stroke"]
    assert elements[0]["opacity"] == 0.4 and len(elements[1]["points"]) == 1
    out = dlg.run_operation([str(input_path)], dlg.gather_params())[0]
    with fitz.open(out) as doc:
        pix = doc[0].get_pixmap()
    r, g, b = pix.pixel(int(pix.width * 0.5), int(pix.height * 0.5))[:3]
    assert r > 240 and g > 240 and 100 < b < 220  # translucent yellow, page still visible through it
    assert pix.pixel(int(pix.width * 0.5), int(pix.height * 0.8))[0] < 100  # the dot


# ---- Edit PDF: Select tool (marquee, group move, delete, nudge) ----


def _mixed_row_model():
    """Five different element types in a row near the top, one far below."""
    model = EditElementsModel()
    ids = {
        "stroke": model.add({"page": 1, "type": "stroke", "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}], "color": "#000000", "width": 3}),
        "shape": model.add(_shape_element(x0=0.25, y0=0.1, x1=0.35, y1=0.2)),
        "highlight": model.add(_highlight_element(top=0.1, left=0.4, right=0.5, bottom=0.8)),
        "image": model.add({"page": 1, "type": "image", "x": 0.55, "y": 0.1, "width": 0.1, "height": 0.1, "file_id": "x.png"}),
        "new_text": model.add({"page": 1, "type": "new_text", "x": 0.7, "y": 0.1, "width": 0.1, "height": 0.05, "text": "Hi",
                               "family": "helvetica", "bold": False, "italic": False, "underline": False, "size": 14,
                               "color": "#000000", "align": "left"}),
        "far": model.add(_shape_element(x0=0.1, y0=0.6, x1=0.2, y1=0.7)),
    }
    model.clear_selection()
    model._undo_stack.clear()
    return model, ids


def _marquee(widget, a, b):
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, *a))
    QTest.mouseMove(widget, _px(widget, *b))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, *b))


def test_marquee_selects_every_type_it_touches_and_nothing_else():
    model, ids = _mixed_row_model()
    widget = _white_page_widget(model, "select")
    _marquee(widget, (0.05, 0.05), (0.75, 0.3))
    assert set(model.selected_ids) == {ids["stroke"], ids["shape"], ids["highlight"], ids["image"], ids["new_text"]}
    assert ids["far"] not in model.selected_ids
    assert model.selected_id is None


def test_marquee_that_only_grazes_an_element_still_selects_it():
    model, ids = _mixed_row_model()
    widget = _white_page_widget(model, "select")
    _marquee(widget, (0.05, 0.05), (0.12, 0.12))  # just the corner of the stroke
    assert model.selected_ids == [ids["stroke"]]


def test_a_new_marquee_replaces_the_old_selection_and_a_click_clears_it():
    model, ids = _mixed_row_model()
    widget = _white_page_widget(model, "select")
    _marquee(widget, (0.05, 0.05), (0.75, 0.3))
    assert len(model.selected_ids) == 5
    _marquee(widget, (0.05, 0.55), (0.3, 0.8))
    assert model.selected_ids == [ids["far"]]
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.9, 0.9))  # empty space, no drag
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.9, 0.9))
    assert model.selected_ids == [] and model.selected_id is None


def test_marquee_ignores_other_pages_elements():
    model, ids = _mixed_row_model()
    other = model.add({"page": 2, "type": "stroke", "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}], "color": "#000000", "width": 3})
    model.clear_selection()
    widget = _white_page_widget(model, "select")  # page 1's widget
    _marquee(widget, (0.05, 0.05), (0.75, 0.3))
    assert other not in model.selected_ids


def test_marquee_picks_up_a_text_edit_once_its_run_is_loaded():
    model = EditElementsModel()
    run = {"index": 0, "text": "Hello", "bbox": {"top": 0.1, "left": 0.1, "right": 0.6, "bottom": 0.85}, "family": "helvetica",
           "size": 12, "bold": False, "italic": False, "color": "#000000"}
    model.set_page_text_info(1, [run], 0, 595.0, 842.0)
    edit = model.add({"page": 1, "type": "text_edit", "run_index": 0, "segments": []})
    model.clear_selection()
    widget = _white_page_widget(model, "select")
    _marquee(widget, (0.05, 0.05), (0.8, 0.2))
    assert model.selected_ids == [edit]


def _select_group(widget, model):
    _marquee(widget, (0.05, 0.05), (0.75, 0.3))
    assert len(model.selected_ids) == 5


def test_dragging_the_group_moves_every_member_together_in_one_undo_step():
    model, ids = _mixed_row_model()
    widget = _white_page_widget(model, "select")
    _select_group(widget, model)
    before = {e["id"]: dict(e) for e in model.elements}
    # Press inside the group box (on the empty gap between shape and highlight)
    # and drag: it must move the group, not start a new marquee.
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.37, 0.15))
    QTest.mouseMove(widget, _px(widget, 0.37, 0.15) + QPoint(20, 30))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.37, 0.15) + QPoint(20, 30))
    dx, dy = 20 / widget.width(), 30 / widget.height()
    now = {e["id"]: e for e in model.elements}
    assert now[ids["stroke"]]["points"][0]["x"] == pytest.approx(0.1 + dx)
    assert now[ids["shape"]]["y0"] == pytest.approx(0.1 + dy)
    assert now[ids["image"]]["x"] == pytest.approx(0.55 + dx)
    assert now[ids["new_text"]]["y"] == pytest.approx(0.1 + dy)
    assert now[ids["highlight"]]["left"] == pytest.approx(0.4 + dx)
    assert now[ids["far"]] == before[ids["far"]]  # not in the group
    assert len(model._undo_stack) == 1
    model.undo()
    assert {e["id"]: e for e in model.elements}[ids["shape"]]["y0"] == before[ids["shape"]]["y0"]


def test_group_drag_is_clamped_as_a_whole_at_the_page_edge():
    model, ids = _mixed_row_model()
    widget = _white_page_widget(model, "select")
    _select_group(widget, model)
    start = _px(widget, 0.37, 0.15)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, QPoint(1, 1))  # far past the top-left corner (not (0,0): QTest reads that as "centre")
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    now = {e["id"]: e for e in model.elements}
    # Leftmost member (the stroke, x=0.1) and topmost (y=0.1) stop at the edge...
    assert now[ids["stroke"]]["points"][0]["x"] == pytest.approx(0.0)
    assert min(p["y"] for p in now[ids["stroke"]]["points"]) == pytest.approx(0.0)
    # ...and the others slid by the SAME amount rather than piling up on it.
    assert now[ids["shape"]]["x0"] == pytest.approx(0.25 - 0.1)
    assert now[ids["image"]]["x"] == pytest.approx(0.55 - 0.1)


def test_a_plain_click_on_the_group_moves_nothing_and_adds_no_undo_step():
    model, ids = _mixed_row_model()
    widget = _white_page_widget(model, "select")
    _select_group(widget, model)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.37, 0.15))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.37, 0.15))
    assert model._undo_stack == []
    assert len(model.selected_ids) == 5  # still selected


def test_a_press_outside_the_group_starts_a_new_marquee_instead_of_moving_it():
    model, ids = _mixed_row_model()
    widget = _white_page_widget(model, "select")
    _select_group(widget, model)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.9, 0.9))
    assert widget._marquee is not None and widget._group_drag is None
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.9, 0.9))


def test_select_tool_still_selects_and_moves_a_single_stroke():
    model = EditElementsModel()
    stroke_id = model.add(_stroke_at(0.5))
    model.clear_selection()
    widget = _white_page_widget(model, "select")
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.5, 0.5))
    QTest.mouseMove(widget, _px(widget, 0.5, 0.5) + QPoint(0, 40))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, _px(widget, 0.5, 0.5) + QPoint(0, 40))
    assert model.selected_id == stroke_id
    assert model.elements[0]["points"][0]["y"] == pytest.approx(0.5 + 40 / widget.height())


def _dialog_with_group(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    input_path = _single_page_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page = dlg._page_widgets[0]
    dlg.select_btn.click()
    for el in (
        {"page": 1, "type": "stroke", "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}], "color": "#000000", "width": 3},
        _shape_element(x0=0.3, y0=0.1, x1=0.4, y1=0.2),
        _highlight_element(top=0.1, left=0.5, right=0.4, bottom=0.8),
    ):
        dlg.model.add(el)
    dlg.model.clear_selection()
    dlg.model._undo_stack.clear()
    _marquee(page, (0.05, 0.05), (0.7, 0.3))
    assert len(dlg.model.selected_ids) == 3
    return dlg, page, input_path


def test_select_button_sets_the_select_mode_and_keeps_only_one_mode_checked():
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    dlg = EditPdfDialog()
    dlg.on_files_changed([])
    dlg.select_btn.click()
    assert dlg.select_btn.isChecked() and not dlg.new_text_btn.isChecked() and not dlg.eraser_btn.isChecked()
    dlg.draw_btn.click()
    assert not dlg.select_btn.isChecked()


def test_delete_key_deletes_the_whole_group_in_one_undo_step(tmp_path):
    dlg, page, _ = _dialog_with_group(tmp_path)
    QTest.keyClick(dlg, Qt.Key_Delete)
    assert dlg.model.elements == [] and dlg.model.selected_ids == []
    assert len(dlg.model._undo_stack) == 1
    dlg.model.undo()
    assert len(dlg.model.elements) == 3


def test_backspace_and_the_toolbar_delete_button_also_delete_the_group(tmp_path):
    dlg, page, _ = _dialog_with_group(tmp_path)
    QTest.keyClick(dlg, Qt.Key_Backspace)
    assert dlg.model.elements == []
    dlg.model.undo()
    _marquee(page, (0.05, 0.05), (0.7, 0.3))
    dlg.delete_btn.click()
    assert dlg.model.elements == []


def test_arrow_keys_nudge_the_group_and_shift_makes_it_bigger(tmp_path):
    dlg, page, _ = _dialog_with_group(tmp_path)
    QTest.keyClick(dlg, Qt.Key_Right)
    shape = next(e for e in dlg.model.elements if e["type"] == "shape")
    assert shape["x0"] == pytest.approx(0.3 + 0.004)
    QTest.keyClick(dlg, Qt.Key_Down, Qt.ShiftModifier)
    stroke = next(e for e in dlg.model.elements if e["type"] == "stroke")
    assert stroke["points"][0]["y"] == pytest.approx(0.1 + 0.02)
    assert len(dlg.model._undo_stack) == 2  # one undo step per keypress


def test_escape_clears_the_group_selection(tmp_path):
    dlg, page, _ = _dialog_with_group(tmp_path)
    QTest.keyClick(dlg, Qt.Key_Escape)
    assert dlg.model.selected_ids == [] and len(dlg.model.elements) == 3


def test_a_moved_group_exports_cleanly(tmp_path):
    dlg, page, input_path = _dialog_with_group(tmp_path)
    QTest.mousePress(page, Qt.LeftButton, Qt.NoModifier, _px(page, 0.25, 0.15))
    QTest.mouseMove(page, QPoint(1, 1))  # clamp hard against the corner
    QTest.mouseRelease(page, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    _assert_exports_cleanly(dlg, input_path)


# ---- Edit PDF: one-row toolbar ----


def _toolbar_dialog(tmp_path=None):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    dlg = EditPdfDialog()
    dlg.on_files_changed([])
    return dlg


def test_toolbar_is_a_single_row_with_the_modes_in_the_web_order():
    dlg = _toolbar_dialog()
    bar = dlg._toolbar_widget.layout()
    assert type(bar).__name__ == "QHBoxLayout"
    modes = []
    for i in range(bar.count()):
        widget = bar.itemAt(i).widget()
        if widget is not None and widget.objectName() == "modeButton":
            modes.append(widget.accessibleName())
    assert modes == ["Select", "Edit Text", "Draw", "Shapes", "Highlight", "Insert Image", "Add Text", "Eraser"]


def test_toolbar_has_no_separate_action_or_arrange_rows():
    dlg = _toolbar_dialog()
    # Everything - modes, history, arrange, clipboard AND the option rows - lives
    # in the one toolbar widget; nothing is stacked beneath it but the pages.
    for widget in (
        dlg.select_btn, dlg.eraser_btn, dlg.undo_btn, dlg.redo_btn, dlg.arrange_btn, dlg.copy_btn, dlg.cut_btn,
        dlg.paste_btn, dlg.delete_btn, dlg._draw_options, dlg._shapes_options, dlg._highlight_options, dlg._text_options,
    ):
        assert widget.parentWidget() is dlg._toolbar_widget
    outer = dlg.preview_widget.layout()
    assert [outer.itemAt(i).widget() for i in range(outer.count())] == [dlg._toolbar_scroll, dlg._scroll]


def test_toolbar_scrolls_sideways_instead_of_wrapping_when_narrow():
    dlg = _toolbar_dialog()
    assert dlg._toolbar_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dlg._toolbar_scroll.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOff
    assert dlg._toolbar_scroll.widgetResizable()
    assert dlg._toolbar_scroll.height() <= 60  # one row's worth, not several


def test_only_the_active_mode_shows_its_name():
    dlg = _toolbar_dialog()
    dlg.draw_btn.click()
    labels = {b.accessibleName(): b.text() for b in dlg._mode_buttons.values()}
    assert labels["Draw"] == "Draw"
    assert all(text == "" for name, text in labels.items() if name != "Draw")
    dlg.eraser_btn.click()
    assert dlg.eraser_btn.text() == "Eraser" and dlg.draw_btn.text() == ""
    assert [b.isChecked() for b in dlg._mode_buttons.values()].count(True) == 1


def test_switching_mode_swaps_the_inline_options():
    dlg = _toolbar_dialog()
    for button, visible in (
        (dlg.draw_btn, "_draw_options"), (dlg.shapes_btn, "_shapes_options"),
        (dlg.highlight_btn, "_highlight_options"), (dlg.edit_text_btn, "_text_options"),
    ):
        button.click()
        shown = [n for n in ("_draw_options", "_shapes_options", "_highlight_options", "_text_options") if not getattr(dlg, n).isHidden()]
        assert shown == [visible]
    dlg.select_btn.click()
    assert all(getattr(dlg, n).isHidden() for n in ("_draw_options", "_shapes_options", "_highlight_options", "_text_options"))


def test_undo_redo_and_selection_buttons_enable_only_when_they_can_act():
    dlg = _toolbar_dialog()
    assert not dlg.undo_btn.isEnabled() and not dlg.redo_btn.isEnabled()
    assert not dlg.arrange_btn.isEnabled() and not dlg.copy_btn.isEnabled()
    assert not dlg.cut_btn.isEnabled() and not dlg.delete_btn.isEnabled() and not dlg.paste_btn.isEnabled()
    dlg.model.add(_shape_element(x0=0.2, y0=0.2, x1=0.5, y1=0.5))  # add() selects it
    assert dlg.undo_btn.isEnabled() and not dlg.redo_btn.isEnabled()
    assert dlg.arrange_btn.isEnabled() and dlg.copy_btn.isEnabled() and dlg.delete_btn.isEnabled()
    dlg.copy_btn.click()
    assert dlg.paste_btn.isEnabled()
    dlg.undo_btn.click()
    assert dlg.model.elements == [] and dlg.redo_btn.isEnabled() and not dlg.undo_btn.isEnabled()
    assert not dlg.delete_btn.isEnabled()  # nothing selected any more
    dlg.redo_btn.click()
    assert len(dlg.model.elements) == 1


def test_toolbar_state_follows_the_model_after_a_new_file_is_loaded(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(_single_page_pdf(tmp_path, "a.pdf"))])
    dlg.model.add(_shape_element(x0=0.2, y0=0.2, x1=0.5, y1=0.5))
    old_model = dlg.model
    assert dlg.undo_btn.isEnabled()
    dlg.on_files_changed([str(_single_page_pdf(tmp_path, "b.pdf"))])  # a fresh model
    assert not dlg.undo_btn.isEnabled() and not dlg.delete_btn.isEnabled()
    assert dlg._refresh_toolbar_state not in old_model.on_change  # no dangling listener
    dlg.model.add(_shape_element(x0=0.2, y0=0.2, x1=0.5, y1=0.5))
    assert dlg.undo_btn.isEnabled()


def test_arrange_menu_reorders_the_selected_element():
    dlg = _toolbar_dialog()
    first = dlg.model.add(_shape_element(x0=0.1, y0=0.1, x1=0.3, y1=0.3))
    dlg.model.add(_shape_element(x0=0.4, y0=0.4, x1=0.6, y1=0.6))
    dlg.model.select(first)
    labels = [a.text() for a in dlg.arrange_btn.menu().actions()]
    assert labels == ["Bring to Front", "Forward", "Backward", "Send to Back"]
    dlg.arrange_btn.menu().actions()[0].trigger()  # Bring to Front
    assert dlg.model.elements[-1]["id"] == first
    dlg.arrange_btn.menu().actions()[3].trigger()  # Send to Back
    assert dlg.model.elements[0]["id"] == first


def test_toolbar_delete_cut_and_paste_buttons_act_on_the_selection():
    dlg = _toolbar_dialog()
    dlg.model.add(_shape_element(x0=0.2, y0=0.2, x1=0.5, y1=0.5))
    dlg.cut_btn.click()
    assert dlg.model.elements == []
    dlg.paste_btn.click()
    assert len(dlg.model.elements) == 1
    dlg.delete_btn.click()
    assert dlg.model.elements == []


def test_toolbar_icon_buttons_do_not_take_keyboard_focus():
    dlg = _toolbar_dialog()
    for btn in (dlg.undo_btn, dlg.redo_btn, dlg.copy_btn, dlg.cut_btn, dlg.paste_btn, dlg.delete_btn):
        assert btn.focusPolicy() == Qt.NoFocus and btn.toolTip() and btn.accessibleName()


# ---- Edit PDF: page fit, zoom, lazy rendering, slim file bar ----


def _tall_pdf(tmp_path, pages, name="tall.pdf"):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=595, height=842)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


def _shown_edit_dialog(tmp_path, pages=1, size=(1300, 800)):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    dlg = EditPdfDialog()
    dlg.resize(*size)
    dlg.show()
    _app.processEvents()
    dlg.on_files_changed([_tall_pdf(tmp_path, pages)])
    _app.processEvents()
    return dlg


def test_pages_fit_the_window_width_and_are_centred(tmp_path):
    dlg = _shown_edit_dialog(tmp_path)
    page = dlg._page_widgets[0]
    assert page.width() == dlg._compute_fit_width() <= 900
    assert page.width() > 450  # much bigger than the old fixed 450px-tall thumbnails
    assert page.height() == pytest.approx(page.width() * 842 / 595, abs=1)
    assert dlg._container_layout.alignment() & Qt.AlignHCenter
    centre = page.geometry().center().x()
    assert centre == pytest.approx(dlg._container.width() / 2, abs=2)


def test_the_page_is_drawn_at_the_size_it_is_shown(tmp_path):
    dlg = _shown_edit_dialog(tmp_path)
    page = dlg._page_widgets[0]
    assert page.has_pixmap and page.rendered_width == page.width()
    assert page.px_per_pt == pytest.approx(page.width() / 595)


def test_zoom_steps_resize_pages_and_keep_elements_where_they_are(tmp_path):
    dlg = _shown_edit_dialog(tmp_path)
    page = dlg._page_widgets[0]
    base_width = page.width()
    shape = dlg.model.add(_shape_element(x0=0.2, y0=0.2, x1=0.5, y1=0.4))
    before = dict(dlg.model.elements[0])
    dlg.zoom_in_btn.click()
    assert dlg.zoom_label_btn.text() == "125%"
    assert page.width() == pytest.approx(base_width * 1.25, abs=1)
    assert page.rendered_width == page.width()  # redrawn sharp at the new size
    assert dlg.model.elements[0] == before  # fractions: nothing moved
    dlg.zoom_out_btn.click()
    dlg.zoom_out_btn.click()
    assert dlg.zoom_label_btn.text() == "75%"
    assert page.width() == pytest.approx(base_width * 0.75, abs=1)
    dlg.zoom_label_btn.click()
    assert dlg.zoom_label_btn.text() == "100%" and page.width() == base_width


def test_zoom_stops_at_both_ends(tmp_path):
    dlg = _shown_edit_dialog(tmp_path)
    for _ in range(20):
        dlg.zoom_out_btn.click()
    assert dlg.zoom_label_btn.text() == "50%" and not dlg.zoom_out_btn.isEnabled() and dlg.zoom_in_btn.isEnabled()
    for _ in range(20):
        dlg.zoom_in_btn.click()
    assert dlg.zoom_label_btn.text() == "300%" and not dlg.zoom_in_btn.isEnabled() and dlg.zoom_out_btn.isEnabled()


def test_ctrl_scroll_and_shortcuts_zoom(tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    dlg = _shown_edit_dialog(tmp_path)
    viewport = dlg._scroll.viewport()

    def wheel(dy, mods):
        event = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, dy), Qt.NoButton, mods, Qt.NoScrollPhase, False)
        QApplication.sendEvent(viewport, event)

    wheel(120, Qt.ControlModifier)
    assert dlg.zoom_label_btn.text() == "125%"
    wheel(-120, Qt.ControlModifier)
    wheel(-120, Qt.ControlModifier)
    assert dlg.zoom_label_btn.text() == "75%"
    wheel(120, Qt.NoModifier)  # a plain scroll must not zoom
    assert dlg.zoom_label_btn.text() == "75%"
    dlg._handle_shortcut("zoom_reset")
    assert dlg.zoom_label_btn.text() == "100%"
    dlg._handle_shortcut("zoom_in")
    dlg._handle_shortcut("zoom_in")
    assert dlg.zoom_label_btn.text() == "150%"
    dlg._handle_shortcut("zoom_out")
    assert dlg.zoom_label_btn.text() == "125%"


def test_zoom_keeps_working_and_committing_while_a_text_editor_is_open(tmp_path):
    dlg = _shown_edit_dialog(tmp_path)
    page = dlg._page_widgets[0]
    page.create_mode = "new_text"
    click = QPoint(int(page.width() * 0.3), int(page.height() * 0.3))
    QTest.mousePress(page, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(page._text_editor, "Hello")
    dlg._set_zoom(3)  # an open editor is positioned in pixels, so zoom must commit it first
    assert page._text_editor is None
    assert [e["text"] for e in dlg.model.elements if e["type"] == "new_text"] == ["Hello"]


def test_only_pages_near_the_viewport_are_drawn_and_far_ones_are_freed(tmp_path):
    dlg = _shown_edit_dialog(tmp_path, pages=25)
    first, last = dlg._page_widgets[0], dlg._page_widgets[-1]
    assert first.has_pixmap and not last.has_pixmap
    bar = dlg._scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    dlg._render_pages()
    assert last.has_pixmap and not first.has_pixmap  # scrolled away: memory handed back
    assert sum(1 for w in dlg._page_widgets if w.has_pixmap) < 10


def test_an_undrawn_page_is_blank_white_but_still_shows_its_elements(tmp_path):
    dlg = _shown_edit_dialog(tmp_path, pages=25)
    last = dlg._page_widgets[-1]
    assert not last.has_pixmap
    dlg.model.add({"page": 25, "type": "shape", "shape": "rectangle", "x0": 0.2, "y0": 0.2, "x1": 0.6, "y1": 0.6,
                   "color": "#ff0000", "width": 3, "filled": True})
    image = last.grab().toImage()
    assert QColor(image.pixel(5, 5)).name() == "#ffffff"
    assert QColor(image.pixel(int(last.width() * 0.4), int(last.height() * 0.4))).red() > 200
    assert QColor(image.pixel(int(last.width() * 0.4), int(last.height() * 0.4))).green() < 80


def test_resizing_the_window_refits_the_pages(tmp_path):
    dlg = _shown_edit_dialog(tmp_path, size=(1300, 800))
    wide = dlg._page_widgets[0].width()
    dlg.resize(700, 800)
    _app.processEvents()
    dlg._refit()  # (the resize timer would do this a moment later)
    assert dlg._page_widgets[0].width() < wide
    assert dlg._page_widgets[0].width() == dlg._compute_fit_width()


def test_clicking_a_page_gives_it_the_keyboard():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    assert widget.focusPolicy() == Qt.ClickFocus  # so Delete / arrows / Esc reach the dialog


def test_single_file_tools_show_the_file_name_on_a_slim_bar_not_in_a_list(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    dlg = EditPdfDialog()
    default_text = dlg._pick_btn.text()
    path = _tall_pdf(tmp_path, 1, "my report.pdf")
    dlg.file_list.addItem(path)
    assert dlg.file_list.isHidden()
    assert "my report.pdf" in dlg._pick_btn.text() and "Change file" in dlg._pick_btn.text()
    assert dlg._pick_btn.property("compact") is True
    dlg.file_list.clear()
    assert dlg._pick_btn.text() == default_text and dlg._pick_btn.property("compact") is False


def test_multi_file_tools_still_list_their_files(tmp_path):
    from app.ui.dialogs.organize_dialogs import MergeDialog

    dlg = MergeDialog()
    dlg.file_list.addItem(_tall_pdf(tmp_path, 1, "a.pdf"))
    dlg.file_list.addItem(_tall_pdf(tmp_path, 1, "b.pdf"))
    assert not dlg.file_list.isHidden()
    assert dlg._pick_btn.property("compact") is False


def test_a_canvas_tool_puts_back_and_title_on_one_line_and_other_tools_stack_them():
    from PySide6.QtWidgets import QBoxLayout

    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    window = _themed_main_window()
    window.open_tool("Edit PDF", EditPdfDialog)
    assert window._tool_header.direction() == QBoxLayout.LeftToRight
    window.open_tool("Rotate PDF", RotateDialog)
    assert window._tool_header.direction() == QBoxLayout.TopToBottom


# ---- Page tools (Crop, Redact, Sign, PDF Forms, Compare): fit, zoom, lazy pages ----


def _signature_png(tmp_path):
    pixmap = QPixmap(200, 80)
    pixmap.fill(Qt.blue)
    path = str(tmp_path / "sig.png")
    pixmap.save(path, "PNG")
    return path


def _shown_page_tool(kind, tmp_path, pages=1, size=(1300, 800)):
    """A page tool (crop/redact/sign/forms) shown in a window with a file loaded."""
    from app.ui.dialogs.edit_dialogs import CropDialog, FillFormDialog, RedactDialog, SignDialog

    dlg = {"crop": CropDialog, "redact": RedactDialog, "sign": SignDialog, "forms": FillFormDialog}[kind]()
    dlg.resize(*size)
    dlg.show()
    _app.processEvents()
    if kind == "sign":
        dlg.use_signature_file(_signature_png(tmp_path))
    dlg.on_files_changed([_tall_pdf(tmp_path, pages)])
    _settle(dlg)
    return dlg


def _settle(dlg):
    """Lets the layout finish so the scroll range is real (with the app theme
    applied it lands a moment after the pages are added)."""
    import time

    bar = dlg._scroll.verticalScrollBar()
    for _ in range(40):
        _app.processEvents()
        if bar.maximum() > 0:
            break
        time.sleep(0.02)


PAGE_TOOLS = ["crop", "redact", "sign", "forms"]


@pytest.mark.parametrize("kind", PAGE_TOOLS)
def test_page_tools_show_big_centred_pages_that_fit_the_window(kind, tmp_path):
    dlg = _shown_page_tool(kind, tmp_path)
    page = dlg._zoom_pages()[0]
    assert page.width() == dlg._compute_fit_width() <= 900
    assert page.width() > 450  # was a fixed 450px-tall thumbnail
    assert page.height() == pytest.approx(page.width() * 842 / 595, abs=1)
    assert page.has_pixmap and page.rendered_width == page.width()
    assert dlg._container_layout.alignment() & Qt.AlignHCenter
    assert page.geometry().center().x() == pytest.approx(dlg._container.width() / 2, abs=2) if hasattr(dlg, "_container") else True


@pytest.mark.parametrize("kind", PAGE_TOOLS)
def test_page_tools_zoom_with_buttons_wheel_and_shortcuts(kind, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    dlg = _shown_page_tool(kind, tmp_path)
    page = dlg._zoom_pages()[0]
    base = page.width()
    dlg.zoom_in_btn.click()
    assert dlg.zoom_label_btn.text() == "125%" and page.width() == pytest.approx(base * 1.25, abs=1)
    assert page.rendered_width == page.width()  # redrawn sharp at the new size
    viewport = dlg._scroll.viewport()
    event = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(viewport, event)
    assert dlg.zoom_label_btn.text() == "100%"
    dlg.zoom_out_btn.click()
    assert page.width() == pytest.approx(base * 0.75, abs=1)
    dlg.zoom_label_btn.click()
    assert page.width() == base
    for _ in range(20):
        dlg.zoom_in_btn.click()
    assert dlg.zoom_label_btn.text() == "300%" and not dlg.zoom_in_btn.isEnabled()


@pytest.mark.parametrize("kind", PAGE_TOOLS)
def test_page_tools_draw_only_pages_near_the_view(kind, tmp_path):
    dlg = _shown_page_tool(kind, tmp_path, pages=25)
    pages = dlg._zoom_pages()
    assert len(pages) == 25
    assert pages[0].has_pixmap and not pages[-1].has_pixmap
    bar = dlg._scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    dlg._render_pages()
    assert pages[-1].has_pixmap and not pages[0].has_pixmap


@pytest.mark.parametrize("kind", PAGE_TOOLS)
def test_page_tools_refit_when_the_window_is_resized(kind, tmp_path):
    dlg = _shown_page_tool(kind, tmp_path, size=(1300, 800))
    wide = dlg._zoom_pages()[0].width()
    dlg.resize(700, 800)
    _app.processEvents()
    dlg._refit()
    assert dlg._zoom_pages()[0].width() < wide
    assert dlg._zoom_pages()[0].width() == dlg._compute_fit_width()


def test_redact_boxes_survive_zoom_because_they_are_page_fractions(tmp_path):
    dlg = _shown_page_tool("redact", tmp_path)
    page = dlg._page_widgets[0]
    _drag(page, [_px(page, 0.2, 0.2), _px(page, 0.6, 0.4)])
    before = [dict(b) for b in page.boxes]
    dlg.zoom_in_btn.click()
    assert [dict(b) for b in page.boxes] == before
    assert dlg.gather_params()["redactions"][0]["page"] == 1


def test_crop_mirrors_follow_the_box_at_any_zoom(tmp_path):
    dlg = _shown_page_tool("crop", tmp_path, pages=3)
    _drag(dlg.overlay, [_px(dlg.overlay, 0.2, 0.2), _px(dlg.overlay, 0.6, 0.4)])
    assert all(m.single_box() for m in dlg._mirrors) and len(dlg._mirrors) == 2
    dlg.zoom_in_btn.click()
    dlg.zoom_in_btn.click()
    assert all(m.width() == dlg.overlay.width() for m in dlg._mirrors)
    assert all(m.single_box() == dlg.overlay.single_box() for m in dlg._mirrors)
    assert dlg.gather_params()["box"] is not None


def test_sign_placements_survive_zoom_and_export(tmp_path):
    dlg = _shown_page_tool("sign", tmp_path)
    page = dlg._page_widgets[0]
    QTest.mouseClick(page, Qt.LeftButton, Qt.NoModifier, _px(page, 0.5, 0.5))
    assert len(page.placements) == 1
    before = dict(page.placements[0])
    dlg.zoom_in_btn.click()
    assert page.placements[0] == before
    out = dlg.run_operation([_tall_pdf(tmp_path, 1, "in.pdf")], dlg.gather_params())[0]
    with fitz.open(out) as doc:
        assert doc[0].get_images()


def test_forms_fields_stay_on_their_spots_when_zoomed_and_keep_their_values(tmp_path):
    from app.ui.dialogs.edit_dialogs import FillFormDialog

    dlg = FillFormDialog()
    dlg.resize(1300, 800)
    dlg.show()
    _app.processEvents()
    dlg.on_files_changed([_build_form_fixture(tmp_path)])
    _app.processEvents()
    frame = dlg._zoom_pages()[0]
    key = next(k for k, w in dlg.fields_widget._field_widgets.items() if isinstance(w, QLineEdit))
    field = dlg.fields_widget._field_widgets[key]
    field.setText("typed by the user")
    fx, fy = field.x() / frame.width(), field.y() / frame.height()
    fw = field.width() / frame.width()
    dlg.zoom_in_btn.click()
    dlg.zoom_in_btn.click()
    assert field.x() / frame.width() == pytest.approx(fx, abs=0.01)
    assert field.y() / frame.height() == pytest.approx(fy, abs=0.01)
    assert field.width() / frame.width() == pytest.approx(fw, abs=0.01)
    assert field.text() == "typed by the user"
    assert any(v["value"] == "typed by the user" for v in dlg.fields_widget.values())


def test_compare_panes_fit_the_window_and_zoom(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    a = _tall_pdf(tmp_path, 1, "a.pdf")
    b = _tall_pdf(tmp_path, 1, "b.pdf")
    dlg = CompareDialog()
    dlg.resize(1300, 800)
    dlg.show()
    _app.processEvents()
    dlg.on_files_changed([a, b])
    _app.processEvents()
    fit = dlg._compute_fit_width()
    assert dlg.visual_a.width() == fit == dlg.visual_b.width()
    assert fit > 400  # was a fixed 400x560
    dlg.zoom_in_btn.click()
    assert dlg.visual_a.width() == pytest.approx(fit * 1.25, abs=1)
    dlg.zoom_out_btn.click()
    dlg.zoom_out_btn.click()
    assert dlg.visual_a.width() == pytest.approx(fit * 0.75, abs=1)
    dlg.resize(800, 800)
    _app.processEvents()
    dlg._refit()
    assert dlg.visual_a.width() < fit * 0.75 + 1 or dlg._compute_fit_width() < fit


def test_get_page_sizes_reads_every_page_in_one_pass(tmp_path):
    from app.core.pdf_ops import get_page_sizes

    doc = fitz.open()
    doc.new_page(width=300, height=400)
    doc.new_page(width=500, height=200)
    rotated = doc.new_page(width=300, height=400)
    rotated.set_rotation(90)
    path = tmp_path / "mixed.pdf"
    doc.save(str(path))
    doc.close()
    assert get_page_sizes(str(path)) == [(300.0, 400.0), (500.0, 200.0), (400.0, 300.0)]


def test_delete_key_does_nothing_while_a_dropdown_has_focus_but_works_otherwise(tmp_path, monkeypatch):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    from PySide6.QtWidgets import QApplication as App

    dlg = EditPdfDialog()
    dlg.on_files_changed([])
    dlg.model.add(_shape_element(x0=0.2, y0=0.2, x1=0.5, y1=0.5))  # add() selects it
    monkeypatch.setattr(App, "focusWidget", staticmethod(lambda: dlg.shape_type_combo))
    QTest.keyClick(dlg, Qt.Key_Backspace)
    QTest.keyClick(dlg, Qt.Key_Delete)
    assert len(dlg.model.elements) == 1  # a drop-down's focus must not delete the element
    monkeypatch.setattr(App, "focusWidget", staticmethod(lambda: dlg.select_btn))
    QTest.keyClick(dlg, Qt.Key_Delete)
    assert dlg.model.elements == []  # a focused toolbar button still lets Delete work
