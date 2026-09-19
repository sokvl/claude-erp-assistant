import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "seed"))

from indexes import PRODUCT_INDEXES, sync_indexes  # noqa: E402

URI = "mongodb://localhost:27017"


def _gpu(sku, name, brand, price, vram, fp16, pooling, arch, memory, use_cases, **extra):
    return {
        "_id": sku, "sku": sku, "name": name, "brand": brand,
        "category": "GPU", "listPrice": price, "tier": "gpu_consumer",
        "specs": {
            "architecture": arch, "vramGb": vram, "memoryType": memory,
            "fp16TensorTflopsDense": fp16, "multiGpuScaling": pooling,
            "useCases": use_cases, "releaseYear": 2023, **extra,
        },
    }


# 5 GPUs spanning the VRAM range, 2 products with no `specs` at all, and one
# GPU carrying an explicit null - the AMD cards store tensorCoreCount: null.
FIXTURE_PRODUCTS = [
    _gpu("GPU-SMALL", "Test GPU 8GB", "NVIDIA", 249.0, 8, 121.0, False,
         "Ada Lovelace", "GDDR6", ["gaming", "inference"]),
    _gpu("GPU-MID", "Test GPU 24GB", "NVIDIA", 1499.0, 24, 330.0, False,
         "Ada Lovelace", "GDDR6X", ["gaming", "inference", "fine-tuning"]),
    _gpu("GPU-AMD-NULL", "Test Radeon 24GB", "AMD", 899.0, 24, 122.8, False,
         "RDNA 3", "GDDR6", ["gaming", "inference"], tensorCoreCount=None),
    _gpu("GPU-BIG", "Test GPU 80GB", "NVIDIA", 27999.0, 80, 989.0, True,
         "Hopper", "HBM3", ["training", "inference", "hpc"]),
    _gpu("GPU-HUGE", "Test GPU 192GB", "AMD", 26999.0, 192, 1307.4, True,
         "CDNA 3", "HBM3", ["training", "inference", "hpc"]),
    # same listPrice as GPU-MID, to prove the _id sort tiebreaker
    {"_id": "CPU-TEST", "sku": "CPU-TEST", "name": "Test CPU", "brand": "AMD",
     "category": "CPU", "listPrice": 1499.0},
    {"_id": "RAM-TEST", "sku": "RAM-TEST", "name": "Test RAM", "brand": "Corsair",
     "category": "RAM", "listPrice": 94.0},
]


@pytest.fixture(scope="session")
def mongo_client():
    client = MongoClient(URI, serverSelectionTimeoutMS=1000)
    try:
        client.admin.command("ping")
    except PyMongoError:
        pytest.skip("MongoDB not reachable on localhost:27017")
    yield client
    client.close()


@pytest.fixture(scope="session")
def products(mongo_client):
    # Arrange: a throwaway database, never the demo data in invoices_db
    db_name = f"test_catalog_{uuid4().hex[:8]}"
    collection = mongo_client[db_name]["products"]
    collection.insert_many(FIXTURE_PRODUCTS)
    sync_indexes(collection, PRODUCT_INDEXES)

    yield collection

    # Annihilate
    mongo_client.drop_database(db_name)


@pytest.fixture
def client(products):
    from fastapi.testclient import TestClient

    from app.db import get_database
    from app.main import app

    app.dependency_overrides[get_database] = lambda: {"products": products}
    yield TestClient(app)
    app.dependency_overrides.clear()
