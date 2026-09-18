import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/products"),
        ("GET", "/products/facets"),
        ("GET", "/invoices"),
        ("GET", "/invoices/analytics"),
        ("POST", "/chat"),
    ],
    ids=["products", "facets", "invoices", "invoice_analytics", "chat"],
)
def test_every_router_rejects_a_missing_api_key_with_a_challenge(method, path):
    # Arrange: which keys are wrong is test_security's job; this proves each router carries the dependency
    client = TestClient(app)

    # Act
    response = client.request(method, path, json={"message": "question"} if method == "POST" else None)

    # Assert
    assert (response.status_code, response.headers.get("WWW-Authenticate")) == (401, "APIKey")
