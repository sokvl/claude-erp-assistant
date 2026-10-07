import os

from dotenv import load_dotenv

from app.vault import secret

load_dotenv()

MONGO_URI = secret("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "invoices_db")
