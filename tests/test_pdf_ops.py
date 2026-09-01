import fitz
import pytest

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf, get_page_count, merge_pdfs


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
