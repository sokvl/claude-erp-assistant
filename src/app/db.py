from pymongo import MongoClient
from pymongo.database import Database

from app.config import MONGO_DB_NAME, MONGO_URI

_client = MongoClient(MONGO_URI)
_db: Database = _client[MONGO_DB_NAME]


def get_database() -> Database:
    return _db
