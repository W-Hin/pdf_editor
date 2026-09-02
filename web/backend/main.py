import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.core.errors import PDFError
from web.backend.routes import files, history, tools, version

app = FastAPI(title="PDF Editor")


@app.exception_handler(PDFError)
async def pdf_error_handler(request, exc: PDFError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(FileNotFoundError)
async def missing_file_handler(request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": "File not found — please re-upload."})


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
if _frontend_dist.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend-assets"
    )

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(str(_frontend_dist / "index.html"))
