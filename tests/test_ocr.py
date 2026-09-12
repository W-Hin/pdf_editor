import os

import fitz
import pytest

from app.core.errors import PDFError
from app.core.ocr import ocr_pdf


def _make_image_only_pdf(path, text="This is a scanned-looking test page for OCR verification."):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), text, fontsize=14)
    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    scanned.save(str(path))
    scanned.close()
    doc.close()


def test_ocr_pdf_adds_searchable_text_to_image_only_page(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    before = fitz.open(str(input_path))
    assert before[0].get_text().strip() == ""
    before.close()

    output_path = tmp_path / "output.pdf"
    result = ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    assert result == {"pages_ocred": 1, "pages_skipped": 0}
    after = fitz.open(str(output_path))
    assert "This is a scanned-looking test page for OCR verification." in after[0].get_text()
    after.close()


def test_ocr_pdf_skips_pages_that_already_have_text(tmp_path):
    image_page_pdf = tmp_path / "image_page.pdf"
    _make_image_only_pdf(image_page_pdf, text="Image page content.")

    doc = fitz.open()
    text_page = doc.new_page(width=612, height=792)
    text_page.insert_text((72, 100), "Already has real text.", fontsize=14)
    image_src = fitz.open(str(image_page_pdf))
    doc.insert_pdf(image_src)
    image_src.close()
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    result = ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    assert result == {"pages_ocred": 1, "pages_skipped": 1}
    after = fitz.open(str(output_path))
    assert "Already has real text." in after[0].get_text()
    assert "Image page content." in after[1].get_text()
    after.close()


def _has_pdfa_identifier(path: str) -> bool:
    # Verified this session: EVERY ocrmypdf output carries some XMP metadata,
    # even with output_type="pdf" — the presence of a /Metadata key alone
    # does NOT distinguish PDF/A from plain output. The genuine PDF/A marker
    # is the pdfaid:part/pdfaid:conformance fields inside that XMP stream,
    # confirmed present only in output_type="pdfa" output and absent from
    # output_type="pdf" output on the same input.
    doc = fitz.open(path)
    try:
        xml_metadata = doc.xref_get_key(doc.pdf_catalog(), "Metadata")
        if xml_metadata[0] == "null":
            return False
        meta_xref = int(xml_metadata[1].split()[0])
        content = doc.xref_stream(meta_xref)
        return b"pdfaid:part" in content
    finally:
        doc.close()


def test_ocr_pdf_with_pdfa_checkbox_produces_pdfa_metadata(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    output_path = tmp_path / "output.pdf"
    ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=True)

    assert _has_pdfa_identifier(str(output_path))


def test_ocr_pdf_without_pdfa_checkbox_produces_plain_pdf(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    output_path = tmp_path / "output.pdf"
    ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    assert not _has_pdfa_identifier(str(output_path))


def test_ocr_pdf_rejects_empty_language_list(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    with pytest.raises(PDFError):
        ocr_pdf(str(input_path), str(tmp_path / "output.pdf"), languages=[], convert_to_pdfa=False)


def test_ocr_pdf_uses_only_vendored_binaries(tmp_path, monkeypatch):
    # Prove the app's own PATH-prepending is what makes ocrmypdf use the
    # vendored binaries, not a lucky fallback to whatever's on this dev
    # machine's system-wide PATH/Registry/Program Files.
    import app.core.ocr as ocr_module

    ocr_module._binaries_ensured = False  # reset the memoization for this test
    monkeypatch.setenv("PATH", r"C:\Windows\system32;C:\Windows")

    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)
    output_path = tmp_path / "output.pdf"

    ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    after = fitz.open(str(output_path))
    assert "This is a scanned-looking test page for OCR verification." in after[0].get_text()
    after.close()
    assert str((__import__("pathlib").Path(__file__).resolve().parent.parent / "ocr_binaries" / "tesseract")) in os.environ["PATH"]
