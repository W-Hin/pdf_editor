import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.core.errors import PDFError
from web.backend.routes import compare, files, history, tools, version

app = FastAPI(title="PDF Editor")


@app.exception_handler(PDFError)
async def pdf_error_handler(request, exc: PDFError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(FileNotFoundError)
async def missing_file_handler(request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": "File not found — please re-upload."})


app.include_router(compare.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(version.router, prefix="/api")

if hasattr(sys, "_MEIPASS"):
    # Running from a PyInstaller bundle (onedir or onefile) — data files
    # added via --add-data land under sys._MEIPASS, not next to this file.
    _base_dir = Path(sys._MEIPASS)
else:
    _base_dir = Path(__file__).resolve().parent.parent
_frontend_dist = _base_dir / "frontend" / "dist"


def mount_frontend(fastapi_app: FastAPI, dist_dir: Path) -> None:
    """Serves the built React frontend (a no-op if it hasn't been built).

    index.html is sent with `Cache-Control: no-cache` (the browser must
    revalidate it on every load). Its script/style files have content-hashed
    names, so they can be cached freely - but without this header a browser
    keeps an old index.html for days (it heuristically caches a page with no
    caching headers), and after an upgrade keeps showing the OLD app - the
    old tool list, missing new tools - against the NEW server.
    """
    if not dist_dir.exists():
        return
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    fastapi_app.mount(
        "/assets", StaticFiles(directory=str(dist_dir / "assets")), name="frontend-assets"
    )

    @fastapi_app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(str(dist_dir / "index.html"), headers={"Cache-Control": "no-cache"})


mount_frontend(app, _frontend_dist)
