"""Load seed/dataset.csv (AR invoice header data) into MongoDB.

Schema notes:
- _id is the invoice's natural business key (invoice_id, falling back to
  doc_id for the handful of rows missing invoice_id). Using a stable
  business key as _id makes re-runs idempotent (upsert) and gives a
  future `invoice_items` collection a natural field to reference via
  invoiceId, without needing an embedded/placeholder array today.
- document_create_date and document_create_date.1 are kept as two
  separate fields (documentCreateDate / documentCreateDate1) - they
  differ in ~57% of rows in this dataset, so they are not duplicates.
"""

import argparse
from datetime import datetime

import pandas as pd
from pymongo import ASCENDING, MongoClient, UpdateOne


def parse_yyyymmdd(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.dropna().astype("int64").astype(str), format="%Y%m%d").reindex(series.index)


def to_python_datetime(value):
    if pd.isna(value):
        return None
    return value.to_pydatetime()


def load_dataframe(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    df["clear_date"] = pd.to_datetime(df["clear_date"], errors="coerce")
    df["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    df["document_create_date"] = parse_yyyymmdd(df["document_create_date"])
    df["document_create_date.1"] = parse_yyyymmdd(df["document_create_date.1"])
    df["due_in_date"] = parse_yyyymmdd(df["due_in_date"])
    df["baseline_create_date"] = parse_yyyymmdd(df["baseline_create_date"])

    df["invoice_id"] = df["invoice_id"].astype("Int64")
    df["doc_id"] = df["doc_id"].astype("Int64")
    df["invoiceKey"] = df["invoice_id"].fillna(df["doc_id"])

    return df


def row_to_document(row: pd.Series) -> dict:
    return {
        "_id": str(row["invoiceKey"]),
        "invoiceId": str(row["invoice_id"]) if pd.notna(row["invoice_id"]) else None,
        "docId": str(row["doc_id"]),
        "businessCode": row["business_code"],
        "areaBusiness": None if pd.isna(row["area_business"]) else row["area_business"],
        "customer": {
            "number": row["cust_number"],
            "name": row["name_customer"],
        },
        "currency": row["invoice_currency"],
        "documentType": row["document type"],
        "postingId": None if pd.isna(row["posting_id"]) else int(row["posting_id"]),
        "isOpen": bool(row["isOpen"]),
        "amounts": {
            "totalOpen": float(row["total_open_amount"]),
        },
        "dates": {
            "postingDate": to_python_datetime(row["posting_date"]),
            "documentCreateDate": to_python_datetime(row["document_create_date"]),
            "documentCreateDate1": to_python_datetime(row["document_create_date.1"]),
            "dueInDate": to_python_datetime(row["due_in_date"]),
            "baselineCreateDate": to_python_datetime(row["baseline_create_date"]),
            "clearDate": to_python_datetime(row["clear_date"]),
        },
        "paymentTerms": row["cust_payment_terms"],
        "businessYear": int(row["buisness_year"]),
    }


def ensure_indexes(collection):
    collection.create_index([("customer.number", ASCENDING)])
    collection.create_index([("isOpen", ASCENDING), ("dates.dueInDate", ASCENDING)])
    collection.create_index([("dates.clearDate", ASCENDING)], sparse=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="seed/dataset.csv")
    parser.add_argument("--uri", default="mongodb://localhost:27017")
    parser.add_argument("--db", default="invoices_db")
    parser.add_argument("--collection", default="invoices")
    parser.add_argument("--batch-size", type=int, default=2000)
    args = parser.parse_args()

    df = load_dataframe(args.csv)

    client = MongoClient(args.uri)
    collection = client[args.db][args.collection]
    ensure_indexes(collection)

    start = datetime.now()
    total = 0
    ops = []
    for _, row in df.iterrows():
        doc = row_to_document(row)
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
        if len(ops) >= args.batch_size:
            collection.bulk_write(ops, ordered=False)
            total += len(ops)
            ops = []
    if ops:
        collection.bulk_write(ops, ordered=False)
        total += len(ops)

    print(f"Upserted {total} documents into {args.db}.{args.collection} in {datetime.now() - start}")


if __name__ == "__main__":
    main()
