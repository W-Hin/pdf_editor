import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from app.core.pdf_ops import extract_page_info, extract_text_runs, get_page_rotation, get_page_size

_app = QApplication.instance() or QApplication([])


def _mixed_pdf(tmp_path, pages=4):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=300 + 50 * i, height=400)
        page.insert_text((40, 60), f"Page {i + 1} heading", fontsize=16)
        page.insert_text((40, 90), "second line", fontname="tiro", fontsize=11)
    doc[1].set_rotation(90)
    path = tmp_path / "mixed.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_extract_page_info_matches_the_per_page_functions(tmp_path):
    path = _mixed_pdf(tmp_path)
    info = extract_page_info(path)
    assert len(info) == 4
    for number, page in enumerate(info, start=1):
        assert page["runs"] == extract_text_runs(path, number)
        assert (page["width_pt"], page["height_pt"]) == get_page_size(path, number)
        assert page["rotation"] == get_page_rotation(path, number)
    assert info[1]["rotation"] == 90 and info[1]["width_pt"] == 400.0  # displayed size, rotation applied


def test_one_unreadable_page_keeps_its_size_and_the_rest_are_unaffected(tmp_path, monkeypatch):
    import app.core.pdf_ops as pdf_ops

    path = _mixed_pdf(tmp_path)
    real = pdf_ops._runs_for_page
    calls = {"n": 0}

    def flaky(page):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("bad text layer")
        return real(page)

    monkeypatch.setattr(pdf_ops, "_runs_for_page", flaky)
    info = extract_page_info(path)
    assert info[1]["runs"] == [] and info[1]["width_pt"] == 400.0
    assert info[0]["runs"] and info[2]["runs"] and info[3]["runs"]


def test_a_long_document_is_read_in_a_single_open(tmp_path, monkeypatch):
    import app.core.pdf_ops as pdf_ops

    path = _mixed_pdf(tmp_path, pages=30)
    opens = {"n": 0}
    real_open = pdf_ops.open_pdf

    def counting_open(p, *a, **k):
        opens["n"] += 1
        return real_open(p, *a, **k)

    monkeypatch.setattr(pdf_ops, "open_pdf", counting_open)
    extract_page_info(path)
    assert opens["n"] == 1  # the per-page functions would have opened it 90 times


def test_the_edit_dialog_opens_a_document_without_the_per_page_functions(tmp_path, monkeypatch):
    from app.ui.dialogs import edit_dialogs
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    def forbidden(*args, **kwargs):
        raise AssertionError("the per-page reader was used")

    monkeypatch.setattr(edit_dialogs, "extract_text_runs", forbidden)
    monkeypatch.setattr(edit_dialogs, "get_page_size", forbidden)
    monkeypatch.setattr(edit_dialogs, "get_page_rotation", forbidden)
    dlg = EditPdfDialog()
    dlg.on_files_changed([_mixed_pdf(tmp_path)])
    assert len(dlg._page_widgets) == 4
    assert dlg.model.page_info[2]["rotation"] == 90
    assert dlg.model.text_runs[1]  # the editable text is there


# ---- pages are drawn on a background thread ----


def _tall_pdf(tmp_path, pages, name="tall.pdf", height=842):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=595, height=height)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


def _wait_until(condition, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def _threaded_dialog(tmp_path, monkeypatch, delay=0.0, pages=3, height=300):
    """A shown Edit PDF dialog whose page renders run on the background thread
    (each taking `delay` seconds), plus the list of (page, long_side) requests."""
    from app.ui.dialogs import edit_dialogs
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    from app.ui.page_zoom import PageZoomMixin

    monkeypatch.setattr(PageZoomMixin, "_SYNC_RENDER", False)
    requests = []
    real = edit_dialogs.render_page_thumbnail

    def slow(path, page, max_size=100):
        requests.append((page, max_size))
        time.sleep(delay)
        return real(path, page, max_size=max_size)

    monkeypatch.setattr(edit_dialogs, "render_page_thumbnail", slow)
    dlg = EditPdfDialog()
    dlg.resize(1200, 800)
    dlg.show()
    _app.processEvents()
    dlg.on_files_changed([_tall_pdf(tmp_path, pages, height=height)])
    return dlg, requests


def test_loading_returns_at_once_and_pages_appear_afterwards(tmp_path, monkeypatch):
    dlg, _ = _threaded_dialog(tmp_path, monkeypatch, delay=0.4)
    try:
        # Three pages at 0.4s each would be over a second if drawn on this thread;
        # on_files_changed has already returned and nothing is drawn yet.
        assert not any(w.has_pixmap for w in dlg._page_widgets)
        assert [w.size() for w in dlg._page_widgets][0].width() > 450  # but the pages are laid out
        assert _wait_until(lambda: all(w.has_pixmap for w in dlg._page_widgets))
    finally:
        dlg.shutdown()


def test_the_window_stays_responsive_while_a_page_is_slow_to_draw(tmp_path, monkeypatch):
    dlg, _ = _threaded_dialog(tmp_path, monkeypatch, delay=0.5, pages=1)
    try:
        start = time.perf_counter()
        for _ in range(20):
            _app.processEvents()  # the event loop keeps turning while the render runs
        assert time.perf_counter() - start < 0.3
        assert not dlg._page_widgets[0].has_pixmap
        assert _wait_until(lambda: dlg._page_widgets[0].has_pixmap)
    finally:
        dlg.shutdown()


def test_a_picture_drawn_for_an_old_zoom_is_never_shown(tmp_path, monkeypatch):
    dlg, requests = _threaded_dialog(tmp_path, monkeypatch, delay=0.3, pages=1)
    try:
        page = dlg._page_widgets[0]
        old_width = page.width()
        dlg.zoom_in_btn.click()  # while the first (100%) render is still running
        new_width = page.width()
        assert new_width > old_width
        assert _wait_until(lambda: page.has_pixmap and page.rendered_width == new_width)
        time.sleep(0.4)
        _app.processEvents()
        assert page.rendered_width == new_width  # the stale 100% picture did not overwrite it
    finally:
        dlg.shutdown()


def test_repeated_scroll_updates_do_not_queue_the_same_page_twice(tmp_path, monkeypatch):
    dlg, requests = _threaded_dialog(tmp_path, monkeypatch, delay=0.3, pages=1)
    try:
        for _ in range(10):
            dlg._render_pages()
        assert _wait_until(lambda: dlg._page_widgets[0].has_pixmap)
        assert [r[0] for r in requests].count(1) == 1
    finally:
        dlg.shutdown()


def test_a_page_that_fails_to_draw_stays_blank_and_does_not_break_the_others(tmp_path, monkeypatch):
    from app.core.errors import PDFError
    from app.ui.dialogs import edit_dialogs

    dlg, _ = _threaded_dialog(tmp_path, monkeypatch, delay=0.0, pages=3)
    dlg.shutdown()  # discard the first (good) round; redo it with a failing page 2
    real = edit_dialogs.render_page_thumbnail

    def flaky(path, page, max_size=100):
        if page == 2:
            raise PDFError("cannot draw")
        return real(path, page, max_size=max_size)

    monkeypatch.setattr(edit_dialogs, "render_page_thumbnail", flaky)
    dlg2 = type(dlg)()
    dlg2.resize(1200, 800)
    dlg2.show()
    _app.processEvents()
    dlg2.on_files_changed([_tall_pdf(tmp_path, 3, "again.pdf", height=300)])
    try:
        assert _wait_until(lambda: dlg2._page_widgets[0].has_pixmap and dlg2._page_widgets[2].has_pixmap)
        assert not dlg2._page_widgets[1].has_pixmap
    finally:
        dlg2.shutdown()


def test_shutdown_is_safe_with_renders_still_running_and_afterwards(tmp_path, monkeypatch):
    dlg, _ = _threaded_dialog(tmp_path, monkeypatch, delay=0.3, pages=3)
    dlg.shutdown()  # must return promptly and not raise
    _app.processEvents()
    time.sleep(0.5)
    _app.processEvents()  # a late result arriving now is ignored
    assert not any(w.has_pixmap for w in dlg._page_widgets)


def test_the_main_window_stops_a_tools_rendering_when_you_leave_it(tmp_path, monkeypatch):
    from app.main import build_main_window
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    from app.ui.page_zoom import PageZoomMixin

    monkeypatch.setattr(PageZoomMixin, "_SYNC_RENDER", False)
    window = build_main_window()
    window.show()
    window.open_tool("Edit PDF", EditPdfDialog)
    tool = window._current_tool
    tool.on_files_changed([_tall_pdf(tmp_path, 3)])
    called = []
    real_shutdown = tool.shutdown
    tool.shutdown = lambda: (called.append(True), real_shutdown())
    window.show_home()
    assert called == [True]
