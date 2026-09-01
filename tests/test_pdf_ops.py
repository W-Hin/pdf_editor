import fitz
import pytest

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf, get_page_count, merge_pdfs, extract_pages, remove_pages, reorder_pages, split_pdf, rotate_pages, add_watermark


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
