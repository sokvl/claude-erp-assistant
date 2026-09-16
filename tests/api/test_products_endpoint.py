import pytest
from fastapi.testclient import TestClient

from app.catalog import vocab
from app.config import API_KEY
from app.db import products_collection
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
    def __init__(self):
        self.aggregate_calls = []

    def distinct(self, path):
        return VOCABULARIES[path]

    def aggregate(self, pipeline, **kwargs):
        self.aggregate_calls.append(pipeline)
        return iter([{"items": [{"_id": "GPU-H100-80G"}], "total": 1}])


@pytest.fixture
def collection():
    fake = FakeCollection()
    app.dependency_overrides[products_collection] = lambda: fake
    vocab.clear_cache()
    yield fake
    app.dependency_overrides.clear()
    vocab.clear_cache()


@pytest.fixture
def client(collection):
    return TestClient(app)


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?category=GPU",
        "?min_vram_gb=24",
        "?min_vram_gb=0",
        "?use_case=training&use_case=inference",
        "?min_vram_gb=80&min_fp16_tflops=900&requires_pooling=true",
        "?sort_by=vram&sort_order=desc",
        "?page=2&page_size=5",
        "?min_vram_gb=999999",
        "?architecture=Hopper&memory_type=HBM3",
    ],
    ids=["no_filters", "category", "min_vram", "min_vram_zero", "use_cases",
         "training_scenario", "sorted", "paginated", "unreachable_vram", "specs"],
)
def test_list_products_valid_query_returns_200(client, query):
    # Arrange / Act
    response = client.get(f"/products{query}", headers=AUTH)

    # Assert
    assert response.status_code == 200


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
    ("query", "expected_status"),
    [
        ("?category=Widget", 422),
        ("?brand=Nvidea", 422),
        ("?architecture=Hoppr", 422),
        ("?use_case=mining", 422),
        ("?page=0", 422),
        ("?page_size=101", 422),
        ("?min_price=-1", 422),
        ("?sort_by=listPrice", 422),
        ("?min_vram=24", 422),
        ("?min_vram_gb=80&max_vram_gb=8", 422),
    ],
    ids=["unknown_category", "unknown_brand", "unknown_architecture",
         "unknown_use_case", "page_zero", "page_size_over_max",
         "negative_price", "raw_sort_path", "typo_param", "inverted_range"],
)
def test_list_products_invalid_query_returns_422(client, query, expected_status):
    # Arrange / Act
    response = client.get(f"/products{query}", headers=AUTH)

    # Assert
    assert response.status_code == expected_status


def test_list_products_unknown_vocabulary_value_never_reaches_the_database(client, collection):
    # Arrange / Act
    response = client.get("/products?architecture=Hoppr", headers=AUTH)

    # Assert: validation alone is not enough - nothing may reach aggregate()
    assert response.status_code == 422
    assert collection.aggregate_calls == []


def test_list_products_error_detail_names_the_rejected_value(client):
    # Arrange / Act
    body = client.get("/products?category=Widget", headers=AUTH).json()

    # Assert
    assert "Widget" in str(body["detail"])


@pytest.mark.parametrize(
    ("path", "headers"),
    [("/products", {}), ("/products", {"X-API-Key": "wrong"}),
     ("/products/facets", {}), ("/products/facets", {"X-API-Key": "wrong"})],
    ids=["products_no_key", "products_bad_key", "facets_no_key", "facets_bad_key"],
)
def test_endpoints_require_a_valid_api_key(client, path, headers):
    # Arrange / Act
    response = client.get(path, headers=headers)

    # Assert
    assert response.status_code in (401, 403)


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
