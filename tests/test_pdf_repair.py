import fitz
import pikepdf
import pytest

from app.core.errors import PDFError
from app.core.pdf_repair import protect_pdf, repair_pdf, unlock_pdf


def _make_pdf(path, num_pages=5):
    doc = fitz.open()
    for _ in range(num_pages):
        doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()


def test_repair_pdf_reports_healthy_file_with_no_warnings(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=5)

    output_path = tmp_path / "output.pdf"
    result = repair_pdf(str(input_path), str(output_path))

    assert result == {"page_count": 5, "warnings_count": 0}
    assert output_path.exists()


def test_repair_pdf_recovers_a_truncated_file(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=5)
    data = input_path.read_bytes()

    # Verified empirically: truncating this exact 5-page fixture to 50% of
    # its byte length is recoverable by pikepdf/qpdf, salvaging exactly 3 of
    # the 5 original pages with exactly 8 structural warnings — not an
    # assumed "original" page count, the actual number pikepdf reports at
    # this truncation level for this exact fixture shape.
    truncated_path = tmp_path / "truncated.pdf"
    truncated_path.write_bytes(data[: int(len(data) * 0.5)])

    output_path = tmp_path / "output.pdf"
    result = repair_pdf(str(truncated_path), str(output_path))

    assert result == {"page_count": 3, "warnings_count": 8}
    assert output_path.exists()


def test_repair_pdf_raises_on_unrecoverable_file(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=5)
    data = input_path.read_bytes()

    # Verified empirically: truncating to 20% of the byte length is past the
    # point even qpdf's recovery can salvage anything — pikepdf.open() itself
    # raises PdfError("...unable to find any pages while recovering damaged
    # file...").
    truncated_path = tmp_path / "truncated.pdf"
    truncated_path.write_bytes(data[: int(len(data) * 0.2)])

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        repair_pdf(str(truncated_path), str(output_path))
    assert not output_path.exists()


def test_unlock_pdf_decrypts_with_correct_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    encrypted_path = tmp_path / "encrypted.pdf"
    pdf = pikepdf.open(str(input_path))
    pdf.save(str(encrypted_path), encryption=pikepdf.Encryption(user="secret123", owner="secret123", R=6))
    pdf.close()

    output_path = tmp_path / "unlocked.pdf"
    unlock_pdf(str(encrypted_path), str(output_path), "secret123")

    result = fitz.open(str(output_path))
    assert result.is_encrypted is False
    assert result.page_count == 3
    result.close()


def test_unlock_pdf_rejects_wrong_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    encrypted_path = tmp_path / "encrypted.pdf"
    pdf = pikepdf.open(str(input_path))
    pdf.save(str(encrypted_path), encryption=pikepdf.Encryption(user="secret123", owner="secret123", R=6))
    pdf.close()

    output_path = tmp_path / "unlocked.pdf"
    with pytest.raises(PDFError) as exc_info:
        unlock_pdf(str(encrypted_path), str(output_path), "wrong")
    # The underlying pikepdf.PasswordError's message includes the raw temp
    # file path — must never leak into the user-facing error.
    assert str(encrypted_path) not in str(exc_info.value)
    assert not output_path.exists()


def test_protect_pdf_encrypts_with_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "protected.pdf"
    protect_pdf(str(input_path), str(output_path), "mypassword")

    result = fitz.open(str(output_path))
    assert result.is_encrypted is True
    result.close()
    # Confirm the exact password given actually works.
    reopened = fitz.open(str(output_path))
    reopened.authenticate("mypassword")
    assert reopened.page_count == 3
    reopened.close()


def test_protect_pdf_rejects_empty_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "protected.pdf"
    with pytest.raises(PDFError):
        protect_pdf(str(input_path), str(output_path), "")
    assert not output_path.exists()
