import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pymongo.errors import PyMongoError

from app.routers import chat, invoices, products

CHAT_PAGE = Path(__file__).parent / "static" / "chat.html"

logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(products.router)
app.include_router(invoices.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
def chat_page() -> FileResponse:
    return FileResponse(CHAT_PAGE)


@app.exception_handler(PyMongoError)
def handle_database_error(request: Request, exc: PyMongoError) -> JSONResponse:
    logger.exception("database error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
