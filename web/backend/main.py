from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.errors import PDFError
from web.backend.routes import files, history, tools

app = FastAPI(title="PDF Editor")


@app.exception_handler(PDFError)
async def pdf_error_handler(request, exc: PDFError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


app.include_router(files.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(tools.router, prefix="/api")

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
