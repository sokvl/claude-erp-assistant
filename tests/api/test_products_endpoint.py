import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ExecutionTimeout, ServerSelectionTimeoutError

from app.config import API_KEY
from app.db import get_database
from app.limits import MAX_PAGE, MAX_PAGE_SIZE, MAX_PRICE, MAX_TEXT_LENGTH, MAX_USE_CASES, MAX_VRAM_GB
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
        "?architecture=Hopper&memory_type=HBM3",
        f"?min_vram_gb={MAX_VRAM_GB}",
        f"?page={MAX_PAGE}&page_size={MAX_PAGE_SIZE}",
        f"?max_price={MAX_PRICE:.0f}",
        "?" + "&".join(["use_case=training"] * MAX_USE_CASES),
    ],
    ids=["no_filters", "category", "min_vram", "min_vram_zero", "use_cases",
         "training_scenario", "sorted", "paginated", "specs",
         "vram_at_cap", "page_and_size_at_cap", "price_at_cap", "use_cases_at_cap"],
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
    "query",
    [
        # previously reachable HTTP 500s (BSON int64 overflow)
        f"?min_vram_gb={2**63}",
        f"?min_vram_gb={10**30}",
        f"?page={10**18}",
        # over the domain caps
        f"?min_vram_gb={MAX_VRAM_GB + 1}",
        f"?page={MAX_PAGE + 1}",
        f"?page_size={MAX_PAGE_SIZE + 1}",
        f"?max_price={MAX_PRICE * 10:.0f}",
        # non-finite and out-of-range floats
        "?min_price=1e400",
        "?min_price=inf",
        "?min_price=nan",
        "?min_price=-1",
        # oversized inputs; a valid tag repeated so the cap, not the whitelist, rejects it
        "?category=" + "A" * (MAX_TEXT_LENGTH + 1),
        "?" + "&".join(["use_case=training"] * (MAX_USE_CASES + 1)),
        # injection payloads land as literal strings and fail the whitelist
        "?category=%7B%22%24ne%22%3A%20null%7D",
        "?category=%7B%22%24gt%22%3A%20%22%22%7D",
        "?brand=%24where",
        "?category=GPU%27%3B+DROP+TABLE+products%3B--",
        "?category=GPU%00",
        "?brand=..%2F..%2Fetc%2Fpasswd",
        # unknown vocabulary, bad enums, typos, contradictions
        "?category=Widget",
        "?architecture=Hoppr",
        "?use_case=mining",
        "?page=0",
        "?sort_by=listPrice",
        "?min_vram=24",
        "?min_vram_gb=80&max_vram_gb=8",
    ],
    ids=["vram_over_int64", "vram_absurd", "page_skip_overflow",
         "vram_over_cap", "page_over_cap", "page_size_over_cap", "price_over_cap",
         "price_overflows_to_inf", "price_inf", "price_nan", "price_negative",
         "category_too_long", "use_cases_over_cap",
         "operator_ne", "operator_gt", "operator_where", "sql_payload",
         "null_byte", "path_traversal",
         "unknown_category", "unknown_architecture", "unknown_use_case",
         "page_zero", "raw_sort_path", "typo_param", "inverted_range"],
)
def test_list_products_hostile_query_is_rejected_before_the_database(client, collection, query):
    # Arrange / Act
    response = client.get(f"/products{query}", headers=AUTH)

    # Assert
    assert (response.status_code, collection.aggregate_calls) == (422, [])


@pytest.mark.parametrize(
    "query",
    [
        f"?page={10**18}",
        f"?page={MAX_PAGE + 1}",
        f"?page_size={MAX_PAGE_SIZE + 1}",
        "?page=0",
        "?page=abc",
        "?page=1e3",
    ],
    ids=["page_skip_overflow", "page_over_cap", "page_size_over_cap",
         "page_zero", "page_not_a_number", "page_float_notation"],
)
def test_list_invoices_out_of_range_page_returns_422(client, query):
    # Arrange / Act
    response = client.get(f"/invoices{query}", headers=AUTH)

    # Assert
    assert response.status_code == 422


def test_list_products_error_detail_names_the_rejected_value(client):
    # Arrange / Act
    body = client.get("/products?category=Widget", headers=AUTH).json()

    # Assert
    assert "Widget" in str(body["detail"])


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/products", {}),
        ("/products", {"X-API-Key": "wrong"}),
        ("/products", {"X-API-Key": ""}),
        ("/products/facets", {}),
        ("/products/facets", {"X-API-Key": "wrong"}),
        ("/invoices", {}),
        ("/invoices", {"X-API-Key": "wrong"}),
    ],
    ids=["products_no_key", "products_bad_key", "products_empty_key",
         "facets_no_key", "facets_bad_key", "invoices_no_key", "invoices_bad_key"],
)
def test_endpoints_without_valid_api_key_return_401_with_challenge(client, path, headers):
    # Arrange / Act
    response = client.get(path, headers=headers)

    # Assert
    assert (response.status_code, response.headers.get("WWW-Authenticate")) == (401, "APIKey")


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
