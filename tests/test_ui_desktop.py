import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.pdf_ops import crop_pdf, render_page_thumbnail
from app.ui.widgets import RectangleOverlayWidget, SignaturePadWidget, box_to_insets, insets_to_box

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


def test_compress_dialog_still_builds_its_thumbnail_strip():
    from app.ui.dialogs.optimize_dialogs import CompressDialog

    dlg = CompressDialog()
    assert hasattr(dlg, "thumbnail_strip")
    assert hasattr(dlg, "_thumbnail_layout")
    assert dlg.quality_slider.value() == 60


def test_redact_dialog_page_switch_accumulates_and_restores_boxes(tmp_path):
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
    assert dlg.page_spin.maximum() == 2

    w, h = dlg.overlay.width(), dlg.overlay.height()

    def draw_box():
        QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
        QTest.mouseMove(dlg.overlay, QPoint(int(w * 0.6), int(h * 0.15)))
        QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    # Page 1: draw a box.
    draw_box()
    assert len(dlg.overlay.boxes) == 1

    # Switch to page 2: starts empty, draw a box there too.
    dlg.page_spin.setValue(2)
    assert dlg.overlay.boxes == []
    draw_box()
    assert len(dlg.overlay.boxes) == 1

    # Switch back to page 1: its earlier box must still be there.
    dlg.page_spin.setValue(1)
    assert len(dlg.overlay.boxes) == 1

    # Remove page 1's box via its marker.
    marker = dlg.overlay._marker_rect(dlg.overlay.boxes[0])
    click = marker.center()
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    assert dlg.overlay.boxes == []

    # gather_params must flush whatever page is CURRENTLY displayed (page 1,
    # now empty) and report only page 2's surviving box.
    params = dlg.gather_params()
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
    assert "PAGE ONE SECRET" in text_p1  # page 1's box was removed
    assert "PAGE TWO SECRET" not in text_p2  # page 2's box was kept


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
