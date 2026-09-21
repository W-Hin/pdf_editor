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
