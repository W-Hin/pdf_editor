from pathlib import Path

import fitz

from app.core.errors import PDFError


def open_pdf(path: str) -> fitz.Document:
    p = Path(path)
    if not p.exists():
        raise PDFError(f"File not found: {path}")
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PDFError(f"Could not open '{p.name}' — it may not be a valid PDF.") from exc
    if doc.is_encrypted:
        doc.close()
        raise PDFError(f"'{p.name}' is password-protected. Unlock it before using this tool.")
    return doc


def get_page_count(path: str) -> int:
    doc = open_pdf(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def merge_pdfs(input_paths: list[str], output_path: str) -> None:
    if len(input_paths) < 2:
        raise PDFError("Select at least two PDF files to merge.")
    result = fitz.open()
    try:
        for path in input_paths:
            doc = open_pdf(path)
            try:
                result.insert_pdf(doc)
            finally:
                doc.close()
        result.save(output_path)
    finally:
        result.close()


def extract_pages(input_path: str, page_numbers: list[int], output_path: str) -> None:
    """page_numbers are 1-indexed, in the desired output order. Duplicates allowed."""
    if not page_numbers:
        raise PDFError("No pages selected.")
    doc = open_pdf(input_path)
    try:
        for n in page_numbers:
            if n < 1 or n > doc.page_count:
                raise PDFError(f"Page {n} does not exist in this document ({doc.page_count} pages).")
        result = fitz.open()
        try:
            for n in page_numbers:
                result.insert_pdf(doc, from_page=n - 1, to_page=n - 1)
            result.save(output_path)
        finally:
            result.close()
    finally:
        doc.close()


def remove_pages(input_path: str, page_numbers: list[int], output_path: str) -> None:
    total = get_page_count(input_path)
    to_remove = set(page_numbers)
    keep = [n for n in range(1, total + 1) if n not in to_remove]
    if not keep:
        raise PDFError("Cannot remove all pages from the document.")
    extract_pages(input_path, keep, output_path)


def reorder_pages(input_path: str, new_order: list[int], output_path: str) -> None:
    total = get_page_count(input_path)
    if sorted(new_order) != list(range(1, total + 1)):
        raise PDFError("New order must include every page exactly once.")
    extract_pages(input_path, new_order, output_path)


def split_pdf(input_path: str, output_dir: str, ranges: list[tuple[int, int]]) -> list[str]:
    total = get_page_count(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(input_path).stem
    output_paths = []
    for i, (start, end) in enumerate(ranges, start=1):
        if start < 1 or end > total or start > end:
            raise PDFError(f"Invalid page range {start}-{end} for a {total}-page document.")
        pages = list(range(start, end + 1))
        out_path = out_dir / f"{stem}_part{i}.pdf"
        extract_pages(input_path, pages, str(out_path))
        output_paths.append(str(out_path))
    return output_paths
