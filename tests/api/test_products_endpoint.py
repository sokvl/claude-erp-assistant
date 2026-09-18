import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ExecutionTimeout, ServerSelectionTimeoutError

from app.config import API_KEY
from app.db import get_database
from app.limits import MAX_USE_CASES
from app.main import app

AUTH = {"X-API-Key": API_KEY}

VOCABULARIES = {
    "category": ["GPU", "CPU"],
    "brand": ["NVIDIA", "AMD"],
    "specs.architecture": ["Hopper", "Ada Lovelace"],
    "specs.memoryType": ["HBM3", "GDDR6X"],
    "specs.useCases": ["training", "inference", "gaming"],
}


class FakeCollection:
    def __init__(self, error=None):
        self.error = error
        self.aggregate_calls = []

    def distinct(self, path):
        return VOCABULARIES[path]

    def aggregate(self, pipeline, **kwargs):
        self.aggregate_calls.append(pipeline)
        if self.error:
            raise self.error
        return iter([{"items": [{"_id": "GPU-H100-80G"}], "total": 1}])


@pytest.fixture
def collection():
    fake = FakeCollection()
    app.dependency_overrides[get_database] = lambda: {"products": fake}
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(collection):
    return TestClient(app)


def test_list_products_query_params_reach_the_pipeline(client, collection):
    # Arrange: a repeated list param, a bool, an int, a float, enums and paging, all parsed from the query string
    query = "?category=GPU&use_case=training&use_case=inference&min_vram_gb=80&min_fp16_tflops=900.5" \
            "&requires_pooling=true&sort_by=vram&sort_order=desc&page=2&page_size=5"

    # Act
    client.get(f"/products{query}", headers=AUTH)

    # Assert
    [pipeline] = collection.aggregate_calls
    assert (pipeline[0], pipeline[1]["$facet"]["items"]) == (
        {"$match": {
            "category": "GPU",
            "specs.useCases": {"$in": ["training", "inference"]},
            "specs.vramGb": {"$gte": 80},
            "specs.fp16TensorTflopsDense": {"$gte": 900.5},
            "specs.multiGpuScaling": True,
        }},
        [{"$sort": {"specs.vramGb": -1, "_id": -1}}, {"$skip": 5}, {"$limit": 5}],
    )


def test_list_products_returns_paginated_envelope(client):
    # Arrange / Act
    body = client.get("/products", headers=AUTH).json()

    # Assert
    assert body == {
        "page": 1,
        "pageSize": 20,
        "total": 1,
        "items": [{"_id": "GPU-H100-80G"}],
    }


@pytest.mark.parametrize(
    "query",
    [
        # once an HTTP 500 (BSON int64 overflow); every other bound is test_schemas' job
        f"?min_vram_gb={2**63}",
        # query-string parsing: the text "nan" and a repeated param must still meet the model's bounds
        "?min_price=nan",
        "?" + "&".join(["use_case=training"] * (MAX_USE_CASES + 1)),
        # an operator payload arrives as a literal string and fails the whitelist like any unknown value
        "?category=%7B%22%24ne%22%3A%20null%7D",
        "?category=Widget",
        "?min_vram=24",
    ],
    ids=["vram_over_int64", "price_nan_text", "repeated_use_case_over_cap", "operator_payload",
         "unknown_category", "typo_param"],
)
def test_list_products_hostile_query_is_rejected_before_the_database(client, collection, query):
    # Arrange / Act
    response = client.get(f"/products{query}", headers=AUTH)

    # Assert
    assert (response.status_code, collection.aggregate_calls) == (422, [])


def test_list_products_error_detail_names_the_rejected_value(client):
    # Arrange / Act
    body = client.get("/products?category=Widget", headers=AUTH).json()

    # Assert
    assert "Widget" in str(body["detail"])


@pytest.mark.parametrize(
    "error",
    [ServerSelectionTimeoutError("connection refused at 10.0.0.5:27017"),
     ExecutionTimeout("operation exceeded time limit")],
    ids=["database_down", "query_timeout"],
)
def test_list_products_database_error_returns_503_without_internals(collection, error):
    # Arrange
    collection.error = error
    client = TestClient(app, raise_server_exceptions=False)

    # Act
    response = client.get("/products", headers=AUTH)

    # Assert
    assert (response.status_code, response.json()) == (503, {"detail": "Database unavailable"})


def test_list_facets_returns_live_vocabularies(client):
    # Arrange / Act
    body = client.get("/products/facets", headers=AUTH).json()

    # Assert
    assert body == {
        "category": ["CPU", "GPU"],
        "brand": ["AMD", "NVIDIA"],
        "architecture": ["Ada Lovelace", "Hopper"],
        "memory_type": ["GDDR6X", "HBM3"],
        "use_case": ["gaming", "inference", "training"],
    }
