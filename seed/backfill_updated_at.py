import argparse
import os

from dotenv import load_dotenv
from pymongo import MongoClient

BACKFILL = [{"$set": {"updatedAt": {"$ifNull": ["$closedAt", "$dates.postingDate"]}}}]


def backfill(collection):
    return collection.update_many({"updatedAt": {"$exists": False}}, BACKFILL).modified_count


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Set updatedAt on invoices that predate the field.")
    parser.add_argument("--uri", default=os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.environ.get("MONGO_DB_NAME", "invoices_db"))
    args = parser.parse_args()

    collection = MongoClient(args.uri)[args.db]["invoices"]
    print(f"Set updatedAt on {backfill(collection)} invoices")


if __name__ == "__main__":
    main()
