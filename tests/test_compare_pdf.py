from app.core.compare_pdf import diff_page_text, diff_page_visual, extract_page_texts, render_page_image


def _make_pdf(path, rect_pos=None, texts=None):
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if texts:
        y = 100
        for text in texts:
            page.insert_text((72, y), text, fontsize=14)
            y += 30
    if rect_pos:
        page.draw_rect(fitz.Rect(*rect_pos), color=(0, 0, 1), fill=(0.8, 0.8, 1))
    doc.save(str(path))
    doc.close()


def test_diff_page_text_detects_a_changed_line(tmp_path):
    path_a = tmp_path / "a.pdf"
    path_b = tmp_path / "b.pdf"
    _make_pdf(path_a, texts=["Hello World.", "Second unchanged line."])
    _make_pdf(path_b, texts=["Goodbye World.", "Second unchanged line."])

    texts_a = extract_page_texts(str(path_a))
    texts_b = extract_page_texts(str(path_b))
    result = diff_page_text(texts_a[0], texts_b[0])

    assert result == [
        {"op": "delete", "text": "Hello World."},
        {"op": "insert", "text": "Goodbye World."},
        {"op": "equal", "text": "Second unchanged line."},
    ]


def test_diff_page_visual_detects_a_shape_change_text_diff_misses(tmp_path):
    path_a = tmp_path / "a.pdf"
    path_b = tmp_path / "b.pdf"
    same_text = ["Hello World, this is a test page with some text."]
    _make_pdf(path_a, rect_pos=(100, 200, 300, 350), texts=same_text)
    _make_pdf(path_b, rect_pos=(120, 200, 320, 350), texts=same_text)

    texts_a = extract_page_texts(str(path_a))
    texts_b = extract_page_texts(str(path_b))
    text_result = diff_page_text(texts_a[0], texts_b[0])
    assert all(entry["op"] == "equal" for entry in text_result)

    boxes = diff_page_visual(str(path_a), str(path_b), 1, max_size=1800)
    assert len(boxes) >= 1
    for box in boxes:
        assert 0 <= box["x0"] < box["x1"] <= 1
        assert 0 <= box["y0"] < box["y1"] <= 1


def test_diff_page_visual_ignores_negligible_rendering_noise(tmp_path):
    path = tmp_path / "same.pdf"
    _make_pdf(path, rect_pos=(100, 200, 300, 350), texts=["Some text here."])

    boxes = diff_page_visual(str(path), str(path), 1, max_size=1800)
    assert boxes == []


def test_render_page_image_returns_png_bytes(tmp_path):
    path = tmp_path / "a.pdf"
    _make_pdf(path, texts=["Hello"])
    data = render_page_image(str(path), 1, max_size=200)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
