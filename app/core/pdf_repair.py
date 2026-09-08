import pikepdf

from app.core.errors import PDFError


def repair_pdf(input_path: str, output_path: str) -> dict:
    try:
        pdf = pikepdf.open(input_path)
    except pikepdf.PdfError as exc:
        raise PDFError("This file is too damaged to be repaired.") from exc
    try:
        page_count = len(pdf.pages)
        warnings_count = len(pdf.get_warnings())
        pdf.save(output_path)
    finally:
        pdf.close()
    return {"page_count": page_count, "warnings_count": warnings_count}


def unlock_pdf(input_path: str, output_path: str, password: str) -> None:
    try:
        pdf = pikepdf.open(input_path, password=password)
    except pikepdf.PasswordError as exc:
        raise PDFError("Incorrect password.") from exc
    except pikepdf.PdfError as exc:
        raise PDFError("Could not open this file — it may not be a valid PDF.") from exc
    try:
        if pdf.get_warnings():
            # qpdf's structural recovery ran on this file. If the file was also
            # encrypted, recovery can discard the /Encrypt dictionary entirely —
            # at that point pikepdf treats it as never having been encrypted, no
            # password gets checked, and the (still-ciphertext) content streams
            # would be copied straight through into a blank/corrupted "success".
            # Refuse rather than silently producing that destroyed output.
            raise PDFError(
                "This file is too damaged to unlock safely — recovering its structure would "
                "discard the encryption information needed to verify your password, and could "
                "silently produce a blank or corrupted result. Try Repair first, or use a less "
                "damaged copy of this file."
            )
        pdf.save(output_path)
    finally:
        pdf.close()


def protect_pdf(input_path: str, output_path: str, password: str) -> None:
    if not password.strip():
        raise PDFError("Enter a password.")
    # pikepdf/qpdf silently mishandles user/owner passwords over 127 UTF-8
    # bytes: the file saves as "successfully" encrypted, but the exact
    # password the user typed can never open it again (not even a truncated
    # version of it) — a permanently unopenable file once the original is
    # discarded. Reject before that can happen.
    if len(password.encode("utf-8")) > 127:
        raise PDFError("Password is too long — please use 127 bytes or fewer (most passwords are well under this).")
    try:
        pdf = pikepdf.open(input_path)
    except pikepdf.PdfError as exc:
        raise PDFError("Could not open this file — it may not be a valid PDF.") from exc
    try:
        pdf.save(output_path, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    finally:
        pdf.close()
