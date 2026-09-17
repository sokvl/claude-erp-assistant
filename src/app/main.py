import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from app.routers import chat, invoices, products

STATIC_DIR = Path(__file__).parent / "static"
CHAT_PAGE = STATIC_DIR / "chat.html"

logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(products.router)
app.include_router(invoices.router)
app.include_router(chat.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def chat_page() -> FileResponse:
    return FileResponse(CHAT_PAGE)


@app.exception_handler(PyMongoError)
def handle_database_error(request: Request, exc: PyMongoError) -> JSONResponse:
    logger.exception("database error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
