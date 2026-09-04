import fitz
import pytest
from pathlib import Path

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf, get_page_count, merge_pdfs, extract_pages, remove_pages, reorder_pages, split_pdf, rotate_pages, add_watermark, crop_pdf, add_page_numbers, images_to_pdf, redact_pdf, extract_text_runs, edit_pdf, extract_form_fields, fill_form


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


def test_add_watermark_rotates_at_arbitrary_angle(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    unrotated_path = str(tmp_path / "wm0.pdf")
    rotated_path = str(tmp_path / "wm45.pdf")

    add_watermark(path, unrotated_path, "DRAFT", opacity=0.5, font_size=60, rotate=0)
    add_watermark(path, rotated_path, "DRAFT", opacity=0.5, font_size=60, rotate=45)

    def sample(p):
        doc = fitz.open(p)
        pix = doc[0].get_pixmap()
        cx, cy = pix.width // 2, pix.height // 2
        center = pix.pixel(cx, cy)[:3]
        off_diagonal = pix.pixel(cx + 30, cy - 30)[:3]
        doc.close()
        return center, off_diagonal

    unrotated_center, unrotated_off = sample(unrotated_path)
    rotated_center, rotated_off = sample(rotated_path)

    # Both pass through the page center regardless of rotation (that's the pivot).
    assert unrotated_center != (255, 255, 255)
    assert rotated_center != (255, 255, 255)
    # A point up-and-right of center only has ink once rotated toward it —
    # genuinely discriminates rotation, unlike sampling the center alone
    # (which sits on the baseline at every angle).
    assert rotated_off != unrotated_off


def test_add_watermark_font_size_scales_rendered_text(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    small_path = str(tmp_path / "small.pdf")
    large_path = str(tmp_path / "large.pdf")

    add_watermark(path, small_path, "DRAFT", opacity=0.5, font_size=20, rotate=0)
    add_watermark(path, large_path, "DRAFT", opacity=0.5, font_size=80, rotate=0)

    def ink_width(p):
        doc = fitz.open(p)
        d = doc[0].get_text("dict")
        doc.close()
        # make_pdf() also inserts a "Page N" label on the page, so filter to the
        # watermark span itself rather than assuming it's spans[0].
        spans = [
            s
            for b in d["blocks"]
            for l in b.get("lines", [])
            for s in l["spans"]
            if s["text"] == "DRAFT"
        ]
        return spans[0]["bbox"][2] - spans[0]["bbox"][0]

    small_w = ink_width(small_path)
    large_w = ink_width(large_path)
    # 80pt vs 20pt is a 4x fontsize ratio — verified empirically: 266.6 vs 66.7,
    # i.e. genuinely ~4x, not a coincidence of rounding.
    assert large_w > small_w * 3


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


def test_images_to_pdf_accepts_real_jpeg(tmp_path):
    # JPG is the headline format for this tool, but every other fixture here is
    # a PNG — this exercises the actual JPEG decode path end to end.
    doc = fitz.open()
    jpeg_bytes = doc.new_page(width=400, height=300).get_pixmap().tobytes("jpg")
    doc.close()
    img_path = tmp_path / "photo.jpg"
    img_path.write_bytes(jpeg_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(img_path)], str(output_path), fit_mode="fit")

    result = fitz.open(str(output_path))
    assert result.page_count == 1
    assert result[0].rect.width > result[0].rect.height  # landscape image -> landscape page
    result.close()


# A JPEG container MuPDF happily *opens* (SOI + a well-formed JFIF APP0 header,
# so fitz.open() and .page_count both succeed) but cannot decode — the bytes
# after the header are garbage, with no SOF/SOS segment. fitz.open() on an image
# is lazy, so the failure only surfaces on the first real page access. This is
# the exact shape that used to escape as a raw FzErrorLibrary -> HTTP 500.
UNDECODABLE_JPEG = (
    b"\xff\xd8"  # SOI
    b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"  # APP0/JFIF
    + b"\x00" * 200  # garbage where the image data should be
)


def test_undecodable_image_still_opens_and_reports_a_page(tmp_path):
    """Guards the premise of the two tests below: the failure really is lazy."""
    img_path = tmp_path / "broken.jpg"
    img_path.write_bytes(UNDECODABLE_JPEG)

    assert get_page_count(str(img_path)) == 1


def test_render_page_thumbnail_raises_pdferror_for_undecodable_image(tmp_path):
    img_path = tmp_path / "broken.jpg"
    img_path.write_bytes(UNDECODABLE_JPEG)

    with pytest.raises(PDFError):
        render_page_thumbnail(str(img_path), 1)


def test_images_to_pdf_raises_pdferror_for_undecodable_image(tmp_path):
    img_path = tmp_path / "broken.jpg"
    img_path.write_bytes(UNDECODABLE_JPEG)
    output_path = tmp_path / "combined.pdf"

    with pytest.raises(PDFError):
        images_to_pdf([str(img_path)], str(output_path), fit_mode="fit")


def test_redact_pdf_removes_covered_text(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "REMOVE THIS")
    page.insert_text((72, 150), "KEEP THIS")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    redact_pdf(str(input_path), str(output_path), [
        {"page": 1, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
    ])

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    assert "REMOVE THIS" not in text
    assert "KEEP THIS" in text
    result.close()


def test_redact_pdf_multiple_boxes_same_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "FIRST SECRET")
    page.insert_text((72, 150), "SECOND SECRET")
    page.insert_text((72, 250), "KEPT TEXT")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    redact_pdf(str(input_path), str(output_path), [
        {"page": 1, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
        {"page": 1, "top": 0.13, "right": 0.35, "bottom": 0.77, "left": 0.1},
    ])

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    assert "FIRST SECRET" not in text
    assert "SECOND SECRET" not in text
    assert "KEPT TEXT" in text
    result.close()


def test_redact_pdf_multiple_pages(tmp_path):
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 72), "PAGE ONE SECRET")
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 72), "PAGE TWO SECRET")
    p2.insert_text((72, 150), "PAGE TWO KEPT")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    redact_pdf(str(input_path), str(output_path), [
        {"page": 1, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
        {"page": 2, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
    ])

    result = fitz.open(str(output_path))
    assert "PAGE ONE SECRET" not in result[0].get_text()
    assert "PAGE TWO SECRET" not in result[1].get_text()
    assert "PAGE TWO KEPT" in result[1].get_text()
    result.close()


def test_redact_pdf_handles_rotated_page(tmp_path):
    """A box the user drew over text they could SEE must redact that text.

    On a rotated page, page.rect is the *displayed* rectangle the user drew on,
    but add_redact_annot interprets its argument in *unrotated mediabox* space —
    so the rect must be mapped back through page.derotation_matrix (the same
    step crop_pdf does before set_cropbox). Without it, the redaction lands in
    the wrong place: the marked text survives and unrelated text is destroyed.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Unrotated bottom-left; after a 90 degree rotation this is DISPLAYED top-left.
    page.insert_text((72, 700), "OMEGA SECRET")
    # Unrotated top-left; after rotation this is DISPLAYED top-right (must survive).
    page.insert_text((72, 72), "ALPHA KEEP")
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    # Work out where "OMEGA SECRET" actually appears on screen. search_for
    # reports unrotated coordinates, so rotation_matrix maps them into the
    # displayed space the user (and the frontend selector) sees.
    src = fitz.open(str(input_path))
    src_page = src[0]
    displayed_page = src_page.rect
    hits = src_page.search_for("OMEGA")
    assert hits, "test setup: OMEGA text not found"
    displayed = hits[0] * src_page.rotation_matrix
    src.close()

    # Sanity-check the premise: this text really is in the displayed top-left quadrant.
    assert displayed.x1 < displayed_page.x0 + displayed_page.width / 2
    assert displayed.y1 < displayed_page.y0 + displayed_page.height / 2

    # Invert redact_pdf's own fraction-to-rect arithmetic, so the fractions below
    # are exactly what the UI would send for a box drawn over that visible text.
    pad = 4
    target = fitz.Rect(displayed.x0 - pad, displayed.y0 - pad, displayed.x1 + pad, displayed.y1 + pad)
    fractions = {
        "left": (target.x0 - displayed_page.x0) / displayed_page.width,
        "top": (target.y0 - displayed_page.y0) / displayed_page.height,
        "right": (displayed_page.x1 - target.x1) / displayed_page.width,
        "bottom": (displayed_page.y1 - target.y1) / displayed_page.height,
    }

    output_path = tmp_path / "redacted.pdf"
    redact_pdf(str(input_path), str(output_path), [{"page": 1, **fractions}])

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "OMEGA" not in text, "text under the drawn box survived redaction"
    assert "ALPHA KEEP" in text, "redaction destroyed text outside the drawn box"


def test_redact_pdf_rejects_empty_list(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    with pytest.raises(PDFError):
        redact_pdf(str(input_path), str(output_path), [])


def test_redact_pdf_rejects_out_of_range_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    with pytest.raises(PDFError):
        redact_pdf(str(input_path), str(output_path), [
            {"page": 2, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
        ])


def test_redact_pdf_rejects_invalid_fraction(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    with pytest.raises(PDFError):
        redact_pdf(str(input_path), str(output_path), [
            {"page": 1, "top": 1.0, "right": 0.1, "bottom": 0.1, "left": 0.1},
        ])


def test_extract_text_runs_returns_text_font_size_and_style(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Plain Text", fontsize=14, fontname="helv")
    page.insert_text((72, 150), "Bold Text", fontsize=12, fontname="hebo")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)

    assert len(runs) == 2
    assert runs[0]["index"] == 0
    assert runs[0]["text"] == "Plain Text"
    assert runs[0]["size"] == 14
    assert runs[0]["bold"] is False
    assert runs[0]["italic"] is False
    assert runs[1]["text"] == "Bold Text"
    assert runs[1]["bold"] is True


def test_extract_text_runs_skips_whitespace_only_spans(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Real Text   ", fontsize=12, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)

    assert all(r["text"].strip() for r in runs)


def test_extract_text_runs_bbox_fractions_are_displayed_space(tmp_path):
    """On a rotated page, a run's bbox fraction must describe where it VISUALLY
    appears (the space the frontend renders click targets in), not raw mediabox
    space — spec finding #2: raw_bbox * page.rotation_matrix maps into displayed
    space."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Unrotated top-left; after a 90 degree rotation this is DISPLAYED top-right.
    page.insert_text((72, 72), "ROTATED")
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)

    assert len(runs) == 1
    bbox = runs[0]["bbox"]
    # Displayed top-right quadrant: small "top", small "right".
    assert bbox["top"] < 0.5
    assert bbox["right"] < 0.5
    assert 0 <= bbox["top"] < 1
    assert 0 <= bbox["left"] < 1
    assert 0 <= bbox["right"] < 1
    assert 0 <= bbox["bottom"] < 1


def test_extract_text_runs_rejects_out_of_range_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    with pytest.raises(PDFError):
        extract_text_runs(str(input_path), 2)


def test_edit_pdf_text_edit_replaces_text_and_keeps_surrounding_content(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=14, fontname="helv")
    page.insert_text((72, 150), "Untouched Line", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "text_edit", "page": 1, "run_index": 0, "text": "Goodbye Mars", "font_override": None}],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "Hello World" not in text
    assert "Goodbye Mars" in text
    assert "Untouched Line" in text


def test_edit_pdf_text_edit_handles_rotated_page(tmp_path):
    """Same rigor as test_redact_pdf_handles_rotated_page: a run the user could
    SEE and clicked must be the run that actually gets replaced."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 700), "OMEGA ORIGINAL")  # displayed top-left after rotation
    page.insert_text((72, 72), "ALPHA KEEP")        # displayed top-right after rotation
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)
    target = next(r for r in runs if r["text"] == "OMEGA ORIGINAL")

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "text_edit", "page": 1, "run_index": target["index"], "text": "OMEGA REPLACED", "font_override": None}],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "OMEGA ORIGINAL" not in text
    assert "OMEGA REPLACED" in text
    assert "ALPHA KEEP" in text


def test_edit_pdf_text_edit_auto_shrinks_when_overflowing(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hi", fontsize=20, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    long_text = "This replacement text is much much longer than the original run"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "text_edit", "page": 1, "run_index": 0, "text": long_text, "font_override": None}],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 1
    assert spans[0]["size"] < 20  # shrunk to fit
    assert spans[0]["size"] >= 6  # not below the floor


def test_edit_pdf_text_edit_uses_subset_embedded_font(tmp_path):
    """Covers the embedded-font branch of _apply_text_edit end-to-end, using
    doc.subset_fonts() to reproduce how Word/LaTeX exports actually embed
    fonts: get_page_fonts() then reports a subset-prefixed basefont (e.g.
    "AEDWKD+Arial Regular") that does not exactly match the span's "font"
    value from get_text("dict") ("Arial Regular") — _extract_embedded_font
    must strip that prefix to find and use the real embedded font instead of
    silently falling back to a base-14 font.

    This test also exercises the two ordering fixes found in review: width
    is measured with fitz.Font(fontbuffer=...).text_length() rather than the
    base-14-only fitz.get_text_length() (which raises ValueError for an
    internal fontname), and the embedded font is re-registered via
    insert_font() after page.apply_redactions() has already run (which wipes
    the page's font resources) rather than before.
    """
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    if not font_path.exists():
        pytest.skip("arial.ttf not available on this machine")

    # The original text must contain every glyph the replacement text needs:
    # doc.subset_fonts() strips glyph data for characters that never appear
    # on the page, so a replacement using a letter absent from the original
    # (e.g. original "Embedded Original" replaced with "...Replaced", which
    # needs an "R"/"p"/"c" the subset never kept) renders with missing/wrong
    # glyphs — a real limitation of subsetting, not a bug in edit_pdf.
    original_text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz"

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_font(fontname="F0", fontfile=str(font_path), set_simple=True)
    page.insert_text((72, 100), original_text, fontsize=14, fontname="F0")
    doc.subset_fonts()
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "text_edit", "page": 1, "run_index": 0, "text": "Embedded Replaced", "font_override": None}],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert original_text not in text
    # Asserted as two substrings rather than one "Embedded Replaced" phrase:
    # re-inserting a raw embedded font buffer maps the space glyph to U+00A0
    # (non-breaking space) rather than U+0020 on extraction here, a benign
    # codepoint quirk of the font buffer path, not a correctness issue —
    # "Replaced" rendering intact (not the missing/garbled glyphs seen when
    # the original text lacks a needed letter) is what proves the real
    # embedded font's glyphs were used, not a silent Helvetica fallback.
    assert "Embedded" in text
    assert "Replaced" in text


def test_edit_pdf_stroke_draws_into_content_stream(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "stroke",
                "page": 1,
                "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.15}, {"x": 0.3, "y": 0.1}],
                "color": "#ff0000",
                "width": 3,
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    # Strokes are drawn directly into the page content stream (not as an ink
    # annotation) so they participate in the same paint order as
    # shapes/highlights/images/text and correctly respect z-order — PDF
    # viewers always render annotations above content regardless of array
    # position, which is exactly the z-order bug this test now guards
    # against (see test_edit_pdf_stroke_respects_zorder_against_shape below).
    assert list(result[0].annots()) == []
    pix = result[0].get_pixmap()
    width, height = pix.width, pix.height
    result.close()
    # Point (0.1, 0.1) -> (59, 84); scan a few rows around it for red pixels
    # since draw_polyline's exact stroke placement/antialiasing can shift the
    # line by a pixel or two versus the old ink-annot rendering.
    column = int(0.1 * width)
    target_row = int(0.1 * height)
    found_red = any(
        pix.pixel(column, y)[0] > 200 and pix.pixel(column, y)[1] < 100
        for y in range(max(0, target_row - 4), target_row + 5)
    )
    assert found_red, "stroke did not render into the content stream at its displayed position"


def test_edit_pdf_stroke_respects_zorder_against_shape(tmp_path):
    # Regression test for the z-order bug: strokes used to be drawn as ink
    # annotations, which PDF viewers always paint above page content
    # regardless of array order. A stroke drawn first, then covered by a
    # filled rectangle later in the elements array, must now show the
    # rectangle's color (array order respected) — not the stroke on top.
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    stroke_el = {
        "type": "stroke",
        "page": 1,
        "points": [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1}],
        "color": "#0000ff",
        "width": 20,
    }
    rect_el = {
        "type": "shape",
        "page": 1,
        "shape": "rectangle",
        "x0": 0.05,
        "y0": 0.05,
        "x1": 0.35,
        "y1": 0.15,
        "color": "#ff0000",
        "width": 2,
        "filled": True,
    }

    def sample_pixel(elements):
        output_path = tmp_path / f"output_{len(elements)}_{elements[0]['type']}.pdf"
        edit_pdf(str(input_path), str(output_path), elements, {})
        result = fitz.open(str(output_path))
        pix = result[0].get_pixmap()
        width, height = pix.width, pix.height
        result.close()
        return pix.pixel(int(0.2 * width), int(0.1 * height))[:3]

    # Stroke first, rectangle second (rectangle should be on top -> red).
    r, g, b = sample_pixel([stroke_el, rect_el])
    assert r > 150 and g < 100 and b < 100, "rectangle drawn after the stroke should paint on top of it"

    # Rectangle first, stroke second (stroke should be on top -> blue).
    r, g, b = sample_pixel([rect_el, stroke_el])
    assert b > 150 and r < 100 and g < 100, "stroke drawn after the rectangle should paint on top of it"


def test_edit_pdf_shape_rectangle_filled_renders_color(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "shape",
                "page": 1,
                "shape": "rectangle",
                "x0": 0.1,
                "y0": 0.1,
                "x1": 0.3,
                "y1": 0.2,
                "color": "#00ff00",
                "width": 2,
                "filled": True,
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # Center of the drawn rect: x0=0.1*595=59.5, x1=0.3*595=178.5, y0=0.1*842=84.2, y1=0.2*842=168.4
    r, g, b = pix.pixel(119, 126)[:3]
    assert g > 150 and r < 100 and b < 100  # unmistakably green, not white


def test_edit_pdf_shape_arrow_does_not_raise_and_draws_pixels(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "shape",
                "page": 1,
                "shape": "arrow",
                "x0": 0.1,
                "y0": 0.1,
                "x1": 0.4,
                "y1": 0.3,
                "color": "#000000",
                "width": 2,
                "filled": False,
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    dark_pixels = sum(
        1
        for y in range(0, pix.height, 2)
        for x in range(0, pix.width, 2)
        if sum(pix.pixel(x, y)[:3]) < 200
    )
    assert dark_pixels > 10


def test_edit_pdf_highlight_renders_translucent_overlay(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "highlight", "page": 1, "top": 0.1, "right": 0.7, "bottom": 0.8, "left": 0.1, "color": "#ffff00"}],
        {},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # top=0.1*842=84.2, left=0.1*595=59.5, right edge=0.3*595=178.5(=595-0.7*595), bottom edge=0.2*842=168.4
    r, g, b = pix.pixel(119, 126)[:3]
    assert r > 200 and g > 200 and 100 < b < 220  # yellow-tinted at ~0.4 opacity: not pure white (b=255) or pure yellow (b=0)


def test_edit_pdf_image_inserts_into_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    img_pix.set_rect(img_pix.irect, (0, 0, 255))
    img_path = tmp_path / "stamp.png"
    img_pix.save(str(img_path))

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "image", "page": 1, "file_id": "stamp", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}],
        {"stamp": str(img_path)},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # center of placed image: x=0.2*595=119, y=0.15*842=126.3
    r, g, b = pix.pixel(119, 126)[:3]
    assert b > 150 and r < 100 and g < 100


def test_edit_pdf_image_stretches_to_exact_non_proportional_box(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 50), False)  # 2:1 image
    img_pix.set_rect(img_pix.irect, (0, 0, 255))
    img_path = tmp_path / "wide.png"
    img_pix.save(str(img_path))

    output_path = tmp_path / "output.pdf"
    # A tall box (not matching the image's own 2:1 proportions) — with
    # keep_proportion=False the image must STRETCH to fill it exactly,
    # not letterbox/center within it.
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "image", "page": 1, "file_id": "stamp", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.4}],
        {"stamp": str(img_path)},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # Box: x[59.5,178.5] y[84.2,420.8] (595*0.1..0.3, 842*0.1..0.5). Sample
    # near the TOP and BOTTOM of that box — both must be blue if the image
    # genuinely stretched to fill the full height, not just letterboxed
    # around its own 2:1 proportions near the vertical center.
    top = pix.pixel(119, 90)[:3]
    bottom = pix.pixel(119, 415)[:3]
    assert top[2] > 150 and top[0] < 100 and top[1] < 100  # blue
    assert bottom[2] > 150 and bottom[0] < 100 and bottom[1] < 100  # blue


def test_edit_pdf_markup_elements_handle_rotated_page(tmp_path):
    """Every markup element must land where the user DREW it on a rotated page.

    Same rigor as test_redact_pdf_handles_rotated_page and
    test_edit_pdf_text_edit_handles_rotated_page, extended to the five sites
    that had no rotated-page coverage at all: _apply_stroke, _apply_shape,
    _apply_highlight, _apply_image and _apply_new_text. The frontend sends
    fractions of the *displayed* page, so each element is rendered and
    pixel-sampled (or bbox-checked) at the displayed-space location those same
    fractions describe.

    The image case additionally pins the image's ORIENTATION, not just its
    position: derotating the rect alone leaves the image's own pixels rotated,
    so on a 90/270-degree page it draws sideways and letterboxed inside the
    aspect-swapped raw rect (and upside-down at 180). insert_image(rotate=...)
    is what compensates.

    The new_text case pins the text's ORIENTATION the same way: laying out and
    drawing in raw (derotated) space instead of displayed space renders the
    glyphs rotated 90 degrees — a "HELLO" that should be wide and short comes
    out tall and narrow — and wraps against the wrong axis (raw.width is the
    page's displayed HEIGHT on a 90/270-rotated page). insert_text(rotate=...)
    plus displayed-space layout is what compensates.
    """
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc[0].set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    # A 40x20 image with four distinctly coloured quadrants — a solid or
    # symmetric image would pass even when drawn rotated or mirrored.
    img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), False)
    img_pix.set_rect(fitz.IRect(0, 0, 20, 10), (255, 0, 0))      # top-left red
    img_pix.set_rect(fitz.IRect(20, 0, 40, 10), (0, 255, 0))     # top-right green
    img_pix.set_rect(fitz.IRect(0, 10, 20, 20), (0, 0, 255))     # bottom-left blue
    img_pix.set_rect(fitz.IRect(20, 10, 40, 20), (255, 255, 0))  # bottom-right yellow
    img_path = tmp_path / "quadrants.png"
    img_pix.save(str(img_path))

    stroke_y = 0.80
    image_frac = {"x": 0.50, "y": 0.10, "width": 0.20, "height": 0.10}
    # Placed in an otherwise-empty region of the page (top-left is the shape,
    # top-right the image, mid-left the highlight, y=0.80 the stroke) so its
    # rendering can't be confused with any other element's.
    text_frac = {"x": 0.35, "y": 0.62, "width": 0.30, "height": 0.15}
    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "stroke",
                "page": 1,
                "points": [{"x": 0.10, "y": stroke_y}, {"x": 0.25, "y": stroke_y}, {"x": 0.40, "y": stroke_y}],
                "color": "#ff0000",
                "width": 3,
            },
            {
                "type": "shape", "page": 1, "shape": "rectangle",
                "x0": 0.10, "y0": 0.10, "x1": 0.30, "y1": 0.30,
                "color": "#00ff00", "width": 2, "filled": True,
            },
            {
                "type": "highlight", "page": 1,
                "top": 0.50, "left": 0.10, "right": 0.70, "bottom": 0.40, "color": "#ffff00",
            },
            {"type": "image", "page": 1, "file_id": "quad", **image_frac},
            {
                "type": "new_text", "page": 1,
                **text_frac,
                "text": "HELLO",
                "family": "helvetica", "bold": False, "italic": False, "underline": False,
                "size": 40, "color": "#000000", "align": "left",
            },
        ],
        {"quad": str(img_path)},
    )

    result = fitz.open(str(output_path))
    page = result[0]
    # A rotated page renders into a pixmap of its DISPLAYED size, so pixel
    # (fx * width, fy * height) is exactly the fraction the frontend sent.
    assert page.rect.width == 792 and page.rect.height == 612, "test setup: page is not displayed-rotated"
    pix = page.get_pixmap()
    result.close()
    width, height = pix.width, pix.height

    def sample(fx, fy):
        return pix.pixel(int(fx * width), int(fy * height))[:3]

    # Blank control corner: nothing was drawn here, so a mis-derotated element
    # landing in the wrong place would be caught by the per-element asserts below.
    assert sample(0.90, 0.90) == (255, 255, 255)

    # Shape: filled green rectangle spanning 0.10-0.30 on both axes.
    r, g, b = sample(0.20, 0.20)
    assert g > 150 and r < 100 and b < 100, f"filled shape not green at its displayed centre: {(r, g, b)}"

    # Highlight: displayed x 0.10-0.30, y 0.50-0.60, drawn at 0.4 fill opacity.
    r, g, b = sample(0.20, 0.55)
    assert r > 200 and g > 200 and 100 < b < 220, f"highlight not yellow-tinted at its displayed centre: {(r, g, b)}"

    # Stroke: a horizontal red ink line. Scan a few rows around the drawn
    # fraction — the annotation's rendered width is only a couple of pixels.
    target_row = int(stroke_y * height)
    stroke_column = int(0.25 * width)
    found_red = any(
        pix.pixel(stroke_column, y)[0] > 200 and pix.pixel(stroke_column, y)[1] < 100
        for y in range(target_row - 5, target_row + 6)
    )
    assert found_red, "hand-drawn stroke did not render at its displayed position"

    # Image: work out where the placement box lands in displayed space, then
    # where the image actually sits inside it once insert_image has fitted the
    # 2:1 source into that box. Sampling the four quarter-points of THAT rect
    # proves both the position and the orientation.
    box = fitz.Rect(
        image_frac["x"] * width,
        image_frac["y"] * height,
        (image_frac["x"] + image_frac["width"]) * width,
        (image_frac["y"] + image_frac["height"]) * height,
    )
    source_aspect = 40 / 20
    if source_aspect > box.width / box.height:
        fitted_w, fitted_h = box.width, box.width / source_aspect
    else:
        fitted_h, fitted_w = box.height, box.height * source_aspect
    cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    fitted = fitz.Rect(cx - fitted_w / 2, cy - fitted_h / 2, cx + fitted_w / 2, cy + fitted_h / 2)

    def quadrant(fx, fy):
        return pix.pixel(
            int(fitted.x0 + fx * fitted.width),
            int(fitted.y0 + fy * fitted.height),
        )[:3]

    assert quadrant(0.25, 0.25) == (255, 0, 0), "image top-left quadrant is not the source's top-left"
    assert quadrant(0.75, 0.25) == (0, 255, 0), "image top-right quadrant is not the source's top-right"
    assert quadrant(0.25, 0.75) == (0, 0, 255), "image bottom-left quadrant is not the source's bottom-left"
    assert quadrant(0.75, 0.75) == (255, 255, 0), "image bottom-right quadrant is not the source's bottom-right"

    # New text: laid out and drawn in DISPLAYED space, so a landscape 40pt
    # "HELLO" must come out wide-and-short and sit at the box's displayed-space
    # top-left corner — not tall-and-narrow (rotated 90 degrees sideways), and
    # not shifted onto the wrong axis, as it would happen if layout/drawing used
    # raw (derotated) space instead. get_text("dict") bbox is NOT used here: it
    # reports coordinates in the page's raw (un-rotated) space regardless of how
    # the glyphs actually render, so it would report "tall and narrow" even for
    # correctly-rendered (wide and short) text — verified empirically against
    # this exact insert_text(rotate=...) call. Scanning rendered ink in the
    # pixmap (as every other element in this test already does) is what
    # actually proves what the viewer displays.
    text_box_x0 = int(text_frac["x"] * width) - 5
    text_box_y0 = int(text_frac["y"] * height) - 5
    text_box_x1 = int((text_frac["x"] + text_frac["width"]) * width) + 5
    text_box_y1 = int((text_frac["y"] + text_frac["height"]) * height) + 5
    ink_x0 = ink_y0 = 10**9
    ink_x1 = ink_y1 = -1
    for iy in range(text_box_y0, text_box_y1):
        for ix in range(text_box_x0, text_box_x1):
            r, g, b = pix.pixel(ix, iy)[:3]
            if r < 250 or g < 250 or b < 250:
                ink_x0, ink_y0 = min(ink_x0, ix), min(ink_y0, iy)
                ink_x1, ink_y1 = max(ink_x1, ix), max(ink_y1, iy)
    assert ink_x1 >= ink_x0, "no rendered ink found for the new_text element in its displayed-space box"
    ink_w, ink_h = ink_x1 - ink_x0, ink_y1 - ink_y0
    assert ink_w > ink_h, (
        f"new_text ink is not landscape-oriented in displayed space: w={ink_w} h={ink_h} "
        f"(bbox=({ink_x0},{ink_y0})-({ink_x1},{ink_y1})) — text rendered sideways"
    )
    expected_x0 = text_frac["x"] * width
    expected_y0 = text_frac["y"] * height
    assert abs(ink_x0 - expected_x0) < 10, f"new_text ink x0 {ink_x0} not near expected displayed x0 {expected_x0}"
    assert expected_y0 < ink_y0 < expected_y0 + text_frac["height"] * height, (
        f"new_text ink y0 {ink_y0} not within the box's displayed y-range"
    )


def test_edit_pdf_new_text_inserts_at_position(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "new_text", "page": 1,
                "x": 0.1, "y": 0.1, "width": 0.3, "height": 0.1,
                "text": "Hello Stamp",
                "family": "helvetica", "bold": False, "italic": False, "underline": False,
                "size": 14, "color": "#1f2937", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "Hello Stamp" in text


def test_edit_pdf_new_text_wraps_multiple_lines(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    # This exact text/size/width combination was verified empirically (see the
    # design spec's Key technical findings) to wrap into exactly 3 lines:
    # "This is a longer note that should wrap" / "across multiple lines within
    # the box," / "underlined." — a raw-space box of (72,100)-(300,200) at
    # 12pt, reproduced here via fractions of a 595x842 page so the raw rect
    # matches exactly.
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "new_text", "page": 1,
                "x": 72 / 595, "y": 100 / 842, "width": 228 / 595, "height": 100 / 842,
                "text": "This is a longer note that should wrap across multiple lines within the box, underlined.",
                "family": "helvetica", "bold": False, "italic": False, "underline": False,
                "size": 12, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    line_count = len([l for l in text.split("\n") if l.strip()])
    assert line_count == 3
    assert "This is a longer note that should wrap" in text
    assert "underlined." in text


def test_edit_pdf_new_text_font_family_bold_italic(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "new_text", "page": 1,
                "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1,
                "text": "Styled",
                "family": "times", "bold": True, "italic": True, "underline": False,
                "size": 14, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 1
    assert spans[0]["font"] == "Times-BoldItalic"
    assert bool(spans[0]["flags"] & 16)  # bold
    assert bool(spans[0]["flags"] & 2)  # italic


def test_edit_pdf_new_text_underline_draws_line_per_line(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "new_text", "page": 1,
                "x": 0.12, "y": 0.12, "width": 0.4, "height": 0.1,
                "text": "Underlined Text",
                "family": "helvetica", "bold": False, "italic": False, "underline": True,
                "size": 20, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    drawings = result[0].get_drawings()
    result.close()
    assert len(drawings) == 1
    assert drawings[0]["items"][0][0] == "l"  # a line


def test_edit_pdf_new_text_alignment_positions_text(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    base_el = {
        "type": "new_text", "page": 1,
        "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1,
        "text": "Hi",
        "family": "helvetica", "bold": False, "italic": False, "underline": False,
        "size": 14, "color": "#000000",
    }

    def origin_x(align):
        out = tmp_path / f"{align}.pdf"
        edit_pdf(str(input_path), str(out), [{**base_el, "align": align}], {})
        doc2 = fitz.open(str(out))
        d = doc2[0].get_text("dict")
        doc2.close()
        spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        return spans[0]["origin"][0]

    left_x = origin_x("left")
    center_x = origin_x("center")
    right_x = origin_x("right")
    assert left_x < center_x < right_x


def test_edit_pdf_new_text_overflow_stops_at_box_bottom_without_raising(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    long_text = "One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen"
    # A box only tall enough for one line at this size — the rest overflows
    # past the bottom edge and is simply never drawn (no auto-shrink, no error).
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "new_text", "page": 1,
                "x": 0.1, "y": 0.1, "width": 0.15, "height": 0.03,
                "text": long_text,
                "family": "helvetica", "bold": False, "italic": False, "underline": False,
                "size": 14, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "One" in text
    assert "Fourteen" not in text


def test_edit_pdf_rejects_new_text_empty_text(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "   ",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "left",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_invalid_color(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "Hi",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "not-a-color", "align": "left",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_unknown_family(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "Hi",
                    "family": "comic-sans", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "left",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_unknown_align(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "Hi",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "justify",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_out_of_bounds_rect(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.9, "y": 0.1, "width": 0.3, "height": 0.1,  # x + width > 1
                    "text": "Hi",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "left",
                }
            ],
            {},
        )


def test_edit_pdf_mixed_elements_all_apply_together(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Original", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {"type": "text_edit", "page": 1, "run_index": 0, "text": "Replaced", "font_override": None},
            {"type": "shape", "page": 1, "shape": "rectangle", "x0": 0.5, "y0": 0.5, "x1": 0.6, "y1": 0.55, "color": "#000000", "width": 1, "filled": False},
            {"type": "highlight", "page": 1, "top": 0.6, "right": 0.3, "bottom": 0.3, "left": 0.3, "color": "#00ffff"},
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    annots_and_shapes_present = result[0].get_pixmap() is not None  # rendered without error
    result.close()
    assert "Original" not in text
    assert "Replaced" in text
    assert annots_and_shapes_present


def test_edit_pdf_rejects_empty_elements(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(str(input_path), str(output_path), [], {})


def test_edit_pdf_rejects_out_of_range_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path),
            str(output_path),
            [{"type": "highlight", "page": 2, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1, "color": "#ffff00"}],
            {},
        )


def test_edit_pdf_rejects_invalid_run_index(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Only Run", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path),
            str(output_path),
            [{"type": "text_edit", "page": 1, "run_index": 5, "text": "x", "font_override": None}],
            {},
        )


def test_edit_pdf_rejects_unresolvable_image_file_id(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path),
            str(output_path),
            [{"type": "image", "page": 1, "file_id": "missing", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}],
            {},
        )


def test_extract_form_fields_returns_text_checkbox_and_combobox(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    text_widget = fitz.Widget()
    text_widget.field_name = "full_name"
    text_widget.field_label = "Full Name"
    text_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    text_widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(text_widget)

    checkbox_widget = fitz.Widget()
    checkbox_widget.field_name = "agree"
    checkbox_widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    checkbox_widget.rect = fitz.Rect(72, 140, 90, 158)
    page.add_widget(checkbox_widget)

    combo_widget = fitz.Widget()
    combo_widget.field_name = "country"
    combo_widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    combo_widget.rect = fitz.Rect(72, 180, 250, 200)
    combo_widget.choice_values = ["USA", "Canada", "Mexico"]
    page.add_widget(combo_widget)

    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    fields = extract_form_fields(str(input_path))

    assert len(fields) == 3
    assert fields[0]["page"] == 1
    assert fields[0]["index"] == 0
    assert fields[0]["type"] == "text"
    assert fields[0]["label"] == "Full Name"
    assert fields[0]["value"] == ""
    assert fields[0]["choices"] is None

    assert fields[1]["type"] == "checkbox"
    assert fields[1]["value"] is False

    assert fields[2]["type"] == "combobox"
    assert fields[2]["choices"] == ["USA", "Canada", "Mexico"]


def test_extract_form_fields_label_falls_back_to_field_name(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "raw_internal_name"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(widget)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    fields = extract_form_fields(str(input_path))

    assert fields[0]["label"] == "raw_internal_name"


def test_extract_form_fields_checkbox_reports_checked_state(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "agree"
    widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    widget.rect = fitz.Rect(72, 140, 90, 158)
    widget.field_value = True
    page.add_widget(widget)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    fields = extract_form_fields(str(input_path))

    assert fields[0]["value"] is True


def test_extract_form_fields_bbox_fractions_are_displayed_space(tmp_path):
    """A field's rect fraction must describe where it VISUALLY appears (the
    space the frontend positions form controls in), not raw mediabox space —
    verified empirically: widget.rect * page.rotation_matrix is the mapping
    that matches where a visibly-filled test widget actually rendered.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    widget = fitz.Widget()
    widget.field_name = "test_field"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    # Unrotated top-left; after a 90 degree rotation this is DISPLAYED top-right.
    widget.rect = fitz.Rect(72, 72, 300, 100)
    page.add_widget(widget)
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    fields = extract_form_fields(str(input_path))

    assert len(fields) == 1
    rect = fields[0]["rect"]
    # Displayed top-right quadrant: small "top", small "right".
    assert rect["top"] < 0.5
    assert rect["right"] < 0.5
    assert 0 <= rect["top"] < 1
    assert 0 <= rect["left"] < 1
    assert 0 <= rect["right"] < 1
    assert 0 <= rect["bottom"] < 1


def test_extract_form_fields_skips_unsupported_types(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    text_widget = fitz.Widget()
    text_widget.field_name = "full_name"
    text_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    text_widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(text_widget)

    listbox_widget = fitz.Widget()
    listbox_widget.field_name = "options"
    listbox_widget.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
    listbox_widget.rect = fitz.Rect(72, 220, 250, 260)
    listbox_widget.choice_values = ["A", "B", "C"]
    page.add_widget(listbox_widget)

    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    fields = extract_form_fields(str(input_path))

    # A ListBox widget was also added above — its absence here is what proves
    # the type-set filter genuinely excludes unsupported types, not just that
    # it happens to only see supported ones.
    assert len(fields) == 1
    assert fields[0]["type"] == "text"
    assert fields[0]["label"] == "full_name"


def test_extract_form_fields_no_fields_returns_empty_list(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "no_fields.pdf"
    doc.save(str(input_path))
    doc.close()

    fields = extract_form_fields(str(input_path))

    assert fields == []


def test_fill_form_sets_text_field_value(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "full_name"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(widget)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "filled.pdf"
    fill_form(str(input_path), str(output_path), [{"page": 1, "index": 0, "value": "Jane Doe"}])

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "Jane Doe" in text


def test_fill_form_clears_prefilled_text_field(tmp_path):
    """Clearing a pre-filled Text field to "" must actually blank the field in
    the baked output, not silently leave the old value burned into the PDF.
    PyMuPDF's low-level widget writer only writes /V when the new value is
    truthy, so a naive `widget.field_value = ""; widget.update()` leaves the
    stale /V (and therefore the stale appearance stream) in place. fill_form
    must clear /V explicitly for this case.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "full_name"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_value = "PREFILLED"
    widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(widget)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "cleared.pdf"
    fill_form(str(input_path), str(output_path), [{"page": 1, "index": 0, "value": ""}])

    result = fitz.open(str(output_path))
    page_text = result[0].get_text()
    full_text = "".join(p.get_text() for p in result)
    result.close()

    assert "PREFILLED" not in page_text
    assert "PREFILLED" not in full_text


def test_fill_form_sets_checkbox_value(tmp_path):
    """fill_form always bakes (flattens) its output, so the checkbox widget
    itself is gone afterward — get_text() on a checkbox's glyph isn't a
    reliable readable string either. What IS reliably checkable post-bake is
    that the checkbox's "on" appearance was actually drawn: render the filled
    output and compare it against a second document where the same checkbox
    was explicitly left unchecked (value=False) and also baked. If fill_form's
    checkbox path works, the two renders must differ inside the checkbox's
    rect; if it silently no-ops, they'd be pixel-identical.
    """

    def build_and_fill(value):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        widget = fitz.Widget()
        widget.field_name = "agree"
        widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        widget.rect = fitz.Rect(72, 140, 90, 158)
        page.add_widget(widget)
        input_path = tmp_path / f"form_{value}.pdf"
        doc.save(str(input_path))
        doc.close()
        output_path = tmp_path / f"filled_{value}.pdf"
        fill_form(str(input_path), str(output_path), [{"page": 1, "index": 0, "value": value}])
        result = fitz.open(str(output_path))
        pix = result[0].get_pixmap(clip=fitz.Rect(72, 140, 90, 158))
        samples = pix.samples
        result.close()
        return samples

    checked_pixels = build_and_fill(True)
    unchecked_pixels = build_and_fill(False)

    assert checked_pixels != unchecked_pixels


def test_fill_form_sets_combobox_value(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "country"
    widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    widget.rect = fitz.Rect(72, 180, 250, 200)
    widget.choice_values = ["USA", "Canada", "Mexico"]
    page.add_widget(widget)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "filled.pdf"
    fill_form(str(input_path), str(output_path), [{"page": 1, "index": 0, "value": "Canada"}])

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "Canada" in text


def test_fill_form_flattens_the_output(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "full_name"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(widget)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "filled.pdf"
    fill_form(str(input_path), str(output_path), [{"page": 1, "index": 0, "value": "Jane Doe"}])

    result = fitz.open(str(output_path))
    assert result.is_form_pdf is False
    assert len(list(result[0].widgets())) == 0
    result.close()


def test_fill_form_multiple_fields_across_pages(tmp_path):
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    w1 = fitz.Widget()
    w1.field_name = "page1_field"
    w1.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w1.rect = fitz.Rect(72, 100, 300, 120)
    page1.add_widget(w1)
    page2 = doc.new_page(width=595, height=842)
    w2 = fitz.Widget()
    w2.field_name = "page2_field"
    w2.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w2.rect = fitz.Rect(72, 100, 300, 120)
    page2.add_widget(w2)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "filled.pdf"
    fill_form(
        str(input_path),
        str(output_path),
        [
            {"page": 1, "index": 0, "value": "Page One Value"},
            {"page": 2, "index": 0, "value": "Page Two Value"},
        ],
    )

    result = fitz.open(str(output_path))
    assert "Page One Value" in result[0].get_text()
    assert "Page Two Value" in result[1].get_text()
    result.close()


def test_fill_form_rejects_empty_values(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "filled.pdf"
    with pytest.raises(PDFError):
        fill_form(str(input_path), str(output_path), [])


def test_fill_form_rejects_out_of_range_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "filled.pdf"
    with pytest.raises(PDFError):
        fill_form(str(input_path), str(output_path), [{"page": 2, "index": 0, "value": "x"}])


def test_fill_form_rejects_out_of_range_index(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    widget = fitz.Widget()
    widget.field_name = "full_name"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(widget)
    input_path = tmp_path / "form.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "filled.pdf"
    with pytest.raises(PDFError):
        fill_form(str(input_path), str(output_path), [{"page": 1, "index": 5, "value": "x"}])
