import base64

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.compare_pdf import diff_page_text, diff_page_visual, extract_page_texts, render_page_image
from app.core.errors import PDFError
from app.core.pdf_ops import get_page_count
from web.backend import storage

router = APIRouter()


class CompareRequest(BaseModel):
    file_id_a: str
    file_id_b: str


@router.post("/compare")
def compare_route(req: CompareRequest):
    path_a = str(storage.resolve_file(req.file_id_a))
    path_b = str(storage.resolve_file(req.file_id_b))
    texts_a = extract_page_texts(path_a)
    texts_b = extract_page_texts(path_b)
    page_count_a = len(texts_a)
    page_count_b = len(texts_b)
    total_pages = max(page_count_a, page_count_b)

    pages = []
    for i in range(total_pages):
        has_a = i < page_count_a
        has_b = i < page_count_b
        if has_a and has_b:
            pages.append({"text_diff": diff_page_text(texts_a[i], texts_b[i]), "has_counterpart": True})
        else:
            pages.append({"text_diff": [], "has_counterpart": False})

    return {"page_count_a": page_count_a, "page_count_b": page_count_b, "pages": pages}


@router.get("/compare/{file_id_a}/{file_id_b}/{page_num}/visual")
def compare_visual_route(file_id_a: str, file_id_b: str, page_num: int, max_size: int = 1800):
    path_a = str(storage.resolve_file(file_id_a))
    path_b = str(storage.resolve_file(file_id_b))

    for path in (path_a, path_b):
        page_count = get_page_count(path)
        if page_num < 1 or page_num > page_count:
            raise PDFError(f"Page {page_num} does not exist in this document ({page_count} pages).")

    image_a = render_page_image(path_a, page_num, max_size)
    image_b = render_page_image(path_b, page_num, max_size)
    boxes = diff_page_visual(path_a, path_b, page_num, max_size)
    return {
        "image_a": f"data:image/png;base64,{base64.b64encode(image_a).decode('ascii')}",
        "image_b": f"data:image/png;base64,{base64.b64encode(image_b).decode('ascii')}",
        "boxes": boxes,
    }
