from fastapi import FastAPI

from app.routers import invoices, products

app = FastAPI()
app.include_router(products.router)
app.include_router(invoices.router)
