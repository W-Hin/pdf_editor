from pathlib import Path
from typing import Annotated, Literal, Union

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.convert import convert_to_word
from app.core.errors import PDFError
from app.core.pdf_ops import (
    add_page_numbers,
    add_watermark,
    compress_pdf,
    crop_pdf,
    edit_pdf,
    extract_pages,
    fill_form,
    get_page_count,
    images_to_pdf,
    merge_pdfs,
    redact_pdf,
    remove_pages,
    render_to_images,
    reorder_pages,
    rotate_pages,
    split_pdf,
)
from web.backend import storage

router = APIRouter(prefix="/tools")


def _output_response(paths: list[Path], tool: str, source_filenames: list[str]) -> dict:
    outputs = []
    for path in paths:
        record = storage.record_output(path, tool, source_filenames)
        outputs.append(
            {
                "id": record["id"],
                "filename": record["filename"],
                "download_url": f"/api/files/{record['id']}/download",
            }
        )
    return {"outputs": outputs}


def _sanitize_output_filename(filename: str) -> str:
    """Validate a user-supplied output name and strip a redundant .pdf suffix."""
    filename = filename.strip()
    if not filename:
        raise PDFError("Enter an output filename.")
    if any(sep in filename for sep in ("/", "\\", ":")):
        raise PDFError("Output filename must be a plain file name, not a path.")
    if filename.lower().endswith(".pdf"):
        filename = filename[: -len(".pdf")]
    return filename


class MergeRequest(BaseModel):
    file_ids: list[str]
    filename: str


@router.post("/merge")
def merge(req: MergeRequest):
    input_paths = [str(storage.resolve_file(fid)) for fid in req.file_ids]
    filename = _sanitize_output_filename(req.filename)
    output_path = storage.output_path_for(filename, "")
    merge_pdfs(input_paths, str(output_path))
    source_names = [Path(p).name for p in input_paths]
    return _output_response([output_path], "Merge PDF", source_names)


class SplitRequest(BaseModel):
    file_id: str
    pages_per_file: int


@router.post("/split")
def split(req: SplitRequest):
    if req.pages_per_file < 1:
        raise PDFError("Pages per file must be at least 1.")
    input_path = str(storage.resolve_file(req.file_id))
    total = get_page_count(input_path)
    step = req.pages_per_file
    ranges = [(start, min(start + step - 1, total)) for start in range(1, total + 1, step)]
    stem = Path(input_path).stem
    out_dir = storage.output_dir_for(stem, "_split")
    result_paths = split_pdf(input_path, str(out_dir), ranges)
    return _output_response([Path(p) for p in result_paths], "Split PDF", [Path(input_path).name])


class RemovePagesRequest(BaseModel):
    file_id: str
    pages: list[int]


@router.post("/remove-pages")
def remove_pages_route(req: RemovePagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    if not req.pages:
        raise PDFError("Select at least one page to remove.")
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_removed")
    remove_pages(input_path, req.pages, str(output_path))
    return _output_response([output_path], "Remove pages", [Path(input_path).name])


class ExtractPagesRequest(BaseModel):
    file_id: str
    pages: list[int]


@router.post("/extract-pages")
def extract_pages_route(req: ExtractPagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    if not req.pages:
        raise PDFError("Select at least one page to extract.")
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_extracted")
    extract_pages(input_path, req.pages, str(output_path))
    return _output_response([output_path], "Extract pages", [Path(input_path).name])


class ReorderPagesRequest(BaseModel):
    file_id: str
    order: list[int]


@router.post("/reorder-pages")
def reorder_pages_route(req: ReorderPagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_reordered")
    reorder_pages(input_path, req.order, str(output_path))
    return _output_response([output_path], "Reorder pages", [Path(input_path).name])


class RotateRequest(BaseModel):
    file_id: str
    angle: int


@router.post("/rotate")
def rotate(req: RotateRequest):
    if req.angle % 90 != 0:
        raise PDFError("Angle must be a multiple of 90 degrees.")
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_rotated")
    rotate_pages(input_path, str(output_path), req.angle)
    return _output_response([output_path], "Rotate PDF", [Path(input_path).name])


class WatermarkRequest(BaseModel):
    file_id: str
    text: str
    opacity: float = 0.3


@router.post("/watermark")
def watermark(req: WatermarkRequest):
    if not req.text.strip():
        raise PDFError("Watermark text cannot be empty.")
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_watermarked")
    add_watermark(input_path, str(output_path), req.text, opacity=req.opacity)
    return _output_response([output_path], "Add watermark", [Path(input_path).name])


class CropRequest(BaseModel):
    file_id: str
    top: float
    right: float
    bottom: float
    left: float


@router.post("/crop")
def crop(req: CropRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_cropped")
    crop_pdf(input_path, str(output_path), top=req.top, right=req.right, bottom=req.bottom, left=req.left)
    return _output_response([output_path], "Crop PDF", [Path(input_path).name])


class AddPageNumbersRequest(BaseModel):
    file_id: str
    position: str
    format: str


@router.post("/add-page-numbers")
def add_page_numbers_route(req: AddPageNumbersRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_numbered")
    add_page_numbers(input_path, str(output_path), position=req.position, format=req.format)
    return _output_response([output_path], "Add page numbers", [Path(input_path).name])


class RedactionBox(BaseModel):
    page: int
    top: float
    right: float
    bottom: float
    left: float


class RedactRequest(BaseModel):
    file_id: str
    redactions: list[RedactionBox]


@router.post("/redact")
def redact(req: RedactRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_redacted")
    redactions = [r.model_dump() for r in req.redactions]
    redact_pdf(input_path, str(output_path), redactions)
    return _output_response([output_path], "Redact PDF", [Path(input_path).name])


class CompressRequest(BaseModel):
    file_id: str
    image_quality: int = 60


@router.post("/compress")
def compress(req: CompressRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_compressed")
    compress_pdf(input_path, str(output_path), image_quality=req.image_quality)
    return _output_response([output_path], "Compress PDF", [Path(input_path).name])


class ToImagesRequest(BaseModel):
    file_id: str
    image_format: str = "png"


@router.post("/to-images")
def to_images(req: ToImagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    out_dir = storage.output_dir_for(stem, "_images")
    result_paths = render_to_images(input_path, str(out_dir), image_format=req.image_format)
    return _output_response([Path(p) for p in result_paths], "PDF to Image", [Path(input_path).name])


class ToWordRequest(BaseModel):
    file_id: str


@router.post("/to-word")
def to_word(req: ToWordRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "", ".docx")
    convert_to_word(input_path, str(output_path))
    return _output_response([output_path], "PDF to Word", [Path(input_path).name])


class ImagesToPdfRequest(BaseModel):
    file_ids: list[str]
    filename: str
    fit_mode: str


@router.post("/images-to-pdf")
def images_to_pdf_route(req: ImagesToPdfRequest):
    input_paths = [str(storage.resolve_file(fid)) for fid in req.file_ids]
    filename = _sanitize_output_filename(req.filename)
    output_path = storage.output_path_for(filename, "")
    images_to_pdf(input_paths, str(output_path), fit_mode=req.fit_mode)
    source_names = [Path(p).name for p in input_paths]
    return _output_response([output_path], "Images to PDF", source_names)


class FontOverride(BaseModel):
    family: str
    bold: bool
    italic: bool
    # A blanked number input arrives as 0 from the frontend; insert_text() accepts
    # fontsize=0 silently, which erases the original run and renders the
    # replacement invisibly. Reject it at the model boundary instead.
    size: float = Field(gt=0)


class TextEditElement(BaseModel):
    type: Literal["text_edit"]
    page: int
    run_index: int
    text: str
    font_override: FontOverride | None = None


class StrokePoint(BaseModel):
    x: float
    y: float


class StrokeElement(BaseModel):
    type: Literal["stroke"]
    page: int
    points: list[StrokePoint]
    color: str
    width: float


class ShapeElement(BaseModel):
    type: Literal["shape"]
    page: int
    shape: str
    x0: float
    y0: float
    x1: float
    y1: float
    color: str
    width: float
    filled: bool = False


class HighlightElement(BaseModel):
    type: Literal["highlight"]
    page: int
    top: float
    right: float
    bottom: float
    left: float
    color: str


class ImageElement(BaseModel):
    type: Literal["image"]
    page: int
    file_id: str
    x: float
    y: float
    width: float
    height: float


class NewTextElement(BaseModel):
    type: Literal["new_text"]
    page: int
    x: float
    y: float
    width: float
    height: float
    text: str
    family: str
    bold: bool
    italic: bool
    underline: bool
    # A blanked number input arrives as 0 from the frontend; insert_text()
    # accepts fontsize=0 silently, rendering the text invisibly. Reject it
    # here, matching FontOverride.size's identical guard above.
    size: float = Field(gt=0)
    color: str
    align: str


EditElement = Annotated[
    Union[TextEditElement, StrokeElement, ShapeElement, HighlightElement, ImageElement, NewTextElement],
    Field(discriminator="type"),
]


class EditPdfRequest(BaseModel):
    file_id: str
    elements: list[EditElement]


@router.post("/edit-pdf")
def edit_pdf_route(req: EditPdfRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_edited")
    image_file_ids = {el.file_id for el in req.elements if el.type == "image"}
    image_paths = {}
    for fid in image_file_ids:
        try:
            image_paths[fid] = str(storage.resolve_file(fid))
        except FileNotFoundError:
            pass  # left out of image_paths; edit_pdf raises a PDFError (422) for it
    elements = [el.model_dump() for el in req.elements]
    edit_pdf(input_path, str(output_path), elements, image_paths)
    return _output_response([output_path], "Edit PDF", [Path(input_path).name])


class FormFieldValue(BaseModel):
    page: int
    index: int
    value: str | bool


class FillFormRequest(BaseModel):
    file_id: str
    values: list[FormFieldValue]


@router.post("/fill-form")
def fill_form_route(req: FillFormRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_filled")
    values = [v.model_dump() for v in req.values]
    fill_form(input_path, str(output_path), values)
    return _output_response([output_path], "Fill PDF Form", [Path(input_path).name])
