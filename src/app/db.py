from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.config import MONGO_DB_NAME, MONGO_URI

_client = MongoClient(MONGO_URI)
_db: Database = _client[MONGO_DB_NAME]


def get_collection(name: str) -> Collection:
    return _db[name]


# Injected rather than called inline so tests can override it without a live Mongo.
def products_collection() -> Collection:
    return get_collection("products")


def get_database() -> Database:
    return _db
