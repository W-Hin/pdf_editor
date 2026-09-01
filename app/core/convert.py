from pathlib import Path

from pdf2docx import Converter

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf


def convert_to_word(input_path: str, output_path: str) -> None:
    doc = open_pdf(input_path)  # validates existence, format, and not-encrypted
    doc.close()
    try:
        converter = Converter(input_path)
        try:
            converter.convert(output_path)
        finally:
            converter.close()
    except Exception as exc:
        raise PDFError(f"Could not convert '{Path(input_path).name}' to Word.") from exc
