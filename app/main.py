from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.courses import router
from app.api.rounds import router as rounds_router
from app.api.statistics import router as statistics_router
from app.auth import router as auth_router
from app.web import assets
from app.web import router as web_router

app = FastAPI(
    title="ChainLink Server",
    version="0.1.0",
    description="Self-hosted course catalog. Course writes require an administrator session and CSRF token.",
)
app.include_router(router)
app.include_router(auth_router)
app.include_router(rounds_router)
app.include_router(statistics_router)
app.include_router(web_router)
app.mount("/static", assets, name="static")


@app.get("/health", tags=["health"])
def health():
    """Process liveness; does not require a database connection."""
    return {"status": "ok", "version": "0.1.0"}


@app.middleware("http")
async def authentication_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/v1/auth/", "/v1/rounds", "/v1/statistics")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Cookie"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Validation errors must not echo submitted credentials into responses.
    if request.url.path.startswith("/v1/auth/"):
        return JSONResponse(
            status_code=422, content={"detail": "Invalid authentication request."}
        )
    return await request_validation_exception_handler(request, error)
