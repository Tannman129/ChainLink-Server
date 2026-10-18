"""Local, read-only WebUI; API routes remain independent of this shell."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
router = APIRouter()
assets = StaticFiles(directory=STATIC_DIRECTORY)


@router.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(
        STATIC_DIRECTORY / "index.html",
        headers={
            "Cache-Control": "no-cache",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
        },
    )
