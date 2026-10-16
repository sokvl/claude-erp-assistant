import argparse
import json
import os
import time
from pathlib import Path

from pymongo import MongoClient, WriteConcern
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern

DB_PREFIX = "cap_lab_"
COLLECTION = "orders"


def write(args):
    client = MongoClient(args.uri, serverSelectionTimeoutMS=args.timeout_ms, retryWrites=False)
    concern = WriteConcern(w=int(args.w) if args.w.isdigit() else args.w, wtimeout=args.timeout_ms)
    orders = client[DB_PREFIX + args.run].get_collection(COLLECTION, write_concern=concern)
    started = time.monotonic()
    log, seq = [], 0
    while (elapsed := time.monotonic() - started) < args.seconds:
        t0 = time.monotonic()
        try:
            orders.insert_one({"_id": seq, "at": elapsed})
            outcome = "acked"
        except PyMongoError as exc:
            outcome = type(exc).__name__
        log.append({"seq": seq, "at": round(elapsed, 3), "ms": round((time.monotonic() - t0) * 1000), "outcome": outcome})
        seq += 1
        time.sleep(args.interval)
    Path(args.out).write_text(json.dumps({"run": args.run, "w": args.w, "log": log}))
    acked = sum(entry["outcome"] == "acked" for entry in log)
    print(f"wrote {len(log)} orders, {acked} acknowledged, log in {args.out}")


def check(args):
    run = json.loads(Path(args.log).read_text())
    client = MongoClient(args.uri)
    db_name = DB_PREFIX + run["run"]
    orders = client[db_name].get_collection(COLLECTION, read_concern=ReadConcern("majority"))
    stored = {document["_id"] for document in orders.find({}, {"_id": 1})}
    acked = {entry["seq"] for entry in run["log"] if entry["outcome"] == "acked"}
    errors = {}
    for entry in run["log"]:
        if entry["outcome"] != "acked":
            errors[entry["outcome"]] = errors.get(entry["outcome"], 0) + 1
    print(f"w={run['w']}  attempted {len(run['log'])}  acknowledged {len(acked)}  failed {errors or 0}")
    print(f"acknowledged but lost: {len(acked - stored)}  {sorted(acked - stored)[:20]}")
    print(f"stored although reported failed: {len(stored - acked)}")
    print(f"slowest write: {max(entry['ms'] for entry in run['log'])} ms")
    client.drop_database(db_name)
    print(f"dropped {db_name}")


def cleanup(args):
    client = MongoClient(args.uri)
    leftovers = [name for name in client.list_database_names() if name.startswith(DB_PREFIX)]
    for name in leftovers:
        client.drop_database(name)
    print(f"dropped {len(leftovers)} lab databases {leftovers}")


def main():
    parser = argparse.ArgumentParser(description="Write numbered orders through a partition and count what survives.")
    parser.add_argument("--uri", default=os.environ.get("MONGO_TEST_URI"))
    commands = parser.add_subparsers(dest="command", required=True)

    writer = commands.add_parser("write", help=f"write orders into the throwaway database {DB_PREFIX}<run>")
    writer.add_argument("--run", required=True)
    writer.add_argument("--w", default="majority")
    writer.add_argument("--seconds", type=float, default=10)
    writer.add_argument("--interval", type=float, default=0.05)
    writer.add_argument("--timeout-ms", type=int, default=2000)
    writer.add_argument("--out", required=True)
    writer.set_defaults(handler=write)

    checker = commands.add_parser("check", help="count acknowledged orders that survived, then drop the run's database")
    checker.add_argument("--log", required=True)
    checker.set_defaults(handler=check)

    cleaner = commands.add_parser("cleanup", help=f"drop every {DB_PREFIX}* database left by an interrupted run")
    cleaner.set_defaults(handler=cleanup)

    args = parser.parse_args()
    if not args.uri:
        parser.error("set MONGO_TEST_URI or pass --uri")
    args.handler(args)


if __name__ == "__main__":
    main()
