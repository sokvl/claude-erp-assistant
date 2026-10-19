from collections.abc import Callable
from typing import Any

from pymongo import MongoClient
from pymongo.client_session import ClientSession
from pymongo.database import Database

from app.config import MONGO_DB_NAME, MONGO_URI

TransactionRunner = Callable[[Callable[[ClientSession | None], Any]], Any]

_client = MongoClient(MONGO_URI)
_db: Database = _client[MONGO_DB_NAME]


def build_transaction_runner(client: MongoClient) -> TransactionRunner:
    def run(callback: Callable[[ClientSession | None], Any]) -> Any:
        with client.start_session() as session:
            return session.with_transaction(callback)

    return run


_run_in_transaction = build_transaction_runner(_client)


def get_database() -> Database:
    return _db


def get_transaction_runner() -> TransactionRunner:
    return _run_in_transaction
