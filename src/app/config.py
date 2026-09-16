import logging
import os

from dotenv import load_dotenv

load_dotenv()

MIN_API_KEY_LENGTH = 32

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "invoices_db")
API_KEY = os.environ["API_KEY"]

if len(API_KEY) < MIN_API_KEY_LENGTH:
    logging.getLogger(__name__).warning(
        "API_KEY is %d characters; use at least %d random characters outside "
        "local development (python -c 'import secrets; print(secrets.token_urlsafe(32))')",
        len(API_KEY),
        MIN_API_KEY_LENGTH,
    )
