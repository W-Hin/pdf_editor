import math
import re
from pathlib import Path

import fitz

from app.core.errors import PDFError


def open_pdf(path: str) -> fitz.Document:
    p = Path(path)
    if not p.exists():
        raise PDFError(f"File not found: {path}")
    try:
        doc = fitz.open(path)
        # Reading is_encrypted inside the try on purpose: fitz.open() on an image
        # container is lazy, so the first real property access is where a corrupt
        # file's decode failure can actually surface.
        if doc.is_encrypted:
            doc.close()
            raise PDFError(f"'{p.name}' is password-protected. Unlock it before using this tool.")
    except PDFError:
        raise
    except Exception as exc:
        raise PDFError(f"Could not open '{p.name}' — it may not be a valid PDF or image.") from exc
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
        if not (0 <= value < 1):
            raise PDFError(f"Crop '{name}' must be between 0 and 1 (got {value}).")
    if left + right >= 1 or top + bottom >= 1:
        raise PDFError("The crop area must have a positive width and height.")
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
            # page.rect is the *displayed* (rotated) rectangle, but set_cropbox
            # validates against the unrotated mediabox — derotation_matrix maps
            # the former back into the latter (identity when rotation is 0).
            try:
                page.set_cropbox(new_rect * page.derotation_matrix)
            except ValueError as exc:
                raise PDFError(f"Could not apply this crop to '{Path(input_path).name}'.") from exc
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
            try:
                page.insert_textbox(
                    band,
                    _format_page_number(format, i, total),
                    fontsize=10,
                    fontname="helv",
                    color=(0, 0, 0),
                    align=_PAGE_NUMBER_ALIGN[position],
                )
            except ValueError as exc:
                raise PDFError("This page is too small to add a page number to.") from exc
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
        # Page access and rendering are where a lazily-opened image container
        # actually decodes its pixels — and so where a corrupt file blows up.
        try:
            page = doc[page_number - 1]
            rect = page.rect
            scale = max_size / max(rect.width, rect.height)
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix)
        except Exception as exc:
            raise PDFError(f"Could not render a preview of '{Path(input_path).name}'.") from exc
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


def images_to_pdf(image_paths: list[str], output_path: str, fit_mode: str) -> None:
    if fit_mode not in ("fit", "fill"):
        raise PDFError(f"Unknown fit mode: {fit_mode}")
    if not image_paths:
        raise PDFError("Select at least one image.")
    result = fitz.open()
    try:
        for path in image_paths:
            doc = open_pdf(path)
            try:
                # doc[0].rect is the first access that forces a real decode of a
                # lazily-opened image, so a corrupt file surfaces here.
                img_rect = doc[0].rect
            except Exception as exc:
                raise PDFError(f"Could not read image '{Path(path).name}'.") from exc
            finally:
                doc.close()
            img_w, img_h = img_rect.width, img_rect.height
            page_w, page_h = (842, 595) if img_w > img_h else (595, 842)
            page = result.new_page(width=page_w, height=page_h)
            img_aspect = img_w / img_h
            page_aspect = page_w / page_h
            if fit_mode == "fit":
                if img_aspect > page_aspect:
                    target_w, target_h = page_w, page_w / img_aspect
                else:
                    target_h, target_w = page_h, page_h * img_aspect
            else:
                # Fill: the overflowing part of the image is only *visually*
                # clipped at render time — the full-resolution image is still
                # embedded in the PDF, so Fill neither shrinks the file nor
                # removes the cropped-away pixel data.
                if img_aspect > page_aspect:
                    target_h, target_w = page_h, page_h * img_aspect
                else:
                    target_w, target_h = page_w, page_w / img_aspect
            x0 = (page_w - target_w) / 2
            y0 = (page_h - target_h) / 2
            try:
                page.insert_image(fitz.Rect(x0, y0, x0 + target_w, y0 + target_h), filename=path)
            except Exception as exc:
                raise PDFError(f"Could not insert image '{Path(path).name}' into the PDF.") from exc
        result.save(output_path)
    finally:
        result.close()


def redact_pdf(input_path: str, output_path: str, redactions: list[dict]) -> None:
    if not redactions:
        raise PDFError("Select at least one area to redact.")
    doc = open_pdf(input_path)
    try:
        for r in redactions:
            page_num = r["page"]
            if page_num < 1 or page_num > doc.page_count:
                raise PDFError(f"Page {page_num} does not exist in this document ({doc.page_count} pages).")
        for r in redactions:
            for name in ("top", "right", "bottom", "left"):
                value = r[name]
                if not (0 <= value < 1):
                    raise PDFError(f"Redaction '{name}' must be between 0 and 1 (got {value}).")
            if r["left"] + r["right"] >= 1 or r["top"] + r["bottom"] >= 1:
                raise PDFError("Each redaction area must have a positive width and height.")
        pages_with_annots = set()
        for r in redactions:
            page = doc[r["page"] - 1]
            rect = page.rect
            redact_rect = fitz.Rect(
                rect.x0 + r["left"] * rect.width,
                rect.y0 + r["top"] * rect.height,
                rect.x1 - r["right"] * rect.width,
                rect.y1 - r["bottom"] * rect.height,
            )
            # page.rect is the *displayed* (rotated) rectangle the user drew on,
            # but add_redact_annot interprets coordinates in the unrotated
            # mediabox — derotation_matrix maps the former back into the latter
            # (identity when rotation is 0). Same step as crop_pdf/set_cropbox:
            # without it a rotated page's marked text survives untouched while
            # an unrelated region gets destroyed.
            page.add_redact_annot(redact_rect * page.derotation_matrix, fill=(0, 0, 0))
            pages_with_annots.add(r["page"])
        for page_num in pages_with_annots:
            doc[page_num - 1].apply_redactions()
        doc.save(output_path)
    finally:
        doc.close()


def _page_text_spans(page: fitz.Page) -> list[dict]:
    """Raw PyMuPDF span dicts for a page, in document order, whitespace-only
    spans skipped. Coordinates in each span's "bbox"/"origin" are in unrotated
    mediabox space — the space add_redact_annot/insert_text/set_cropbox all
    expect. edit_pdf (Task 3) reuses this exact function so a run_index from
    extract_text_runs always refers to the same span here.
    """
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip():
                    spans.append(span)
    return spans


def extract_text_runs(input_path: str, page_number: int) -> list[dict]:
    doc = open_pdf(input_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFError(f"Page {page_number} does not exist in this document ({doc.page_count} pages).")
        page = doc[page_number - 1]
        rect = page.rect
        runs = []
        for index, span in enumerate(_page_text_spans(page)):
            # span["bbox"] is raw/unrotated; page.rotation_matrix maps it into
            # the *displayed* rect the frontend renders click targets over
            # (finding #2 — the inverse of crop_pdf/redact_pdf's derotation step).
            displayed = fitz.Rect(span["bbox"]) * page.rotation_matrix
            flags = span["flags"]
            runs.append(
                {
                    "index": index,
                    "text": span["text"],
                    "font": span["font"],
                    "size": span["size"],
                    "bold": bool(flags & 16),
                    "italic": bool(flags & 2),
                    "bbox": {
                        "top": (displayed.y0 - rect.y0) / rect.height,
                        "left": (displayed.x0 - rect.x0) / rect.width,
                        "right": (rect.x1 - displayed.x1) / rect.width,
                        "bottom": (rect.y1 - displayed.y1) / rect.height,
                    },
                }
            )
        return runs
    finally:
        doc.close()


_TEXT_EDIT_MIN_SIZE = 6
_TEXT_EDIT_SHRINK_FACTOR = 0.5

_FONT_ALIASES = {
    ("helvetica", False, False): "helv",
    ("helvetica", True, False): "hebo",
    ("helvetica", False, True): "heit",
    ("helvetica", True, True): "hebi",
    ("times", False, False): "tiro",
    ("times", True, False): "tibo",
    ("times", False, True): "tiit",
    ("times", True, True): "tibi",
    ("courier", False, False): "cour",
    ("courier", True, False): "cobo",
    ("courier", False, True): "coit",
    ("courier", True, True): "cobi",
}

_SHAPE_TYPES = {"rectangle", "ellipse", "line", "arrow"}


def _base14_alias(family: str, bold: bool, italic: bool) -> str:
    key = (family.lower(), bool(bold), bool(italic))
    return _FONT_ALIASES.get(key, _FONT_ALIASES[("helvetica", bool(bold), bool(italic))])


def _closest_base14_family(font_name: str) -> str:
    lowered = font_name.lower()
    if "times" in lowered or "serif" in lowered or "georgia" in lowered:
        return "times"
    if "courier" in lowered or "mono" in lowered or "consolas" in lowered:
        return "courier"
    return "helvetica"


_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")


def _extract_embedded_font(doc: fitz.Document, page: fitz.Page, span_font_name: str) -> bytes | None:
    """Real font-file bytes for span_font_name if it's actually embedded on
    this page, else None (base-14 fonts have nothing to extract).

    get_page_fonts() reports a subset-prefixed basefont for subset-embedded
    fonts (e.g. "AAAAAA+Garet-Bold" — six uppercase letters, a "+", then the
    real name), which is how the overwhelming majority of real-world PDFs
    (Word/LaTeX exports) embed fonts. get_text("dict")'s span "font" value
    never carries that prefix, so an exact-match comparison against the raw
    basefont silently misses every subset-embedded font. Strip the prefix
    before comparing (verified empirically via doc.subset_fonts()).
    """
    for f in doc.get_page_fonts(page.number, full=True):
        xref, basefont = f[0], f[3]
        normalized = _SUBSET_PREFIX_RE.sub("", basefont)
        if basefont == span_font_name or normalized == span_font_name:
            try:
                extracted = doc.extract_font(xref)
                buf = extracted[3]
                if buf:
                    return buf
            except Exception:
                pass
            break
    return None


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise PDFError(f"Invalid color: {hex_color}")
    try:
        return (int(value[0:2], 16) / 255, int(value[2:4], 16) / 255, int(value[4:6], 16) / 255)
    except ValueError as exc:
        raise PDFError(f"Invalid color: {hex_color}") from exc


def _validate_stroke(el: dict) -> None:
    if not el["points"]:
        raise PDFError("A hand-drawn stroke must have at least one point.")
    for pt in el["points"]:
        if not (0 <= pt["x"] <= 1) or not (0 <= pt["y"] <= 1):
            raise PDFError("Stroke points must be within the page.")
    _hex_to_rgb(el["color"])  # raises PDFError up front on a malformed hex


def _validate_shape(el: dict) -> None:
    for name in ("x0", "y0", "x1", "y1"):
        value = el[name]
        if not (0 <= value <= 1):
            raise PDFError(f"Shape '{name}' must be between 0 and 1 (got {value}).")
    if el["shape"] in ("rectangle", "ellipse"):
        if el["x0"] == el["x1"] or el["y0"] == el["y1"]:
            raise PDFError("The shape must have a positive width and height.")
    elif el["x0"] == el["x1"] and el["y0"] == el["y1"]:
        raise PDFError("A line or arrow must have two distinct points.")
    _hex_to_rgb(el["color"])  # raises PDFError up front on a malformed hex


def _validate_highlight(el: dict) -> None:
    for name in ("top", "right", "bottom", "left"):
        value = el[name]
        if not (0 <= value < 1):
            raise PDFError(f"Highlight '{name}' must be between 0 and 1 (got {value}).")
    if el["left"] + el["right"] >= 1 or el["top"] + el["bottom"] >= 1:
        raise PDFError("The highlight area must have a positive width and height.")
    _hex_to_rgb(el["color"])  # raises PDFError up front on a malformed hex


def _validate_image_element(el: dict, image_paths: dict[str, str]) -> None:
    if el["file_id"] not in image_paths:
        raise PDFError(f"Image '{el['file_id']}' was not uploaded.")
    if not (0 <= el["x"] <= 1) or not (0 <= el["y"] <= 1):
        raise PDFError("Image position must be within the page.")
    if not (0 < el["width"] <= 1) or not (0 < el["height"] <= 1):
        raise PDFError("Image width and height must be positive fractions of the page.")
    if el["x"] + el["width"] > 1 or el["y"] + el["height"] > 1:
        raise PDFError("The image must fit within the page.")


def _apply_text_edit(doc: fitz.Document, page: fitz.Page, span: dict, replacement_text: str, font_override: dict | None, internal_fontname: str) -> tuple:
    """Adds the redact annotation for this run's original text and returns the
    (origin, text, fontname, size, embedded_buf, color) needed to insert its
    replacement.

    Verified empirically: inserting the replacement text right away (before
    page.apply_redactions() has actually run) does NOT work in this PyMuPDF
    build — the new text overlaps the same rect as the pending redaction
    annotation, and apply_redactions() clips/removes it right along with the
    original, since redaction acts on whatever is in the content stream at
    the moment it runs, not just what was there when the annotation was
    added. The caller must call page.apply_redactions() first and only then
    insert the text this function returns.

    Also verified empirically: page.apply_redactions() wipes the page's font
    resources, so registering an embedded font via page.insert_font() here
    (before apply_redactions runs) is pointless — by the time the deferred
    insert_text() call happens, that font is gone and insert_text() raises
    "need font file or buffer". embedded_buf is therefore returned uncommitted
    so the caller can call page.insert_font() again immediately before the
    matching insert_text(), AFTER apply_redactions() has already run.
    """
    raw_bbox = fitz.Rect(span["bbox"])
    page.add_redact_annot(raw_bbox, fill=(1, 1, 1))

    detected_bold = bool(span["flags"] & 16)
    detected_italic = bool(span["flags"] & 2)

    embedded_buf = None
    if font_override:
        fontname = _base14_alias(font_override["family"], font_override["bold"], font_override["italic"])
        size = font_override["size"]
    else:
        embedded_buf = _extract_embedded_font(doc, page, span["font"])
        if embedded_buf:
            fontname = internal_fontname
        else:
            fontname = _base14_alias(_closest_base14_family(span["font"]), detected_bold, detected_italic)
        size = span["size"]

    # fitz.get_text_length() only understands base-14/built-in font names —
    # it raises ValueError for an internal/embedded fontname like "TE1_0".
    # For the embedded-font branch, measure width with a throwaway fitz.Font
    # built directly from the font buffer instead (verified empirically).
    if embedded_buf is not None:
        measured = fitz.Font(fontbuffer=embedded_buf).text_length(replacement_text, fontsize=size)
    else:
        measured = fitz.get_text_length(replacement_text, fontname=fontname, fontsize=size)

    original_width = raw_bbox.width
    if measured > original_width > 0:
        floor = max(_TEXT_EDIT_MIN_SIZE, size * _TEXT_EDIT_SHRINK_FACTOR)
        size = max(original_width / measured * size, floor)

    # span["color"] is an sRGB integer; sRGB_to_pdf turns it into the (r, g, b)
    # float triple insert_text's color= expects. Keeping the run's own colour
    # means replacement text no longer silently turns black on coloured runs.
    color = fitz.sRGB_to_pdf(span.get("color", 0))

    return (span["origin"], replacement_text, fontname, size, embedded_buf, color)


def _apply_stroke(page: fitz.Page, el: dict) -> None:
    rect = page.rect
    raw_points = [
        fitz.Point(rect.x0 + pt["x"] * rect.width, rect.y0 + pt["y"] * rect.height) * page.derotation_matrix
        for pt in el["points"]
    ]
    if len(raw_points) == 1:
        p = raw_points[0]
        raw_points = [p, fitz.Point(p.x + 0.1, p.y + 0.1)]
    # add_ink_annot requires plain (x, y) float pairs, not fitz.Point objects —
    # verified empirically: passing Points raises "arg must be seq of seq of
    # float pairs" even though every other API used in this file accepts Points.
    tuple_points = [(p.x, p.y) for p in raw_points]
    annot = page.add_ink_annot([tuple_points])
    annot.set_colors(stroke=_hex_to_rgb(el["color"]))
    annot.set_border(width=el["width"])
    annot.update()


def _to_raw_point(page: fitz.Page, fx: float, fy: float) -> fitz.Point:
    rect = page.rect
    displayed = fitz.Point(rect.x0 + fx * rect.width, rect.y0 + fy * rect.height)
    return displayed * page.derotation_matrix


def _draw_arrow(shape, p0: fitz.Point, p1: fitz.Point, color: tuple, width: float) -> None:
    shape.draw_line(p0, p1)
    shape.finish(color=color, width=width)
    angle = math.atan2(p1.y - p0.y, p1.x - p0.x)
    head_len = max(8, width * 3)
    head_angle = math.radians(25)
    h1 = fitz.Point(p1.x - head_len * math.cos(angle - head_angle), p1.y - head_len * math.sin(angle - head_angle))
    h2 = fitz.Point(p1.x - head_len * math.cos(angle + head_angle), p1.y - head_len * math.sin(angle + head_angle))
    shape.draw_polyline([h1, p1, h2, h1])
    shape.finish(color=color, fill=color, width=width, closePath=True)


def _apply_shape(page: fitz.Page, el: dict) -> None:
    p0 = _to_raw_point(page, el["x0"], el["y0"])
    p1 = _to_raw_point(page, el["x1"], el["y1"])
    color = _hex_to_rgb(el["color"])
    width = el["width"]
    shape = page.new_shape()
    if el["shape"] in ("rectangle", "ellipse"):
        raw_rect = fitz.Rect(p0, p1)
        raw_rect.normalize()
        fill = color if el.get("filled") else None
        if el["shape"] == "rectangle":
            shape.draw_rect(raw_rect)
        else:
            shape.draw_oval(raw_rect)
        shape.finish(color=color, width=width, fill=fill)
    elif el["shape"] == "line":
        shape.draw_line(p0, p1)
        shape.finish(color=color, width=width)
    else:
        _draw_arrow(shape, p0, p1, color, width)
    shape.commit()


def _apply_highlight(page: fitz.Page, el: dict) -> None:
    rect = page.rect
    displayed = fitz.Rect(
        rect.x0 + el["left"] * rect.width,
        rect.y0 + el["top"] * rect.height,
        rect.x1 - el["right"] * rect.width,
        rect.y1 - el["bottom"] * rect.height,
    )
    raw = displayed * page.derotation_matrix
    shape = page.new_shape()
    shape.draw_rect(raw)
    shape.finish(fill=_hex_to_rgb(el["color"]), fill_opacity=0.4, color=None)
    shape.commit()


def _apply_image(page: fitz.Page, el: dict, image_path: str) -> None:
    rect = page.rect
    displayed = fitz.Rect(
        rect.x0 + el["x"] * rect.width,
        rect.y0 + el["y"] * rect.height,
        rect.x0 + (el["x"] + el["width"]) * rect.width,
        rect.y0 + (el["y"] + el["height"]) * rect.height,
    )
    raw = displayed * page.derotation_matrix
    try:
        # The rect is derotated back into mediabox space, but the image's own
        # pixels are not — without a compensating rotation the image draws
        # sideways (and letterboxed inside the aspect-swapped raw rect) at
        # 90/270 degrees, and upside-down at 180. Verified empirically across
        # every (page.rotation, rotate) pair: rotate=page.rotation is the one
        # that reproduces the source image upright in DISPLAYED space —
        # (-page.rotation) % 360 lands 180 degrees out.
        page.insert_image(raw, filename=image_path, rotate=page.rotation % 360)
    except Exception as exc:
        raise PDFError(f"Could not insert image '{Path(image_path).name}' into the PDF.") from exc


_NEW_TEXT_FAMILIES = {"helvetica", "times", "courier"}
_NEW_TEXT_ALIGNS = {"left", "center", "right"}


def _validate_new_text(el: dict) -> None:
    if not el["text"].strip():
        raise PDFError("Add some text before running.")
    if not (0 <= el["x"] <= 1) or not (0 <= el["y"] <= 1):
        raise PDFError("Text box position must be within the page.")
    if not (0 < el["width"] <= 1) or not (0 < el["height"] <= 1):
        raise PDFError("Text box width and height must be positive fractions of the page.")
    if el["x"] + el["width"] > 1 or el["y"] + el["height"] > 1:
        raise PDFError("The text box must fit within the page.")
    if el["family"] not in _NEW_TEXT_FAMILIES:
        raise PDFError(f"Unknown font family: {el['family']}")
    if el["align"] not in _NEW_TEXT_ALIGNS:
        raise PDFError(f"Unknown text alignment: {el['align']}")
    _hex_to_rgb(el["color"])  # raises PDFError up front on a malformed hex


def _wrap_text_lines(text: str, fontname: str, fontsize: float, max_width: float) -> list[str]:
    """Greedy word-wrap using the same width-measurement primitive
    (fitz.get_text_length) auto-shrink-to-fit already relies on.
    insert_textbox() (used elsewhere for Watermark/Page Numbers) wraps text
    but doesn't expose per-line boundaries or widths, which _apply_new_text
    needs to draw a correctly-sized underline under each line and to align
    each line independently — verified empirically (see the Add Text design
    spec) that this manual approach produces the expected line breaks.
    """
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if fitz.get_text_length(candidate, fontname=fontname, fontsize=fontsize) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _apply_new_text(page: fitz.Page, el: dict) -> None:
    rect = page.rect
    displayed = fitz.Rect(
        rect.x0 + el["x"] * rect.width,
        rect.y0 + el["y"] * rect.height,
        rect.x0 + (el["x"] + el["width"]) * rect.width,
        rect.y0 + (el["y"] + el["height"]) * rect.height,
    )
    dm = page.derotation_matrix

    fontname = _base14_alias(el["family"], el["bold"], el["italic"])
    size = el["size"]
    color = _hex_to_rgb(el["color"])
    align = el["align"]

    # Layout happens in DISPLAYED space (matching what the user actually drew),
    # not raw/derotated space — on a 90/270-rotated page, raw space swaps width
    # and height, so laying out (and wrapping) against raw.width would measure
    # against the wrong axis entirely. Each point is mapped to raw space only
    # at the moment it's drawn, via `* dm`, with `rotate=` telling insert_text
    # how to orient the glyphs themselves — the same technique _apply_image
    # already uses via its own `rotate=page.rotation % 360` parameter.
    lines = _wrap_text_lines(el["text"], fontname, size, displayed.width)
    line_height = size * 1.2
    y = displayed.y0 + size
    for line in lines:
        # Overflow: stop drawing past the box's bottom edge rather than
        # auto-shrinking — a documented ceiling (the box is user-resizable,
        # so it's recoverable), matching Edit Text's own white-fill limitation.
        if y > displayed.y1:
            break
        width = fitz.get_text_length(line, fontname=fontname, fontsize=size)
        if align == "center":
            x = displayed.x0 + (displayed.width - width) / 2
        elif align == "right":
            x = displayed.x1 - width
        else:
            x = displayed.x0
        page.insert_text(
            fitz.Point(x, y) * dm, line, fontsize=size, fontname=fontname,
            color=color, rotate=page.rotation % 360,
        )
        if el["underline"]:
            underline_y = y + size * 0.15
            page.draw_line(
                fitz.Point(x, underline_y) * dm, fitz.Point(x + width, underline_y) * dm,
                color=color, width=max(0.5, size * 0.05),
            )
        y += line_height


def edit_pdf(input_path: str, output_path: str, elements: list[dict], image_paths: dict[str, str]) -> None:
    if not elements:
        raise PDFError("Add at least one edit before running.")
    doc = open_pdf(input_path)
    try:
        run_cache: dict[int, list[dict]] = {}
        for el in elements:
            page_num = el["page"]
            if page_num < 1 or page_num > doc.page_count:
                raise PDFError(f"Page {page_num} does not exist in this document ({doc.page_count} pages).")
            el_type = el["type"]
            if el_type == "text_edit":
                if page_num not in run_cache:
                    run_cache[page_num] = _page_text_spans(doc[page_num - 1])
                spans = run_cache[page_num]
                if el["run_index"] < 0 or el["run_index"] >= len(spans):
                    raise PDFError(f"Text run {el['run_index']} not found on page {page_num}.")
            elif el_type == "stroke":
                _validate_stroke(el)
            elif el_type == "shape":
                if el["shape"] not in _SHAPE_TYPES:
                    raise PDFError(f"Unknown shape: {el['shape']}")
                _validate_shape(el)
            elif el_type == "highlight":
                _validate_highlight(el)
            elif el_type == "image":
                _validate_image_element(el, image_paths)
            elif el_type == "new_text":
                _validate_new_text(el)
            else:
                raise PDFError(f"Unknown element type: {el_type}")

        text_edits_by_page: dict[int, list[dict]] = {}
        other_elements = []
        for el in elements:
            if el["type"] == "text_edit":
                text_edits_by_page.setdefault(el["page"], []).append(el)
            else:
                other_elements.append(el)

        # Text edits apply first, settling each page's content stream before
        # anything else is layered on top. Replacement text is inserted only
        # after apply_redactions() has run for the page — see _apply_text_edit.
        for page_num, page_edits in text_edits_by_page.items():
            page = doc[page_num - 1]
            spans = run_cache[page_num]
            pending_inserts = []
            for i, el in enumerate(page_edits):
                span = spans[el["run_index"]]
                pending_inserts.append(
                    _apply_text_edit(doc, page, span, el["text"], el.get("font_override"), f"TE{page_num}_{i}")
                )
            page.apply_redactions()
            for origin, text, fontname, size, embedded_buf, color in pending_inserts:
                # apply_redactions() wipes the page's font resources, so an
                # embedded font must be (re-)registered here, after redaction
                # has already run, immediately before the insert_text() call
                # that needs it — registering it earlier is silently undone.
                if embedded_buf is not None:
                    page.insert_font(fontname=fontname, fontbuffer=embedded_buf)
                page.insert_text(origin, text, fontsize=size, fontname=fontname, color=color)

        # Then strokes/shapes/highlights/images, in the order the user created them.
        for el in other_elements:
            page = doc[el["page"] - 1]
            if el["type"] == "stroke":
                _apply_stroke(page, el)
            elif el["type"] == "shape":
                _apply_shape(page, el)
            elif el["type"] == "highlight":
                _apply_highlight(page, el)
            elif el["type"] == "image":
                _apply_image(page, el, image_paths[el["file_id"]])
            elif el["type"] == "new_text":
                _apply_new_text(page, el)

        doc.save(output_path)
    finally:
        doc.close()


_FORM_FIELD_TYPE_NAMES = {"Text": "text", "CheckBox": "checkbox", "ComboBox": "combobox"}


def _page_form_widgets(page: fitz.Page) -> list:
    """Kept-type widgets for a page, in document order — RadioButton, ListBox,
    Signature, and any other type are skipped. fill_form (Task 3) reuses this
    exact function so an index from extract_form_fields always refers to the
    same widget here.
    """
    return [w for w in page.widgets() if w.field_type_string in _FORM_FIELD_TYPE_NAMES]


def extract_form_fields(input_path: str) -> list[dict]:
    doc = open_pdf(input_path)
    try:
        fields = []
        for page_num in range(1, doc.page_count + 1):
            page = doc[page_num - 1]
            rect = page.rect
            for index, w in enumerate(_page_form_widgets(page)):
                # widget.rect is raw/unrotated; page.rotation_matrix maps it into
                # the *displayed* rect the frontend positions form controls over
                # (same convention and same mapping extract_text_runs uses for
                # span["bbox"] — verified empirically for widgets this session).
                displayed = fitz.Rect(w.rect) * page.rotation_matrix
                field_type = _FORM_FIELD_TYPE_NAMES[w.field_type_string]
                if field_type == "checkbox":
                    value = w.field_value not in (None, "", "Off")
                else:
                    value = w.field_value or ""
                fields.append(
                    {
                        "page": page_num,
                        "index": index,
                        "label": w.field_label or w.field_name,
                        "type": field_type,
                        "rect": {
                            "top": (displayed.y0 - rect.y0) / rect.height,
                            "left": (displayed.x0 - rect.x0) / rect.width,
                            "right": (rect.x1 - displayed.x1) / rect.width,
                            "bottom": (rect.y1 - displayed.y1) / rect.height,
                        },
                        "value": value,
                        "choices": list(w.choice_values) if field_type == "combobox" and w.choice_values else None,
                    }
                )
        return fields
    finally:
        doc.close()


def fill_form(input_path: str, output_path: str, values: list[dict]) -> None:
    if not values:
        raise PDFError("Fill in at least one field before running.")
    doc = open_pdf(input_path)
    try:
        for v in values:
            page_num = v["page"]
            if page_num < 1 or page_num > doc.page_count:
                raise PDFError(f"Page {page_num} does not exist in this document ({doc.page_count} pages).")
            widgets = _page_form_widgets(doc[page_num - 1])
            if v["index"] < 0 or v["index"] >= len(widgets):
                raise PDFError(f"Field {v['index']} not found on page {page_num}.")

        for v in values:
            page = doc[v["page"] - 1]
            widget = _page_form_widgets(page)[v["index"]]
            widget.field_value = v["value"]
            if v["value"] == "" and widget.field_type_string in ("Text", "ComboBox"):
                # PyMuPDF's widget writer skips falsy values, leaving /V (and the
                # appearance stream bake() uses) at the old value - clear /V
                # explicitly so update() regenerates an empty appearance.
                doc.xref_set_key(widget.xref, "V", "()")
            widget.update()

        doc.bake(annots=False, widgets=True)
        doc.save(output_path)
    finally:
        doc.close()
