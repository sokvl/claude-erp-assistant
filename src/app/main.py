import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo.errors import PyMongoError

from app.routers import audit, auth, charts, chat, invoices, pending_actions, products

STATIC_DIR = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(invoices.router)
app.include_router(chat.router)
app.include_router(charts.router)
app.include_router(pending_actions.router)
app.include_router(audit.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def chat_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.exception_handler(PyMongoError)
def handle_database_error(request: Request, exc: PyMongoError) -> JSONResponse:
    logger.exception("database error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
