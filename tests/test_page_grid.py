import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.page_grid import CELL_WIDTHS, GAP, LABEL_HEIGHT, PageGridWidget

_app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _close_every_window_after_each_test():
    """Tests show real windows and never close them. Left open they pile up, keep
    repainting, and keep their render threads alive into the next test (the cause of a
    rare native crash while painting a leftover thumbnail)."""
    yield
    for widget in QApplication.topLevelWidgets():
        stop = getattr(widget, "shutdown", None)
        if stop is not None:
            stop()
        widget.close()
        widget.deleteLater()
    end = time.monotonic() + 0.03
    while time.monotonic() < end:
        QApplication.processEvents()


def _pdf(tmp_path, pages=6, name="doc.pdf", sizes=None):
    doc = fitz.open()
    for i in range(pages):
        w, h = (sizes[i] if sizes else (595, 842))
        doc.new_page(width=w, height=h).insert_text((40, 60), f"Page {i + 1}", fontsize=20)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


def _pump(seconds=0.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        _app.processEvents()
        time.sleep(0.01)


def _grid(tmp_path, pages=6, mode="view", width=1000, height=700, **kw):
    grid = PageGridWidget(mode)
    grid.resize(width, height)
    grid.show()
    _pump(0.05)
    grid.set_document(_pdf(tmp_path, pages, **kw))
    _pump()
    return grid


def _click(cell):
    QTest.mouseClick(cell, Qt.LeftButton, Qt.NoModifier, cell.rect().center())


def test_one_cell_per_page_in_order_wrapping_to_the_width(tmp_path):
    grid = _grid(tmp_path, pages=9, width=1000)
    cells = grid.cells()
    assert [c.page for c in cells] == list(range(1, 10))
    cw = grid.cell_width()
    columns = (1000 - GAP - grid._scroll.verticalScrollBar().sizeHint().width() * 0) // (cw + GAP)
    tops = sorted({c.geometry().top() for c in cells})
    assert len(tops) > 1 and cells[0].geometry().top() == cells[1].geometry().top()  # a row, then wraps
    first_row = [c for c in cells if c.geometry().top() == tops[0]]
    assert 2 <= len(first_row) <= columns
    assert all(c.width() == cw for c in cells)
    assert cells[0].geometry().left() < cells[1].geometry().left()


def test_the_grid_is_centred_and_thumbnails_are_much_bigger_than_the_old_strip(tmp_path):
    grid = _grid(tmp_path, pages=12, width=1200)
    cells = grid.cells()
    assert cells[0].width() >= 200 and cells[0].box_height() >= 250  # the old strip was 100px tall in all
    top = cells[0].geometry().top()
    first_row = [c for c in cells if c.geometry().top() == top]
    assert len(first_row) >= 3
    left = first_row[0].geometry().left()
    right = grid._canvas.width() - first_row[-1].geometry().right()
    assert abs(left - right) <= 2  # a full row has equal margins either side


def test_cell_shape_follows_each_pages_own_aspect_ratio(tmp_path):
    grid = _grid(tmp_path, pages=2, sizes=[(595, 842), (842, 595)])
    portrait, landscape = grid.cells()
    assert portrait.aspect == pytest.approx(842 / 595) and landscape.aspect == pytest.approx(595 / 842)
    assert portrait._page_rect().height() > portrait._page_rect().width()
    assert landscape._page_rect().width() > landscape._page_rect().height()


def test_size_buttons_change_the_thumbnail_size_and_stop_at_the_ends(tmp_path):
    grid = _grid(tmp_path)
    base = grid.cell_width()
    grid.zoom_in_btn.click()
    assert grid.cell_width() > base and all(c.width() == grid.cell_width() for c in grid.cells())
    for _ in range(10):
        grid.zoom_in_btn.click()
    assert grid.cell_width() == CELL_WIDTHS[-1] and not grid.zoom_in_btn.isEnabled()
    for _ in range(10):
        grid.zoom_out_btn.click()
    assert grid.cell_width() == CELL_WIDTHS[0] and not grid.zoom_out_btn.isEnabled()


# ---- thumbnails ----


def test_visible_thumbnails_are_drawn_sharply_at_the_cell_size_and_redrawn_on_resize(tmp_path):
    grid = _grid(tmp_path, pages=4)
    assert all(c.has_pixmap() and c.rendered_width == c.width() for c in grid.cells())
    grid.zoom_in_btn.click()
    _pump()
    assert all(c.has_pixmap() and c.rendered_width == grid.cell_width() for c in grid.cells())


def test_only_thumbnails_near_the_view_are_drawn_and_far_ones_freed(tmp_path):
    grid = _grid(tmp_path, pages=60, height=600, sizes=[(595, 842)] * 60)
    cells = grid.cells()
    assert cells[0].has_pixmap() and not cells[-1].has_pixmap()
    bar = grid._scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    grid._render_visible()
    assert cells[-1].has_pixmap() and not cells[0].has_pixmap()


def test_thumbnails_are_drawn_off_the_ui_thread_and_stale_ones_ignored(tmp_path, monkeypatch):
    from app.ui.page_zoom import PageZoomMixin

    monkeypatch.setattr(PageZoomMixin, "_SYNC_RENDER", False)
    calls = []
    real = PageGridWidget._render_bytes

    def slow(self, key, long_side):
        calls.append(key)
        time.sleep(0.25)
        return real(self, key, long_side)

    monkeypatch.setattr(PageGridWidget, "_render_bytes", slow)
    grid = PageGridWidget("view")
    grid.resize(1000, 700)
    grid.show()
    _pump(0.05)
    started = time.perf_counter()
    grid.set_document(_pdf(tmp_path, 1))
    assert time.perf_counter() - started < 0.2  # returns at once
    _pump(0.05)
    assert not grid.cells()[0].has_pixmap()
    grid.zoom_in_btn.click()  # a new size while the first is still drawing
    end = time.monotonic() + 5
    while time.monotonic() < end and grid.cells()[0].rendered_width != grid.cell_width():
        _app.processEvents()
        time.sleep(0.01)
    time.sleep(0.4)
    _app.processEvents()
    assert grid.cells()[0].rendered_width == grid.cell_width()  # the stale picture did not overwrite it
    grid.shutdown()


def test_a_page_that_cannot_be_drawn_stays_blank_and_the_rest_show(tmp_path, monkeypatch):
    real = PageGridWidget._render_bytes

    def flaky(self, key, long_side):
        if key % 1_000_000 == 2:
            raise RuntimeError("cannot draw")
        return real(self, key, long_side)

    monkeypatch.setattr(PageGridWidget, "_render_bytes", flaky)
    grid = _grid(tmp_path, pages=3)
    a, b, c = grid.cells()
    assert a.has_pixmap() and not b.has_pixmap() and c.has_pixmap()


# ---- select mode ----


def test_clicking_a_page_marks_it_and_clicking_again_unmarks_it(tmp_path):
    grid = _grid(tmp_path, mode="select")
    emitted = []
    grid.selection_changed.connect(lambda: emitted.append(grid.selected_pages()))
    cells = grid.cells()
    _click(cells[2])
    _click(cells[0])
    assert grid.selected_pages() == [1, 3]  # page order, whatever order they were clicked in
    _click(cells[2])
    assert grid.selected_pages() == [1]
    assert emitted == [[3], [1, 3], [1]]


def test_view_mode_never_marks_pages(tmp_path):
    grid = _grid(tmp_path, mode="view")
    _click(grid.cells()[0])
    assert grid.selected_pages() == []


def test_select_all_and_clear(tmp_path):
    grid = _grid(tmp_path, pages=5, mode="select")
    grid.select_all()
    assert grid.selected_pages() == [1, 2, 3, 4, 5]
    grid.clear_selection()
    assert grid.selected_pages() == []


def test_marked_pages_are_drawn_with_a_tint_and_a_badge(tmp_path):
    grid = _grid(tmp_path, pages=2, mode="select")
    grid.select_color = "#dc2626"
    cell = grid.cells()[0]
    before = cell.grab().toImage()
    _click(cell)
    after = cell.grab().toImage()
    rect = cell._page_rect()
    x, y = int(rect.center().x()), int(rect.center().y())
    assert after.pixelColor(x, y) != before.pixelColor(x, y)  # tinted
    badge = after.pixelColor(int(rect.right() - 18 - 8), int(rect.top() + 18))  # on the disc, off the white cross
    assert badge.red() > 180 and badge.green() < 90  # the red badge disc


def test_a_new_document_clears_the_marks(tmp_path):
    grid = _grid(tmp_path, mode="select")
    _click(grid.cells()[1])
    grid.set_document(_pdf(tmp_path, 3, name="other.pdf"))
    assert grid.selected_pages() == [] and len(grid.cells()) == 3


# ---- reorder mode ----


def test_moving_a_page_reorders_the_grid_and_reports_the_new_order(tmp_path):
    grid = _grid(tmp_path, pages=5, mode="reorder")
    changes = []
    grid.order_changed.connect(lambda: changes.append(grid.order()))
    assert grid.order() == [1, 2, 3, 4, 5]
    grid._move_page(1, 3)  # page 1 dropped in the slot before the third cell
    assert grid.order() == [2, 3, 1, 4, 5]
    grid._move_page(5, 0)
    assert grid.order() == [5, 2, 3, 1, 4]
    grid._move_page(5, 1)  # back where it is: nothing changes
    assert grid.order() == [5, 2, 3, 1, 4]
    assert changes == [[2, 3, 1, 4, 5], [5, 2, 3, 1, 4]]
    on_screen = [c.page for c in sorted(grid.cells(), key=lambda c: (c.geometry().top(), c.geometry().left()))]
    assert on_screen == grid.order()  # the cells were moved to match


def test_dropping_after_the_last_cell_moves_the_page_to_the_end(tmp_path):
    grid = _grid(tmp_path, pages=4, mode="reorder")
    last = grid.cells()[-1].geometry()
    index = grid._drop_index(QPoint(last.right() - 2, last.center().y()))
    assert index == 4
    grid._move_page(1, index)
    assert grid.order() == [2, 3, 4, 1]


def test_drop_position_picks_the_slot_before_or_after_a_cell_by_which_half(tmp_path):
    grid = _grid(tmp_path, pages=3, mode="reorder")
    second = grid.cells()[1].geometry()
    assert grid._drop_index(QPoint(second.left() + 5, second.center().y())) == 1
    assert grid._drop_index(QPoint(second.right() - 5, second.center().y())) == 2


def test_a_real_drag_and_drop_reorders(tmp_path):
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent

    grid = _grid(tmp_path, pages=4, mode="reorder")
    mime = QMimeData()
    mime.setData("application/x-pdf-page", b"4")
    target = grid.cells()[0].geometry()
    pos = QPointF(target.left() + 4, target.center().y())
    event = QDropEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    # (Qt only routes a drop after a real drag-enter, so hand the event to the handler.)
    grid._canvas.dropEvent(event)
    assert grid.order() == [4, 1, 2, 3]
    assert grid._canvas.drop_line is None  # the insertion marker is cleared after the drop


# ---- sections (merge / split) ----


def test_sections_show_a_titled_group_per_file_or_page_range(tmp_path):
    a = _pdf(tmp_path, 3, name="a.pdf")
    b = _pdf(tmp_path, 2, name="b.pdf")
    grid = PageGridWidget("view")
    grid.resize(1000, 800)
    grid.show()
    grid.set_sections([{"title": "1. a.pdf", "path": a, "pages": None}, {"title": "2. b.pdf", "path": b, "pages": None}])
    _pump()
    assert [(c.section, c.page) for c in grid.cells()] == [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2)]
    assert [t.text() for t in grid._titles] == ["1. a.pdf", "2. b.pdf"]
    first_of_b = next(c for c in grid.cells() if c.section == 1)
    last_of_a = next(c for c in reversed(grid.cells()) if c.section == 0)
    assert first_of_b.geometry().top() > last_of_a.geometry().bottom()  # a new block, below the first
    assert all(c.has_pixmap() for c in grid.cells())  # each drawn from ITS OWN file


def test_a_section_can_show_just_a_range_of_pages(tmp_path):
    path = _pdf(tmp_path, 6)
    grid = PageGridWidget("view")
    grid.resize(1000, 800)
    grid.show()
    grid.set_sections([{"title": "Output 1", "path": path, "pages": [1, 2]}, {"title": "Output 2", "path": path, "pages": [3, 4]}])
    _pump()
    assert [(c.section, c.page) for c in grid.cells()] == [(0, 1), (0, 2), (1, 3), (1, 4)]


def test_only_the_first_sections_marks_are_reported(tmp_path):
    a = _pdf(tmp_path, 2, name="a.pdf")
    grid = PageGridWidget("select")
    grid.resize(1000, 800)
    grid.show()
    grid.set_sections([{"title": None, "path": a, "pages": None}, {"title": "other", "path": a, "pages": None}])
    _pump()
    _click(grid.cells()[1])
    _click(grid.cells()[3])
    assert grid.selected_pages() == [2]


# ---- live previews ----


def test_rotation_turns_the_pages_and_reflows_the_rows(tmp_path):
    grid = _grid(tmp_path, pages=2)
    cell = grid.cells()[0]
    portrait_rect = cell._page_rect()
    assert portrait_rect.height() > portrait_rect.width()
    grid.set_rotation(90)
    turned = cell._page_rect()
    assert turned.width() > turned.height()  # a quarter turn makes it landscape
    grid.set_rotation(180)
    assert cell._page_rect().height() > cell._page_rect().width()
    grid.set_rotation(-90)
    assert grid.rotation == 270


def test_the_rotated_thumbnail_really_is_drawn_turned(tmp_path):
    grid = _grid(tmp_path, pages=1)
    cell = grid.cells()[0]
    flat = cell.grab().toImage()
    grid.set_rotation(90)
    turned = cell.grab().toImage()
    assert flat != turned


def test_an_overlay_callback_is_painted_on_every_page_with_its_number_and_the_total(tmp_path):
    grid = _grid(tmp_path, pages=3)
    seen = []

    def overlay(painter, rect, page, total):
        seen.append((page, total, rect.width() > 50))
        painter.fillRect(rect, Qt.red)

    grid.set_overlay(overlay)
    _pump()
    for cell in grid.cells():
        cell.grab()
    assert {(p, t) for p, t, _ in seen} >= {(1, 3), (2, 3), (3, 3)} and all(ok for _, _, ok in seen)
    cell = grid.cells()[0]
    image = cell.grab().toImage()
    rect = cell._page_rect()
    centre = (int(rect.center().x()), int(rect.center().y()))
    assert image.pixelColor(*centre).green() < 60  # the red overlay covers the page
    grid.set_overlay(None)
    assert cell.grab().toImage().pixelColor(*centre).green() > 200  # and is gone again


def test_an_unreadable_file_gives_an_empty_grid_not_an_error(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    grid = PageGridWidget("view")
    grid.resize(800, 600)
    grid.show()
    grid.set_document(str(bad))
    assert grid.cells() == []
    grid.set_document(None)
    assert grid.cells() == []


def test_shutdown_is_safe_with_work_pending(tmp_path, monkeypatch):
    from app.ui.page_zoom import PageZoomMixin

    monkeypatch.setattr(PageZoomMixin, "_SYNC_RENDER", False)
    grid = _grid(tmp_path, pages=6)
    grid.shutdown()
    _pump(0.3)  # late results are ignored, nothing raises


# ---- Remove / Extract / Reorder pages: the dialogs built on the grid ----


def _dialog(cls, tmp_path, pages=5):
    dlg = cls()
    dlg.resize(1300, 800)
    dlg.show()
    _pump(0.05)
    path = _pdf(tmp_path, pages)
    dlg._add_files([path])
    _pump()
    return dlg, path


def _out_texts(path):
    with fitz.open(path) as doc:
        return [page.get_text().strip() for page in doc]


def test_remove_pages_click_pages_then_run_removes_exactly_those(tmp_path):
    from app.ui.dialogs.pages_dialogs import RemovePagesDialog

    dlg, path = _dialog(RemovePagesDialog, tmp_path)
    assert dlg.summary_label.text() == "No pages marked yet." and not dlg.clear_button.isEnabled()
    cells = dlg.page_grid.cells()
    _click(cells[1])
    _click(cells[3])
    assert dlg.summary_label.text() == "2 pages will be removed: 2, 4"
    _click(cells[1])
    assert dlg.summary_label.text() == "1 page will be removed: 4"  # singular
    _click(cells[1])
    out = dlg.run_operation([path], dlg.gather_params())[0]
    assert _out_texts(out) == ["Page 1", "Page 3", "Page 5"]
    assert out.endswith("_removed.pdf")


def test_remove_pages_uses_a_red_cross_and_extract_a_blue_tick(tmp_path):
    from app.ui.dialogs.pages_dialogs import ExtractPagesDialog, RemovePagesDialog

    remove, _ = _dialog(RemovePagesDialog, tmp_path)
    extract, _ = _dialog(ExtractPagesDialog, tmp_path)
    assert remove.page_grid.select_color == "#dc2626" and remove.page_grid.select_badge == "x"
    assert extract.page_grid.select_color == "#2563eb" and extract.page_grid.select_badge == "check"


def test_remove_pages_with_nothing_marked_says_what_to_do(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.pages_dialogs import RemovePagesDialog

    dlg, path = _dialog(RemovePagesDialog, tmp_path)
    with pytest.raises(PDFError, match="Click at least one page"):
        dlg.run_operation([path], dlg.gather_params())


def test_extract_pages_click_pages_then_run_keeps_only_those(tmp_path):
    from app.ui.dialogs.pages_dialogs import ExtractPagesDialog

    dlg, path = _dialog(ExtractPagesDialog, tmp_path)
    cells = dlg.page_grid.cells()
    _click(cells[4])
    _click(cells[0])
    assert dlg.summary_label.text() == "2 pages will be extracted: 1, 5"
    out = dlg.run_operation([path], dlg.gather_params())[0]
    assert _out_texts(out) == ["Page 1", "Page 5"] and out.endswith("_extracted.pdf")


def test_select_all_and_clear_buttons_and_a_long_selection_is_shortened(tmp_path):
    from app.ui.dialogs.pages_dialogs import RemovePagesDialog

    dlg, _ = _dialog(RemovePagesDialog, tmp_path, pages=20)
    dlg.select_all_button.click()
    assert len(dlg.page_grid.selected_pages()) == 20
    assert dlg.summary_label.text().startswith("20 pages will be removed: 1, 2, 3") and "(+8 more)" in dlg.summary_label.text()
    dlg.clear_button.click()
    assert dlg.page_grid.selected_pages() == [] and not dlg.clear_button.isEnabled()


def test_choosing_another_file_starts_with_nothing_marked(tmp_path):
    from app.ui.dialogs.pages_dialogs import RemovePagesDialog

    dlg, _ = _dialog(RemovePagesDialog, tmp_path)
    _click(dlg.page_grid.cells()[0])
    dlg._add_files([_pdf(tmp_path, 3, name="other.pdf")])
    _pump()
    assert dlg.page_grid.selected_pages() == [] and len(dlg.page_grid.cells()) == 3
    assert dlg.summary_label.text() == "No pages marked yet."


def test_reorder_pages_drag_then_run_writes_the_new_order(tmp_path):
    from app.ui.dialogs.pages_dialogs import ReorderPagesDialog

    dlg, path = _dialog(ReorderPagesDialog, tmp_path)
    assert dlg.summary_label.text() == "The pages are in their original order." and not dlg.reset_button.isEnabled()
    dlg.page_grid._move_page(5, 0)
    dlg.page_grid._move_page(2, 5)
    assert dlg.page_grid.order() == [5, 1, 3, 4, 2]
    assert dlg.summary_label.text() == "New order: 5, 1, 3, 4, 2" and dlg.reset_button.isEnabled()
    out = dlg.run_operation([path], dlg.gather_params())[0]
    assert _out_texts(out) == ["Page 5", "Page 1", "Page 3", "Page 4", "Page 2"]


def test_reorder_reset_restores_the_original_order(tmp_path):
    from app.ui.dialogs.pages_dialogs import ReorderPagesDialog

    dlg, _ = _dialog(ReorderPagesDialog, tmp_path)
    dlg.page_grid._move_page(3, 0)
    dlg.reset_button.click()
    assert dlg.page_grid.order() == [1, 2, 3, 4, 5]
    assert dlg.summary_label.text() == "The pages are in their original order."


def test_these_tools_show_the_side_panel_and_the_grid_together(tmp_path):
    from app.ui.dialogs.pages_dialogs import RemovePagesDialog

    dlg, _ = _dialog(RemovePagesDialog, tmp_path)
    assert not dlg.side_panel.isHidden() and dlg.preview_widget.width() > dlg.side_panel.width() * 2  # pages get the room


# ---- live previews and grouped views (Rotate, Watermark, Page numbers, Merge, Split) ----


def test_rotate_previews_the_turn_as_the_angle_changes(tmp_path):
    from app.ui.dialogs.edit_dialogs import RotateDialog

    dlg, path = _dialog(RotateDialog, tmp_path, pages=3)
    assert dlg.page_grid.rotation == 90  # the default angle is already shown
    dlg.angle_box.setCurrentText("180")
    assert dlg.page_grid.rotation == 180
    dlg.angle_box.setCurrentText("270")
    assert dlg.page_grid.rotation == 270
    cell = dlg.page_grid.cells()[0]
    assert cell._page_rect().width() > cell._page_rect().height()  # 270 turns a portrait page sideways
    out = dlg.run_operation([path], dlg.gather_params())[0]
    with fitz.open(out) as doc:
        assert all(p.rotation == 270 for p in doc)  # what was previewed is what was written


def test_watermark_text_appears_on_every_page_as_you_type_and_follows_opacity(tmp_path):
    from app.ui.dialogs.edit_dialogs import WatermarkDialog

    dlg, _ = _dialog(WatermarkDialog, tmp_path, pages=2)
    cell = dlg.page_grid.cells()[0]
    rect = cell._page_rect()
    centre = (int(rect.center().x()), int(rect.center().y()))

    def ink():
        image = cell.grab().toImage()
        return sum(1 for x in range(int(rect.left()), int(rect.right())) for y in range(int(rect.top() + rect.height() * 0.4), int(rect.top() + rect.height() * 0.6))
                   if image.pixelColor(x, y).green() < 240)

    empty = ink()
    dlg.text_input.setText("CONFIDENTIAL")
    faint = ink()
    assert faint > empty  # the text is on the page
    dlg.opacity_slider.setValue(100)
    assert ink() >= faint  # stronger opacity darkens it
    dlg.text_input.setText("   ")
    assert ink() == empty  # blank text draws nothing
    assert all(c.width() > 0 for c in dlg.page_grid.cells())


def test_page_numbers_preview_position_and_format_match_the_output(tmp_path):
    from app.ui.dialogs.edit_dialogs import AddPageNumbersDialog

    dlg, path = _dialog(AddPageNumbersDialog, tmp_path, pages=3)
    cell = dlg.page_grid.cells()[1]
    rect = cell._page_rect()

    def dark_pixels(where):
        image = cell.grab().toImage()
        x0, x1 = int(rect.left()), int(rect.right())
        y0, y1 = int(rect.top()), int(rect.bottom())
        if where == "bottom":
            y0 = y1 - int(rect.height() * 0.15)
        else:
            y1 = y0 + int(rect.height() * 0.15)
        return [(x, y) for x in range(x0, x1) for y in range(y0, y1) if image.pixelColor(x, y).lightness() < 170]

    bottom = dark_pixels("bottom")
    assert bottom, "the number should be drawn in the bottom band"
    assert abs(sum(x for x, _ in bottom) / len(bottom) - rect.center().x()) < rect.width() * 0.12  # centred
    dlg.position_box.setCurrentIndex(dlg.position_box.findData("top-center"))
    assert not dark_pixels("bottom")  # moved out of the bottom band
    dlg.position_box.setCurrentIndex(dlg.position_box.findData("bottom-right"))
    xs = [x for x, _ in dark_pixels("bottom")]
    assert xs and min(xs) > rect.center().x()  # right-aligned
    dlg.format_box.setCurrentIndex(dlg.format_box.findData("page-x-of-y"))
    assert len(dark_pixels("bottom")) > len(xs)  # "Page 2 of 3" is longer than "2"
    out = dlg.run_operation([path], dlg.gather_params())[0]
    with fitz.open(out) as doc:
        assert "Page 2 of 3" in doc[1].get_text()


def test_merge_shows_each_file_as_its_own_titled_block_in_merge_order(tmp_path):
    from app.ui.dialogs.organize_dialogs import MergeDialog

    dlg = MergeDialog()
    dlg.resize(1300, 800)
    dlg.show()
    _pump(0.05)
    a = _pdf(tmp_path, 3, name="first.pdf")
    b = _pdf(tmp_path, 2, name="second.pdf")
    dlg._add_files([a, b])
    _pump()
    grid = dlg.page_grid
    assert [t.text() for t in grid._titles] == [
        "1. first.pdf \u2014 where its pages land in the merged file",
        "2. second.pdf \u2014 where its pages land in the merged file",
    ]
    assert [(c.section, c.page) for c in grid.cells()] == [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2)]
    assert all(c.has_pixmap() for c in grid.cells())
    dlg.file_list.clear()
    assert grid.cells() == []
    out = dlg.run_operation([a, b], {"filename": "merged.pdf"})[0]
    with fitz.open(out) as doc:
        assert doc.page_count == 5  # the preview showed exactly five pages


def test_split_groups_the_pages_by_output_file_and_follows_the_setting(tmp_path):
    from app.ui.dialogs.organize_dialogs import SplitDialog

    dlg, path = _dialog(SplitDialog, tmp_path, pages=5)
    grid = dlg.page_grid
    assert [t.text() for t in grid._titles] == [f"Output file {i} \u2014 page {i}" for i in range(1, 6)]
    dlg.pages_per_file.setValue(2)
    assert [t.text() for t in grid._titles] == [
        "Output file 1 \u2014 pages 1\u20132", "Output file 2 \u2014 pages 3\u20134", "Output file 3 \u2014 page 5",
    ]
    assert [(c.section, c.page) for c in grid.cells()] == [(0, 1), (0, 2), (1, 3), (1, 4), (2, 5)]
    dlg.pages_per_file.setValue(9999)
    assert [t.text() for t in grid._titles] == ["Output file 1 \u2014 pages 1\u20135"]
    dlg.pages_per_file.setValue(2)
    outs = dlg.run_operation([path], dlg.gather_params())
    assert len(outs) == 3  # the preview promised three files


def test_split_with_a_broken_file_shows_an_empty_grid(tmp_path):
    from app.ui.dialogs.organize_dialogs import SplitDialog

    dlg = SplitDialog()
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    dlg.file_list.addItem(str(bad))
    dlg._refresh_thumbnails()
    assert dlg.page_grid.cells() == []


# ---- file chips (multi-file tools) and Compare's layout ----


def _chips(dlg):
    from PySide6.QtWidgets import QFrame, QLabel

    frames = dlg.file_chips.findChildren(QFrame, "fileChip")
    frames.sort(key=lambda f: f.geometry().left())
    return [f.findChild(QLabel).text() for f in frames]


def _merge_with(tmp_path, names=("a.pdf", "b.pdf", "c.pdf")):
    from app.ui.dialogs.organize_dialogs import MergeDialog

    dlg = MergeDialog()
    dlg.resize(1300, 800)
    dlg.show()
    _pump(0.05)
    paths = [_pdf(tmp_path, 2, name=n) for n in names]
    dlg._add_files(paths)
    _pump()
    return dlg, paths


def test_chips_show_number_and_name_with_the_full_path_on_hover(tmp_path):
    from PySide6.QtWidgets import QFrame, QLabel

    dlg, paths = _merge_with(tmp_path)
    assert _chips(dlg) == ["1  a.pdf", "2  b.pdf", "3  c.pdf"]
    label = dlg.file_chips.findChildren(QFrame, "fileChip")[0].findChild(QLabel)
    assert label.toolTip() in paths


def test_a_very_long_file_name_is_shortened_on_its_chip(tmp_path):
    dlg, _ = _merge_with(tmp_path, names=("a_really_quite_extraordinarily_long_report_name_final_v2.pdf",))
    text = _chips(dlg)[0]
    assert text.endswith("...") and len(text) <= 40


def test_merge_files_can_be_moved_and_the_preview_and_order_follow(tmp_path):
    from PySide6.QtWidgets import QPushButton

    dlg, paths = _merge_with(tmp_path)
    later = [b for b in dlg.file_chips.findChildren(QPushButton) if b.accessibleName() == "Move later"]
    earlier = [b for b in dlg.file_chips.findChildren(QPushButton) if b.accessibleName() == "Move earlier"]
    assert not earlier[0].isEnabled() and not later[-1].isEnabled()  # nowhere to go past the ends
    later[0].click()  # a moves after b
    assert [os.path.basename(p) for p in dlg.selected_files()] == ["b.pdf", "a.pdf", "c.pdf"]
    assert _chips(dlg) == ["1  b.pdf", "2  a.pdf", "3  c.pdf"]
    assert dlg.page_grid._titles[0].text().startswith("1. b.pdf")  # the preview blocks reordered too
    out = dlg.run_operation(dlg.selected_files(), {"filename": "m.pdf"})[0]
    assert fitz.open(out).page_count == 6


def test_a_file_can_be_removed_from_its_chip_and_removing_the_last_returns_to_choosing(tmp_path):
    from PySide6.QtWidgets import QPushButton

    dlg, paths = _merge_with(tmp_path, names=("a.pdf", "b.pdf"))
    removers = [b for b in dlg.file_chips.findChildren(QPushButton) if b.accessibleName() == "Remove this file"]
    removers[0].click()
    assert [os.path.basename(p) for p in dlg.selected_files()] == ["b.pdf"] and _chips(dlg) == ["1  b.pdf"]
    assert [c.section for c in dlg.page_grid.cells()] == [0, 0]
    dlg.file_chips.findChildren(QPushButton, "chipButton")[-1].click()
    assert dlg.selected_files() == [] and dlg._states.currentIndex() == 0  # back to the chooser
    assert dlg.page_grid.cells() == []


def test_only_merge_has_reorder_arrows(tmp_path):
    from PySide6.QtWidgets import QPushButton

    from app.ui.dialogs.edit_dialogs import CompareDialog

    dlg = CompareDialog()
    dlg._add_files([_pdf(tmp_path, 1, name="x.pdf"), _pdf(tmp_path, 1, name="y.pdf")])
    names = {b.accessibleName() for b in dlg.file_chips.findChildren(QPushButton)}
    assert names == {"Remove this file"}  # compare's two files are "original" and "changed": no arrows


def test_compare_gives_the_pages_the_room_and_puts_its_controls_in_the_side_panel(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    dlg = CompareDialog()
    dlg.resize(1500, 900)
    dlg.show()
    _pump(0.05)
    dlg._add_files([_pdf(tmp_path, 2, name="a.pdf"), _pdf(tmp_path, 2, name="b.pdf")])
    _pump(0.4)
    assert dlg.page_spin.parentWidget() is not None and dlg.side_panel.isAncestorOf(dlg.page_spin)
    assert dlg.side_panel.isAncestorOf(dlg.text_diff_view) and dlg.side_panel.isAncestorOf(dlg.status_label_compare)
    assert dlg.side_panel.width() == 400 and dlg.preview_widget.width() > dlg.side_panel.width() * 2
    assert dlg.side_panel.height() > 500  # as tall as the window, so the text diff has room
    assert dlg.text_diff_view.height() > 200
    assert dlg.visual_a.width() > 300 and dlg.visual_a.height() > 400  # not the old fixed 400x560 sliver


def test_compare_still_compares_after_the_layout_change(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    dlg = CompareDialog()
    dlg.resize(1500, 900)
    dlg.show()
    _pump(0.05)
    dlg._add_files([_pdf(tmp_path, 3, name="a.pdf"), _pdf(tmp_path, 3, name="b.pdf")])
    _pump(0.4)
    assert dlg.page_spin.maximum() == 3
    assert "Comparing 3 page(s)" in dlg.status_label_compare.text()
    dlg.page_spin.setValue(2)
    assert "Page 2" in dlg.text_diff_view.toPlainText()  # the text diff of the chosen page is shown
    assert dlg.run_operation([], {"file_count": 2})[1].startswith("Compared 3")


# ---- explanatory notes for tools whose result cannot be previewed (as on the web) ----


@pytest.mark.parametrize("module,cls,needle", [
    ("optimize_dialogs", "CompressDialog", "file size, not appearance"),
    ("optimize_dialogs", "RepairDialog", "internal structure"),
    ("optimize_dialogs", "OcrDialog", "invisible, searchable text layer"),
    ("optimize_dialogs", "PdfToPdfaDialog", "long-term archiving"),
    ("convert_dialogs", "ToWordDialog", "can't be previewed"),
    ("convert_dialogs", "PdfToMarkdownDialog", "extracts text and images"),
    ("convert_dialogs", "PdfToPptxDialog", "positioned text boxes"),
    ("convert_dialogs", "PdfToXlsxDialog", "detected table"),
])
def test_tools_with_no_meaningful_preview_say_so_above_the_pages(module, cls, needle, tmp_path):
    import importlib

    dialog = getattr(importlib.import_module(f"app.ui.dialogs.{module}"), cls)()
    assert needle in dialog.page_grid._hint.text()
    assert dialog.page_grid._hint.wordWrap()  # long notes wrap instead of running off the edge


def test_tools_whose_preview_is_meaningful_show_their_own_hint_not_a_note():
    from app.ui.dialogs.pages_dialogs import RemovePagesDialog

    assert "Click the pages you want to remove" in RemovePagesDialog().page_grid._hint.text()


# ---- Add watermark: size and rotation, like the web app ----


def _ink_box(image, rect, baseline=None, threshold=235):
    """Bounding box of the dark pixels inside `rect`. With a `baseline` image (the same
    cell without the watermark) only pixels that changed count, so the page's own text
    never matters - it is there or not depending on whether the thumbnail has rendered."""
    xs, ys = [], []
    for x in range(int(rect.left()) + 2, int(rect.right()) - 2):
        for y in range(int(rect.top()) + 2, int(rect.bottom()) - 2):
            green = image.pixelColor(x, y).green()
            if baseline is not None:
                if abs(green - baseline.pixelColor(x, y).green()) > 12:
                    xs.append(x)
                    ys.append(y)
            elif green < threshold:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _watermark_box(dlg, cell):
    """Where the watermark's own ink is on the cell, found by diffing against the cell with no text."""
    text = dlg.text_input.text()
    dlg.text_input.setText("")
    _pump(0.05)
    baseline = cell.grab().toImage()
    dlg.text_input.setText(text)
    _pump(0.05)
    return _ink_box(cell.grab().toImage(), cell._page_rect(), baseline)


def test_watermark_has_the_webs_controls_with_the_webs_ranges_and_defaults(tmp_path):
    from app.ui.dialogs.edit_dialogs import WatermarkDialog

    dlg = WatermarkDialog()
    assert (dlg.opacity_slider.minimum(), dlg.opacity_slider.maximum(), dlg.opacity_slider.value()) == (10, 100, 30)
    assert (dlg.font_size_slider.minimum(), dlg.font_size_slider.maximum(), dlg.font_size_slider.value()) == (10, 120, 40)
    assert (dlg.rotation_slider.minimum(), dlg.rotation_slider.maximum(), dlg.rotation_slider.value()) == (0, 360, 0)
    dlg.text_input.setText("DRAFT")
    assert dlg.gather_params() == {"text": "DRAFT", "opacity": 0.3, "font_size": 40, "rotate": 0}
    dlg.font_size_slider.setValue(90)
    dlg.rotation_slider.setValue(135)
    dlg.opacity_slider.setValue(55)
    assert dlg.gather_params() == {"text": "DRAFT", "opacity": 0.55, "font_size": 90, "rotate": 135}


def test_watermark_sliders_show_their_current_value():
    from PySide6.QtWidgets import QLabel

    from app.ui.dialogs.edit_dialogs import WatermarkDialog

    dlg = WatermarkDialog()
    dlg.font_size_slider.setValue(72)
    dlg.rotation_slider.setValue(45)
    texts = [lbl.text() for lbl in dlg.options_widget.findChildren(QLabel)]
    assert "Font size (pt): 72" in texts and "Rotation (degrees): 45" in texts and "Opacity (%): 30" in texts


def test_the_exported_watermark_uses_the_chosen_size_and_rotation(tmp_path):
    from app.ui.dialogs.edit_dialogs import WatermarkDialog

    dlg, path = _dialog(WatermarkDialog, tmp_path, pages=2)
    dlg.text_input.setText("CONFIDENTIAL")
    dlg.font_size_slider.setValue(72)
    dlg.rotation_slider.setValue(90)
    out = dlg.run_operation([path], dlg.gather_params())[0]
    with fitz.open(out) as doc:
        spans = [
            (line["dir"], span["size"])
            for block in doc[0].get_text("dict")["blocks"] if block["type"] == 0
            for line in block["lines"] for span in line["spans"] if "CONFIDENTIAL" in span["text"]
        ]
    assert spans, "the watermark text is on the page"
    (dx, dy), size = spans[0]
    assert size == pytest.approx(72) and abs(dx) < 0.01 and dy == pytest.approx(-1, abs=0.01)  # written bottom-to-top


def test_the_preview_follows_size_and_rotation_and_matches_the_exports_orientation(tmp_path):
    from app.ui.dialogs.edit_dialogs import WatermarkDialog

    dlg, path = _dialog(WatermarkDialog, tmp_path, pages=1)
    dlg.text_input.setText("CONFIDENTIAL")
    dlg.opacity_slider.setValue(100)
    cell = dlg.page_grid.cells()[0]

    def box():
        return _watermark_box(dlg, cell)

    dlg.font_size_slider.setValue(20)
    small = box()
    dlg.font_size_slider.setValue(80)
    big = box()
    assert (big[2] - big[0]) > (small[2] - small[0]) * 1.5  # a bigger font makes a wider watermark
    dlg.font_size_slider.setValue(40)
    flat = box()
    assert (flat[2] - flat[0]) > (flat[3] - flat[1]) * 3  # horizontal text: much wider than tall
    dlg.rotation_slider.setValue(90)
    upright = box()
    assert (upright[3] - upright[1]) > (upright[2] - upright[0]) * 3  # turned a quarter: much taller than wide
    # ...and the exported page turns the same way: also taller than wide.
    out = dlg.run_operation([path], dlg.gather_params())[0]
    with fitz.open(out) as doc:
        pix = doc[0].get_pixmap(dpi=72)
    xs = [x for x in range(pix.width) for y in range(0, pix.height, 2) if y > 90 and pix.pixel(x, y)[1] < 235]  # y > 90 skips the page's own "Page 1" line
    ys = [y for y in range(90, pix.height) for x in range(0, pix.width, 2) if pix.pixel(x, y)[1] < 235]
    assert ys and xs
    assert (max(ys) - min(ys)) > (max(xs) - min(xs)) * 2  # taller than wide in the real output as well


def test_a_45_degree_watermark_runs_and_previews(tmp_path):
    from app.ui.dialogs.edit_dialogs import WatermarkDialog

    dlg, path = _dialog(WatermarkDialog, tmp_path, pages=1)
    dlg.text_input.setText("DRAFT")
    dlg.rotation_slider.setValue(45)
    cell = dlg.page_grid.cells()[0]
    assert _watermark_box(dlg, cell) is not None
    out = dlg.run_operation([path], dlg.gather_params())[0]
    assert os.path.exists(out)


def test_an_empty_watermark_text_is_still_refused(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import WatermarkDialog

    dlg, path = _dialog(WatermarkDialog, tmp_path, pages=1)
    with pytest.raises(PDFError):
        dlg.run_operation([path], dlg.gather_params())


# ---- small parity fixes with the web app ----


def test_pdf_to_image_is_named_and_defaulted_like_the_web(tmp_path):
    from app.ui.dialogs.convert_dialogs import ToImagesDialog

    dlg = ToImagesDialog()
    assert dlg.title == "PDF to Image"
    assert [dlg.format_box.itemText(i) for i in range(dlg.format_box.count())] == ["jpg", "png"]
    assert dlg.gather_params() == {"image_format": "jpg"}  # the web app's default


def test_the_home_screen_lists_pdf_to_image_not_pdf_to_jpg():
    from PySide6.QtWidgets import QPushButton

    from app.main import build_main_window
    from app.ui.theme import apply_theme

    sheet, font = _app.styleSheet(), _app.font()
    apply_theme(_app)
    try:
        window = build_main_window()
        names = {c.accessibleName() for c in window._home.findChildren(QPushButton)}
    finally:  # the theme is app-wide; later tests expect the unthemed defaults
        _app.setStyleSheet(sheet)
        _app.setFont(font)
    assert "PDF to Image" in names and "PDF to JPG" not in names


def test_ocr_pdfa_checkbox_explains_itself_like_the_web():
    from app.ui.dialogs.optimize_dialogs import OcrDialog

    tip = OcrDialog().pdfa_check.toolTip()
    assert "archival format" in tip and "long-term storage" in tip


def test_unlock_needs_a_password_like_the_web(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.optimize_dialogs import UnlockDialog

    dlg = UnlockDialog()
    path = _pdf(tmp_path, 1)
    with pytest.raises(PDFError, match="password"):
        dlg.run_operation([path], {"password": ""})
