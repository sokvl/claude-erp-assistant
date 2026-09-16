import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.routers import invoices, products

logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(products.router)
app.include_router(invoices.router)


@app.exception_handler(PyMongoError)
def handle_database_error(request: Request, exc: PyMongoError) -> JSONResponse:
    logger.exception("database error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
