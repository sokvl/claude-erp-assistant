import pytest
from fastapi.testclient import TestClient

from app.auth.roles import Principal, Role, allows
from app.db import get_database
from app.main import app
from app.routers.chat import assistant_client
from app.security import current_principal

ROUTES = [
    ("GET", "/products", None, Role.CONSULTANT),
    ("GET", "/products/facets", None, Role.CONSULTANT),
    ("POST", "/chat", {"message": "question"}, Role.CONSULTANT),
    ("POST", "/chat", {"message": "question", "assistant": "analyst"}, Role.MANAGER),
    ("GET", "/invoices", None, Role.MANAGER),
    ("GET", "/invoices/analytics", None, Role.MANAGER),
    ("GET", "/charts?conversation_id=conv-1", None, Role.MANAGER),
    ("GET", "/charts/chart-1/image", None, Role.MANAGER),
    ("POST", "/pending-actions/action-1/approve", None, Role.MANAGER),
    ("POST", "/pending-actions/action-1/reject", None, Role.MANAGER),
]
ROUTE_IDS = ["products", "facets", "chat_advisor", "chat_analyst", "invoices", "invoice_analytics",
             "charts", "chart_image", "approve", "reject"]


@pytest.fixture
def signed_in():
    def sign_in(role):
        app.dependency_overrides[current_principal] = lambda: Principal("anna", role)

    app.dependency_overrides[get_database] = lambda: {}
    app.dependency_overrides[assistant_client] = lambda: object()
    yield sign_in
    app.dependency_overrides.clear()


@pytest.mark.parametrize(("method", "path", "body", "minimum"), ROUTES, ids=ROUTE_IDS)
def test_every_route_without_a_token_returns_401_with_a_bearer_challenge(method, path, body, minimum):
    # Arrange
    client = TestClient(app)

    # Act
    response = client.request(method, path, json=body)

    # Assert
    assert (response.status_code, response.headers.get("WWW-Authenticate")) == (401, "Bearer")


# The role is checked before the route touches anything, so 403 means refused and any
# other status (here the empty database fails the request) means the role got through.
@pytest.mark.parametrize("role", list(Role), ids=[str(role) for role in Role])
@pytest.mark.parametrize(("method", "path", "body", "minimum"), ROUTES, ids=ROUTE_IDS)
def test_every_route_refuses_roles_that_do_not_grant_its_minimum(signed_in, role, method, path, body, minimum):
    # Arrange
    signed_in(role)
    client = TestClient(app, raise_server_exceptions=False)

    # Act
    response = client.request(method, path, json=body)

    # Assert
    assert (response.status_code == 403) is not allows(role, minimum)
