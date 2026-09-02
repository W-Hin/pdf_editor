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


def rotate_pages(input_path: str, output_path: str, angle: int, page_numbers: list[int] | None = None) -> None:
    if angle % 90 != 0:
        raise PDFError("Rotation angle must be a multiple of 90 degrees.")
    doc = open_pdf(input_path)
    try:
        targets = page_numbers if page_numbers is not None else list(range(1, doc.page_count + 1))
        for n in targets:
            if n < 1 or n > doc.page_count:
                raise PDFError(f"Page {n} does not exist in this document ({doc.page_count} pages).")
            page = doc[n - 1]
            page.set_rotation((page.rotation + angle) % 360)
        doc.save(output_path)
    finally:
        doc.close()


def add_watermark(
    input_path: str,
    output_path: str,
    text: str,
    opacity: float = 0.3,
    font_size: int = 40,
    rotate: int = 0,
) -> None:
    if not text.strip():
        raise PDFError("Watermark text cannot be empty.")
    if rotate not in (0, 90, 180, 270):
        raise PDFError("Watermark rotation must be 0, 90, 180, or 270 degrees.")
    doc = open_pdf(input_path)
    try:
        for page in doc:
            page.insert_textbox(
                page.rect,
                text,
                fontsize=font_size,
                fontname="helv",
                color=(0.5, 0.5, 0.5),
                fill_opacity=opacity,
                rotate=rotate,
                align=fitz.TEXT_ALIGN_CENTER,
            )
        doc.save(output_path)
    finally:
        doc.close()


def crop_pdf(input_path: str, output_path: str, top: float, right: float, bottom: float, left: float) -> None:
    for name, value in (("top", top), ("right", right), ("bottom", bottom), ("left", left)):
        if not (0 <= value < 0.5):
            raise PDFError(f"Crop '{name}' must be between 0 and 0.5 (got {value}).")
    doc = open_pdf(input_path)
    try:
        for page in doc:
            rect = page.rect
            new_rect = fitz.Rect(
                rect.x0 + left * rect.width,
                rect.y0 + top * rect.height,
                rect.x1 - right * rect.width,
                rect.y1 - bottom * rect.height,
            )
            page.set_cropbox(new_rect)
        doc.save(output_path)
    finally:
        doc.close()


_PAGE_NUMBER_ALIGN = {
    "bottom-left": fitz.TEXT_ALIGN_LEFT,
    "bottom-center": fitz.TEXT_ALIGN_CENTER,
    "bottom-right": fitz.TEXT_ALIGN_RIGHT,
    "top-left": fitz.TEXT_ALIGN_LEFT,
    "top-center": fitz.TEXT_ALIGN_CENTER,
    "top-right": fitz.TEXT_ALIGN_RIGHT,
}

_PAGE_NUMBER_FORMATS = {"number", "number-of-total", "page-x-of-y"}

_PAGE_NUMBER_MARGIN = 36  # points; 0.5in, the conventional print margin
_PAGE_NUMBER_BAND_HEIGHT = 20  # points


def _format_page_number(fmt: str, page_num: int, total: int) -> str:
    if fmt == "number":
        return str(page_num)
    if fmt == "number-of-total":
        return f"{page_num} / {total}"
    return f"Page {page_num} of {total}"


def add_page_numbers(input_path: str, output_path: str, position: str, format: str) -> None:
    if position not in _PAGE_NUMBER_ALIGN:
        raise PDFError(f"Unknown page number position: {position}")
    if format not in _PAGE_NUMBER_FORMATS:
        raise PDFError(f"Unknown page number format: {format}")
    doc = open_pdf(input_path)
    try:
        total = doc.page_count
        for i, page in enumerate(doc, start=1):
            rect = page.rect
            if position.startswith("bottom"):
                band = fitz.Rect(
                    rect.x0 + _PAGE_NUMBER_MARGIN,
                    rect.y1 - _PAGE_NUMBER_MARGIN - _PAGE_NUMBER_BAND_HEIGHT,
                    rect.x1 - _PAGE_NUMBER_MARGIN,
                    rect.y1 - _PAGE_NUMBER_MARGIN,
                )
            else:
                band = fitz.Rect(
                    rect.x0 + _PAGE_NUMBER_MARGIN,
                    rect.y0 + _PAGE_NUMBER_MARGIN,
                    rect.x1 - _PAGE_NUMBER_MARGIN,
                    rect.y0 + _PAGE_NUMBER_MARGIN + _PAGE_NUMBER_BAND_HEIGHT,
                )
            page.insert_textbox(
                band,
                _format_page_number(format, i, total),
                fontsize=10,
                fontname="helv",
                color=(0, 0, 0),
                align=_PAGE_NUMBER_ALIGN[position],
            )
        doc.save(output_path)
    finally:
        doc.close()


def compress_pdf(input_path: str, output_path: str, image_quality: int = 60) -> None:
    if not 1 <= image_quality <= 100:
        raise PDFError("Image quality must be between 1 and 100.")
    doc = open_pdf(input_path)
    try:
        for page in doc:
            for img in page.get_images(full=True):
                xref = img[0]
                pix = None
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.colorspace and pix.colorspace.n >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.alpha:
                        pix = fitz.Pixmap(pix, 0)
                    jpeg_bytes = pix.tobytes("jpeg", jpg_quality=image_quality)
                    page.replace_image(xref, stream=jpeg_bytes)
                except Exception:
                    continue  # skip images that can't be recompressed (e.g. stencil masks)
                finally:
                    pix = None
        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()


def render_page_thumbnail(input_path: str, page_number: int, max_size: int = 100) -> bytes:
    doc = open_pdf(input_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFError(f"Page {page_number} does not exist in this document ({doc.page_count} pages).")
        page = doc[page_number - 1]
        rect = page.rect
        scale = max_size / max(rect.width, rect.height)
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix)
        return pix.tobytes("png")
    finally:
        doc.close()


def render_to_images(
    input_path: str, output_dir: str, dpi: int = 150, image_format: str = "png"
) -> list[str]:
    fmt = image_format.lower()
    if fmt not in ("png", "jpg", "jpeg"):
        raise PDFError("Image format must be png or jpg.")
    doc = open_pdf(input_path)
    try:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(input_path).stem
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        output_paths = []
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix)
            out_path = out_dir / f"{stem}_page{i}.{fmt}"
            pix.save(str(out_path))
            output_paths.append(str(out_path))
        return output_paths
    finally:
        doc.close()
