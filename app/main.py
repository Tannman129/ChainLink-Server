from fastapi import FastAPI

from app.api.courses import router

app = FastAPI(
    title="ChainLink Server",
    version="0.1.0",
    description="Optional LAN-only course catalog. Write endpoints are unauthenticated.",
)
app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    """Process liveness; does not require a database connection."""
    return {"status": "ok", "version": "0.1.0"}
