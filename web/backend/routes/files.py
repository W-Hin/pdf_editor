from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.core.errors import PDFError
from app.core.pdf_ops import get_page_count, render_page_thumbnail
from web.backend import storage

router = APIRouter()


@router.post("/files")
async def upload_file(file: UploadFile):
    content = await file.read()
    record = storage.save_upload(file.filename, content)
    try:
        page_count = get_page_count(record["path"])
    except PDFError:
        try:
            storage.resolve_file(record["id"]).unlink(missing_ok=True)
        except (OSError, PermissionError):
            pass  # On Windows, file might still be locked
        raise
    return {"id": record["id"], "filename": record["filename"], "page_count": page_count}


@router.get("/files/{file_id}/pages/{page_number}/thumbnail")
def get_thumbnail(file_id: str, page_number: int):
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    thumb_bytes = render_page_thumbnail(str(path), page_number, max_size=220)
    return Response(content=thumb_bytes, media_type="image/png")


@router.get("/files/{file_id}/download")
def download_file(file_id: str):
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), filename=path.name)
