from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.convert import convert_to_word
from app.core.errors import PDFError
from app.core.pdf_ops import (
    add_watermark,
    compress_pdf,
    extract_pages,
    get_page_count,
    merge_pdfs,
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


class MergeRequest(BaseModel):
    file_ids: list[str]
    filename: str


@router.post("/merge")
def merge(req: MergeRequest):
    input_paths = [str(storage.resolve_file(fid)) for fid in req.file_ids]
    filename = req.filename.strip()
    if not filename:
        raise PDFError("Enter an output filename.")
    if any(sep in filename for sep in ("/", "\\", ":")):
        raise PDFError("Output filename must be a plain file name, not a path.")
    if filename.lower().endswith(".pdf"):
        filename = filename[: -len(".pdf")]
    output_path = storage.output_path_for(filename, "")
    merge_pdfs(input_paths, str(output_path))
    source_names = [Path(p).name for p in input_paths]
    return _output_response([output_path], "Merge PDF", source_names)


class SplitRequest(BaseModel):
    file_id: str
    pages_per_file: int


@router.post("/split")
def split(req: SplitRequest):
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
