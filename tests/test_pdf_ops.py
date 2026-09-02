import fitz
import pytest
from pathlib import Path

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf, get_page_count, merge_pdfs, extract_pages, remove_pages, reorder_pages, split_pdf, rotate_pages, add_watermark, crop_pdf, add_page_numbers, images_to_pdf


def test_open_pdf_missing_file_raises(tmp_path):
    with pytest.raises(PDFError):
        open_pdf(str(tmp_path / "missing.pdf"))


def test_open_pdf_not_a_pdf_raises(tmp_path):
    bad_file = tmp_path / "not_a_pdf.pdf"
    bad_file.write_text("this is not a pdf")
    with pytest.raises(PDFError):
        open_pdf(str(bad_file))


def test_get_page_count(make_pdf):
    path = make_pdf(num_pages=4)
    assert get_page_count(path) == 4


def test_merge_pdfs_combines_page_counts(make_pdf, tmp_path):
    pdf_a = make_pdf(num_pages=2, text_prefix="A")
    pdf_b = make_pdf(num_pages=3, text_prefix="B")
    out_path = str(tmp_path / "merged.pdf")

    merge_pdfs([pdf_a, pdf_b], out_path)

    assert get_page_count(out_path) == 5
    doc = fitz.open(out_path)
    assert "A 1" in doc[0].get_text()
    assert "B 1" in doc[2].get_text()
    doc.close()


def test_merge_pdfs_requires_two_files(make_pdf, tmp_path):
    pdf_a = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        merge_pdfs([pdf_a], str(tmp_path / "out.pdf"))


def test_extract_pages_selects_in_order(make_pdf, tmp_path):
    path = make_pdf(num_pages=4)
    out_path = str(tmp_path / "extracted.pdf")

    extract_pages(path, [3, 1], out_path)

    assert get_page_count(out_path) == 2
    doc = fitz.open(out_path)
    assert "Page 3" in doc[0].get_text()
    assert "Page 1" in doc[1].get_text()
    doc.close()


def test_extract_pages_rejects_out_of_range(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    with pytest.raises(PDFError):
        extract_pages(path, [5], str(tmp_path / "out.pdf"))


def test_remove_pages_drops_selected(make_pdf, tmp_path):
    path = make_pdf(num_pages=4)
    out_path = str(tmp_path / "removed.pdf")

    remove_pages(path, [2, 3], out_path)

    assert get_page_count(out_path) == 2
    doc = fitz.open(out_path)
    assert "Page 1" in doc[0].get_text()
    assert "Page 4" in doc[1].get_text()
    doc.close()


def test_remove_pages_rejects_removing_everything(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    with pytest.raises(PDFError):
        remove_pages(path, [1, 2], str(tmp_path / "out.pdf"))


def test_reorder_pages(make_pdf, tmp_path):
    path = make_pdf(num_pages=3)
    out_path = str(tmp_path / "reordered.pdf")

    reorder_pages(path, [3, 1, 2], out_path)

    doc = fitz.open(out_path)
    assert "Page 3" in doc[0].get_text()
    assert "Page 1" in doc[1].get_text()
    assert "Page 2" in doc[2].get_text()
    doc.close()


def test_reorder_pages_rejects_incomplete_order(make_pdf, tmp_path):
    path = make_pdf(num_pages=3)
    with pytest.raises(PDFError):
        reorder_pages(path, [1, 2], str(tmp_path / "out.pdf"))


def test_split_pdf_by_ranges(make_pdf, tmp_path):
    path = make_pdf(num_pages=4)
    out_dir = str(tmp_path / "split_out")

    outputs = split_pdf(path, out_dir, [(1, 2), (3, 4)])

    assert len(outputs) == 2
    assert get_page_count(outputs[0]) == 2
    assert get_page_count(outputs[1]) == 2


def test_split_pdf_rejects_invalid_range(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    with pytest.raises(PDFError):
        split_pdf(path, str(tmp_path / "out"), [(1, 5)])


def test_rotate_pages_all(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    out_path = str(tmp_path / "rotated.pdf")

    rotate_pages(path, out_path, 90)

    doc = fitz.open(out_path)
    assert doc[0].rotation == 90
    assert doc[1].rotation == 90
    doc.close()


def test_rotate_pages_specific(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    out_path = str(tmp_path / "rotated.pdf")

    rotate_pages(path, out_path, 180, page_numbers=[1])

    doc = fitz.open(out_path)
    assert doc[0].rotation == 180
    assert doc[1].rotation == 0
    doc.close()


def test_rotate_pages_rejects_non_multiple_of_90(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        rotate_pages(path, str(tmp_path / "out.pdf"), 45)


def test_add_watermark_inserts_text(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    out_path = str(tmp_path / "watermarked.pdf")

    add_watermark(path, out_path, "CONFIDENTIAL")

    doc = fitz.open(out_path)
    assert "CONFIDENTIAL" in doc[0].get_text()
    doc.close()


def test_add_watermark_rejects_empty_text(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        add_watermark(path, str(tmp_path / "out.pdf"), "   ")


from app.core.pdf_ops import compress_pdf


def _make_pdf_with_image(tmp_path):
    path = tmp_path / "with_image.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # a small solid-color image, embedded via a Pixmap
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(fitz.Rect(0, 0, 200, 200), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_compress_pdf_keeps_page_count(tmp_path):
    path = _make_pdf_with_image(tmp_path)
    out_path = str(tmp_path / "compressed.pdf")

    compress_pdf(path, out_path, image_quality=40)

    doc = fitz.open(out_path)
    assert doc.page_count == 1
    doc.close()


def test_compress_pdf_reduces_or_maintains_size(tmp_path):
    path = _make_pdf_with_image(tmp_path)
    out_path = str(tmp_path / "compressed.pdf")

    compress_pdf(path, out_path, image_quality=10)

    original_size = Path(path).stat().st_size
    compressed_size = Path(out_path).stat().st_size
    assert compressed_size <= original_size * 1.1  # aggressive JPEG compression should not bloat the file


def test_compress_pdf_rejects_bad_quality(tmp_path):
    path = _make_pdf_with_image(tmp_path)
    with pytest.raises(PDFError):
        compress_pdf(path, str(tmp_path / "out.pdf"), image_quality=150)


from app.core.pdf_ops import render_to_images


def test_render_to_images_one_file_per_page(make_pdf, tmp_path):
    path = make_pdf(num_pages=3)
    out_dir = str(tmp_path / "images_out")

    outputs = render_to_images(path, out_dir, dpi=72, image_format="png")

    assert len(outputs) == 3
    for out_path in outputs:
        assert Path(out_path).exists()
        assert out_path.endswith(".png")


def test_render_to_images_jpg_format(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    out_dir = str(tmp_path / "images_out")

    outputs = render_to_images(path, out_dir, dpi=72, image_format="jpg")

    assert outputs[0].endswith(".jpg")
    assert Path(outputs[0]).exists()


def test_render_to_images_rejects_bad_format(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        render_to_images(path, str(tmp_path / "out"), image_format="bmp")


from app.core.pdf_ops import render_page_thumbnail


def test_render_page_thumbnail_returns_png_bytes(make_pdf):
    path = make_pdf(num_pages=2)

    data = render_page_thumbnail(path, 1, max_size=80)

    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_page_thumbnail_rejects_bad_page(make_pdf):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        render_page_thumbnail(path, 5)


def test_crop_pdf_reduces_cropbox_size(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    original_rect = fitz.open(input_path)[0].rect

    crop_pdf(input_path, str(output_path), top=0.1, right=0.1, bottom=0.1, left=0.1)

    doc = fitz.open(str(output_path))
    assert doc[0].rect.width == pytest.approx(original_rect.width * 0.8)
    assert doc[0].rect.height == pytest.approx(original_rect.height * 0.8)
    doc.close()


def test_crop_pdf_applies_same_fraction_across_mixed_page_sizes(tmp_path):
    doc = fitz.open()
    doc.new_page(width=200, height=300)
    doc.new_page(width=400, height=600)
    input_path = tmp_path / "mixed.pdf"
    doc.save(str(input_path))
    doc.close()
    output_path = tmp_path / "cropped.pdf"

    crop_pdf(str(input_path), str(output_path), top=0.1, right=0.1, bottom=0.1, left=0.1)

    result = fitz.open(str(output_path))
    assert result[0].rect.width == pytest.approx(200 * 0.8)
    assert result[0].rect.height == pytest.approx(300 * 0.8)
    assert result[1].rect.width == pytest.approx(400 * 0.8)
    assert result[1].rect.height == pytest.approx(600 * 0.8)
    result.close()


def test_crop_pdf_near_boundary_fractions_still_succeed(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"

    crop_pdf(input_path, str(output_path), top=0.49, right=0.49, bottom=0.49, left=0.49)

    doc = fitz.open(str(output_path))
    assert doc[0].rect.width > 0
    assert doc[0].rect.height > 0
    doc.close()


def test_crop_pdf_rejects_fraction_at_or_above_one(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    with pytest.raises(PDFError):
        crop_pdf(input_path, str(output_path), top=1.0, right=0.1, bottom=0.1, left=0.1)


def test_crop_pdf_allows_keeping_less_than_half_on_an_axis(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    original_rect = fitz.open(input_path)[0].rect

    crop_pdf(input_path, str(output_path), top=0.6, right=0.05, bottom=0.05, left=0.05)

    doc = fitz.open(str(output_path))
    assert doc[0].rect.width == pytest.approx(original_rect.width * 0.9)
    assert doc[0].rect.height == pytest.approx(original_rect.height * 0.35)
    doc.close()


def test_crop_pdf_rejects_fraction_sum_at_or_above_one(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    with pytest.raises(PDFError):
        crop_pdf(input_path, str(output_path), top=0.1, right=0.6, bottom=0.1, left=0.6)


def test_crop_pdf_handles_rotated_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()
    output_path = tmp_path / "cropped.pdf"

    crop_pdf(str(input_path), str(output_path), top=0.1, right=0.1, bottom=0.1, left=0.1)

    result = fitz.open(str(output_path))
    assert result[0].rotation == 90
    assert result[0].rect.width > 0
    assert result[0].rect.height > 0
    result.close()


def test_crop_pdf_rejects_negative_fraction(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    with pytest.raises(PDFError):
        crop_pdf(input_path, str(output_path), top=0.1, right=0.1, bottom=0.1, left=-0.1)


def test_add_page_numbers_page_x_of_y_format(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=3)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="bottom-center", format="page-x-of-y")

    doc = fitz.open(str(output_path))
    assert "Page 1 of 3" in doc[0].get_text()
    assert "Page 2 of 3" in doc[1].get_text()
    assert "Page 3 of 3" in doc[2].get_text()
    doc.close()


def test_add_page_numbers_number_of_total_format(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=2)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="bottom-center", format="number-of-total")

    doc = fitz.open(str(output_path))
    assert "1 / 2" in doc[0].get_text()
    doc.close()


def test_add_page_numbers_plain_number_appears_at_bottom(make_pdf, tmp_path):
    # make_pdf's own fixture text ("Page N") sits near the top-left (72, 72).
    # Checking for a standalone "1" token in the page's bottom half proves
    # add_page_numbers actually added something there — a plain substring
    # check on the whole page's text couldn't distinguish our output from
    # the fixture's own pre-existing "Page 1" text.
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="bottom-center", format="number")

    doc = fitz.open(str(output_path))
    page = doc[0]
    page_height = page.rect.height
    bottom_words = [w[4] for w in page.get_text("words") if w[1] > page_height / 2]
    assert "1" in bottom_words
    doc.close()


def test_add_page_numbers_top_position_places_text_in_top_half(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="top-right", format="number-of-total")

    doc = fitz.open(str(output_path))
    page = doc[0]
    page_height = page.rect.height
    page_width = page.rect.width
    top_right_words = [
        w[4] for w in page.get_text("words")
        if w[1] < page_height / 2 and w[0] > page_width / 2
    ]
    # A 1-page document formatted as "number-of-total" renders "1 / 1",
    # tokenized as separate words "1" and "/" — either confirms the text
    # landed in the top-right quadrant.
    assert any(w in ("1", "/") for w in top_right_words)
    doc.close()


def test_add_page_numbers_rejects_unknown_position(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"
    with pytest.raises(PDFError):
        add_page_numbers(input_path, str(output_path), position="middle", format="number")


def test_add_page_numbers_rejects_unknown_format(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"
    with pytest.raises(PDFError):
        add_page_numbers(input_path, str(output_path), position="bottom-center", format="roman")


def test_add_page_numbers_raises_pdferror_on_too_narrow_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=50, height=200)
    input_path = tmp_path / "narrow.pdf"
    doc.save(str(input_path))
    doc.close()
    output_path = tmp_path / "numbered.pdf"
    with pytest.raises(PDFError):
        add_page_numbers(str(input_path), str(output_path), position="bottom-center", format="number")


def test_images_to_pdf_single_image_produces_one_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    img_bytes = page.get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(img_path)], str(output_path), fit_mode="fit")

    result = fitz.open(str(output_path))
    assert result.page_count == 1
    result.close()


def test_images_to_pdf_mixed_orientation_pages(tmp_path):
    doc = fitz.open()
    portrait_bytes = doc.new_page(width=300, height=400).get_pixmap().tobytes("png")
    landscape_bytes = doc.new_page(width=400, height=300).get_pixmap().tobytes("png")
    doc.close()
    portrait_path = tmp_path / "portrait.png"
    landscape_path = tmp_path / "landscape.png"
    portrait_path.write_bytes(portrait_bytes)
    landscape_path.write_bytes(landscape_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(portrait_path), str(landscape_path)], str(output_path), fit_mode="fit")

    result = fitz.open(str(output_path))
    assert result.page_count == 2
    assert result[0].rect.width < result[0].rect.height  # portrait image -> portrait page
    assert result[1].rect.width > result[1].rect.height  # landscape image -> landscape page
    result.close()


def test_images_to_pdf_fit_mode_does_not_overflow_page(tmp_path):
    doc = fitz.open()
    img_bytes = doc.new_page(width=500, height=600).get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(img_path)], str(output_path), fit_mode="fit")

    result = fitz.open(str(output_path))
    result_page = result[0]
    bbox = result_page.get_image_bbox(result_page.get_images(full=True)[0])
    assert bbox.width <= result_page.rect.width + 0.01
    assert bbox.height <= result_page.rect.height + 0.01
    result.close()


def test_images_to_pdf_fill_mode_covers_page(tmp_path):
    doc = fitz.open()
    img_bytes = doc.new_page(width=500, height=600).get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(img_path)], str(output_path), fit_mode="fill")

    result = fitz.open(str(output_path))
    result_page = result[0]
    bbox = result_page.get_image_bbox(result_page.get_images(full=True)[0])
    assert bbox.width >= result_page.rect.width - 0.01
    assert bbox.height >= result_page.rect.height - 0.01
    result.close()


def test_images_to_pdf_rejects_unknown_fit_mode(tmp_path):
    doc = fitz.open()
    img_bytes = doc.new_page(width=400, height=300).get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    with pytest.raises(PDFError):
        images_to_pdf([str(img_path)], str(output_path), fit_mode="stretch")


def test_images_to_pdf_rejects_empty_list(tmp_path):
    output_path = tmp_path / "combined.pdf"
    with pytest.raises(PDFError):
        images_to_pdf([], str(output_path), fit_mode="fit")
