from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from mandate.db import engine

app = FastAPI(title="MANDATE AI Control Layer")


@app.get("/health")
async def health() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception as exc:  # noqa: BLE001 - health must report, not raise
        db = f"error: {type(exc).__name__}"
    status = 200 if db == "ok" else 503
    return JSONResponse({"status": "ok" if status == 200 else "degraded", "db": db}, status)
