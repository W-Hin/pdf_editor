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


def test_protect_pdf_accepts_password_at_127_byte_boundary(tmp_path):
    # Verified empirically (see probe_password_length.py): a 127-UTF-8-byte
    # password round-trips correctly through pikepdf/qpdf's R=6 encryption —
    # this is the exact boundary the final reviewer measured as safe.
    password = "a" * 127
    assert len(password.encode("utf-8")) == 127

    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "protected.pdf"
    protect_pdf(str(input_path), str(output_path), password)

    assert output_path.exists()
    reopened = fitz.open(str(output_path))
    reopened.authenticate(password)
    assert reopened.page_count == 3
    reopened.close()


def test_protect_pdf_rejects_password_over_127_bytes(tmp_path):
    # Verified empirically (see probe_password_length.py): a 128-UTF-8-byte
    # password saves as "successfully" encrypted but the exact password typed
    # can never open the file again (pikepdf.open raises PasswordError even
    # with the correct password) — a permanently unopenable file. Must be
    # rejected before any file is written.
    password = "a" * 128
    assert len(password.encode("utf-8")) == 128

    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "protected.pdf"
    with pytest.raises(PDFError):
        protect_pdf(str(input_path), str(output_path), password)
    assert not output_path.exists()


def test_protect_pdf_rejects_multibyte_password_over_127_bytes(tmp_path):
    # A non-ASCII password whose UTF-8 byte length exceeds 127 even though its
    # character count is much smaller than 127 — confirms the check is on
    # UTF-8 byte length, not character count. "é" is 2 UTF-8 bytes each.
    password = "é" * 64  # 64 chars, but 128 UTF-8 bytes
    assert len(password.encode("utf-8")) == 128

    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "protected.pdf"
    with pytest.raises(PDFError):
        protect_pdf(str(input_path), str(output_path), password)
    assert not output_path.exists()


def test_protect_pdf_raises_pdferror_for_non_pdf_file(tmp_path):
    input_path = tmp_path / "not_a_pdf.pdf"
    input_path.write_bytes(b"this is definitely not a PDF file, just plain text bytes")

    output_path = tmp_path / "protected.pdf"
    with pytest.raises(PDFError) as exc_info:
        protect_pdf(str(input_path), str(output_path), "somepassword")
    assert str(input_path) not in str(exc_info.value)
    assert not output_path.exists()


def test_unlock_pdf_raises_pdferror_for_non_pdf_file(tmp_path):
    # Finding 3: a non-PDF (or unrecoverably-damaged PDF) submitted to Unlock
    # must raise a clean PDFError, not let a raw pikepdf.PdfError propagate
    # as an unhandled 500 "Internal Server Error".
    input_path = tmp_path / "not_a_pdf.pdf"
    input_path.write_bytes(b"this is definitely not a PDF file, just plain text bytes")

    output_path = tmp_path / "unlocked.pdf"
    with pytest.raises(PDFError) as exc_info:
        unlock_pdf(str(input_path), str(output_path), "anypassword")
    assert str(input_path) not in str(exc_info.value)
    assert not output_path.exists()


def test_unlock_pdf_refuses_damaged_and_encrypted_file_with_correct_password(tmp_path):
    # Finding 1 (CRITICAL): when a damaged file is ALSO encrypted, pikepdf's
    # structural recovery can discard the /Encrypt dictionary entirely. Once
    # that happens, pikepdf treats the file as never having been encrypted —
    # is_encrypted becomes False and NO password is checked at all — while the
    # content streams are still raw ciphertext. The old (unfixed) code would
    # silently call pdf.save() here, producing a "successful" but completely
    # blank/corrupted output for BOTH the correct and an incorrect password.
    #
    # Verified empirically (see probe_truncation.py): truncating a 3-page
    # encrypted PDF fixture to 90% of its byte length lands in exactly this
    # zone — pikepdf.open() succeeds (no PasswordError), pdf.is_encrypted is
    # False, and pdf.get_warnings() is non-empty (4 warnings), for BOTH the
    # correct and an incorrect password.
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    encrypted_path = tmp_path / "encrypted.pdf"
    pdf = pikepdf.open(str(input_path))
    pdf.save(str(encrypted_path), encryption=pikepdf.Encryption(user="secret123", owner="secret123", R=6))
    pdf.close()

    data = encrypted_path.read_bytes()
    truncated_path = tmp_path / "truncated.pdf"
    truncated_path.write_bytes(data[: int(len(data) * 0.9)])

    # Confirm the fixture actually reproduces the dangerous recovery scenario
    # before asserting the fix's behavior on top of it.
    probe = pikepdf.open(str(truncated_path), password="secret123")
    try:
        assert probe.is_encrypted is False
        assert len(probe.get_warnings()) > 0
    finally:
        probe.close()

    output_path = tmp_path / "unlocked.pdf"
    with pytest.raises(PDFError) as exc_info:
        unlock_pdf(str(truncated_path), str(output_path), "secret123")
    assert "damaged" in str(exc_info.value).lower()
    assert not output_path.exists()


def test_unlock_pdf_refuses_damaged_and_encrypted_file_with_wrong_password(tmp_path):
    # Same fixture as above, but with a WRONG password — must ALSO be
    # refused (not silently "succeed", which is the core of the bug: the
    # unfixed code cannot distinguish a correct from an incorrect password
    # once recovery has stripped the encryption info).
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    encrypted_path = tmp_path / "encrypted.pdf"
    pdf = pikepdf.open(str(input_path))
    pdf.save(str(encrypted_path), encryption=pikepdf.Encryption(user="secret123", owner="secret123", R=6))
    pdf.close()

    data = encrypted_path.read_bytes()
    truncated_path = tmp_path / "truncated.pdf"
    truncated_path.write_bytes(data[: int(len(data) * 0.9)])

    output_path = tmp_path / "unlocked.pdf"
    with pytest.raises(PDFError) as exc_info:
        unlock_pdf(str(truncated_path), str(output_path), "totally-wrong-password")
    assert "damaged" in str(exc_info.value).lower()
    assert not output_path.exists()


def test_unlock_pdf_passes_through_unencrypted_file_with_password_supplied(tmp_path):
    # Legitimate case: a genuinely unencrypted, healthy file with a password
    # supplied anyway — the spec's explicit "harmless passthrough" scenario.
    # get_warnings() must be empty here, so the Finding 1 fix must not block it.
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "unlocked.pdf"
    unlock_pdf(str(input_path), str(output_path), "some-password-nobody-asked-for")

    assert output_path.exists()
    result = fitz.open(str(output_path))
    assert result.is_encrypted is False
    assert result.page_count == 3
    result.close()
