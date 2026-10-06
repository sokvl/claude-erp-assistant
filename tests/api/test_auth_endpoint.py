import pytest
from fastapi.testclient import TestClient
from memory_collection import MemoryCollection

from app.auth.roles import Role
from app.auth.signer import LocalSigner
from app.auth.users import create_user
from app.db import get_database
from app.limits import ACCESS_TOKEN_MINUTES, MAX_LOGIN_ATTEMPTS
from app.main import app
from app.security import get_signer

PASSWORD = "correct horse battery staple"
BASE_URL = "https://testserver"


@pytest.fixture
def db():
    database = {"users": MemoryCollection(), "login_attempts": MemoryCollection(), "refresh_tokens": MemoryCollection()}
    create_user(database["users"], "anna", PASSWORD, Role.MANAGER)
    signer = LocalSigner()
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_signer] = lambda: signer
    yield database
    app.dependency_overrides.clear()


@pytest.fixture
def client(db):
    return TestClient(app, base_url=BASE_URL)


def _login(client, password=PASSWORD):
    return client.post("/auth/login", json={"username": "anna", "password": password})


def _bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_returns_an_access_token_and_a_locked_down_refresh_cookie(client):
    # Arrange / Act
    response = _login(client)

    # Assert
    body = response.json()
    cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 200
    assert (body["token_type"], body["expires_in"], body["username"], body["role"]) == (
        "bearer", ACCESS_TOKEN_MINUTES * 60, "anna", "manager",
    )
    assert all(part in cookie for part in ("refresh_token=", "httponly", "secure", "samesite=strict", "path=/auth"))
    assert "refresh_token" not in body


def test_me_with_the_access_token_returns_the_principal(client):
    # Arrange
    login = _login(client)

    # Act
    response = client.get("/auth/me", headers=_bearer(login))

    # Assert
    assert (response.status_code, response.json()) == (200, {"username": "anna", "role": "manager"})


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic YW5uYTpwYXNz"}],
    ids=["missing", "garbage", "wrong_scheme"],
)
def test_me_without_a_valid_token_returns_401_with_a_bearer_challenge(client, headers):
    # Arrange / Act
    response = client.get("/auth/me", headers=headers)

    # Assert
    assert (response.status_code, response.headers.get("www-authenticate")) == (401, "Bearer")


def test_refresh_with_the_cookie_rotates_it_and_issues_a_new_access_token(client):
    # Arrange
    login = _login(client)

    # Act
    response = client.post("/auth/refresh")

    # Assert
    assert response.status_code == 200
    assert response.cookies["refresh_token"] != login.cookies["refresh_token"]
    assert client.get("/auth/me", headers=_bearer(response)).json()["username"] == "anna"


# Replaying a rotated cookie kills the whole session, including the newest cookie.
def test_refresh_replayed_cookie_returns_401_and_ends_the_session(client):
    # Arrange
    stolen = _login(client).cookies["refresh_token"]
    client.post("/auth/refresh")
    attacker = TestClient(app, base_url=BASE_URL)

    # Act
    replay = attacker.post("/auth/refresh", headers={"Cookie": f"refresh_token={stolen}"})

    # Assert
    assert replay.status_code == 401
    assert client.post("/auth/refresh").status_code == 401


def test_refresh_without_a_cookie_returns_401(client):
    # Arrange / Act
    response = client.post("/auth/refresh")

    # Assert
    assert response.status_code == 401


def test_logout_clears_the_cookie_and_revokes_the_session(client):
    # Arrange
    cookie = _login(client).cookies["refresh_token"]

    # Act
    response = client.post("/auth/logout")

    # Assert
    replay = TestClient(app, base_url=BASE_URL).post("/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"})
    assert response.status_code == 204
    assert 'refresh_token=""' in response.headers["set-cookie"]
    assert replay.status_code == 401


def test_login_wrong_password_returns_401_then_429_once_locked(client):
    # Arrange
    for _ in range(MAX_LOGIN_ATTEMPTS - 1):
        _login(client, "wrong password")

    # Act
    last_failure = _login(client, "wrong password")
    locked = _login(client)

    # Assert
    assert (last_failure.status_code, last_failure.json()["detail"]) == (401, "Invalid username or password")
    assert locked.status_code == 429


@pytest.mark.parametrize(
    "body",
    [{"username": "anna"}, {"username": "anna", "password": PASSWORD, "role": "admin"}, {"username": "", "password": "x"}],
    ids=["missing_password", "extra_field", "empty_username"],
)
def test_login_invalid_body_returns_422(client, body):
    # Arrange / Act
    response = client.post("/auth/login", json=body)

    # Assert
    assert response.status_code == 422
