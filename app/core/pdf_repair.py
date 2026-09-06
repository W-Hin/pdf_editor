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
    try:
        pdf.save(output_path)
    finally:
        pdf.close()


def protect_pdf(input_path: str, output_path: str, password: str) -> None:
    if not password.strip():
        raise PDFError("Enter a password.")
    pdf = pikepdf.open(input_path)
    try:
        pdf.save(output_path, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    finally:
        pdf.close()
