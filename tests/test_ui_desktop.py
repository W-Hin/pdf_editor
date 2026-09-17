import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit

from app.core.pdf_ops import crop_pdf, extract_form_fields, render_page_thumbnail
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
    # Same drag, same page dimensions as the deleted test - the exact expected
    # fraction values were already empirically verified there and reused here.
    assert params["redactions"] == [{
        "page": 2,
        "top": pytest.approx(0.04888888888888889),
        "left": pytest.approx(0.09748427672955975),
        "right": pytest.approx(0.4025157232704403),
        "bottom": pytest.approx(0.8511111111111112),
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

    w, h = dlg.overlay.width(), dlg.overlay.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    assert len(dlg.overlay.placements) == 1

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

    w, h = dlg.overlay.width(), dlg.overlay.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    assert len(dlg.overlay.placements) == 1

    # Switching to a different signature must also clear the overlay's
    # displayed placements, not just the dialog's own bookkeeping - the
    # widget would otherwise keep rendering stale boxes from the old
    # signature.
    dlg._use_different_signature()
    assert dlg.overlay.placements == []


def test_sign_dialog_page_switch_accumulates_and_restores_placements(tmp_path):
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
    dlg.use_signature_file(sig_path)  # bypasses the draw/upload UI, sets signature_path + natural size directly
    dlg.on_files_changed([str(input_path)])
    assert dlg.page_spin.maximum() == 3

    w, h = dlg.overlay.width(), dlg.overlay.height()

    def place():
        click = QPoint(int(w * 0.6), int(h * 0.7))
        QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
        QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)

    # Page 1: place a signature.
    place()
    assert len(dlg.overlay.placements) == 1

    # Switch to page 3: starts empty, place a signature there too.
    dlg.page_spin.setValue(3)
    assert dlg.overlay.placements == []
    place()
    assert len(dlg.overlay.placements) == 1

    # Switch back to page 1: its earlier placement must still be there
    # (restored from the accumulator, exercising the same flush-and-restore
    # machinery as RedactDialog's page-switch test).
    dlg.page_spin.setValue(1)
    assert len(dlg.overlay.placements) == 1

    # gather_params must flush the currently-displayed page (page 1) and
    # report placements on both page 1 and page 3, none on page 2.
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
