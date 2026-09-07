"""
Phase 2 verification tests: authentication & RBAC.

Uses the real Postgres database (via the app's configured DATABASE_URL)
through FastAPI's TestClient -- not mocks -- so these tests exercise the
actual SQL, password hashing, and JWT code paths. Each test creates its
own uniquely-named user(s) to avoid collisions with manually-created
seed data or other test runs.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register(username: str, role: str = "FINANCE_ANALYST", password: str = "TestPass123") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@efdi-corp.com",
            "full_name": f"Test User {username}",
            "password": password,
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login(username: str, password: str = "TestPass123") -> dict:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    return response


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Registration ---

def test_register_creates_user_with_requested_role():
    username = _unique_username("reg")
    body = _register(username, role="FINANCE_MANAGER")
    assert body["username"] == username
    assert body["role"] == "FINANCE_MANAGER"
    assert body["is_active"] is True
    assert "password_hash" not in body
    assert "password" not in body


def test_register_duplicate_username_returns_409():
    username = _unique_username("dup")
    _register(username)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"different_{username}@efdi-corp.com",
            "full_name": "Someone Else",
            "password": "TestPass123",
            "role": "AUDITOR",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "AlreadyExistsException"


def test_register_weak_password_rejected():
    username = _unique_username("weak")
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@efdi-corp.com",
            "full_name": "Weak Password",
            "password": "alllettersnodigits",
            "role": "AUDITOR",
        },
    )
    assert response.status_code == 422


def test_register_invalid_username_characters_rejected():
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "bad username!",
            "email": "badname@efdi-corp.com",
            "full_name": "Bad Name",
            "password": "TestPass123",
            "role": "AUDITOR",
        },
    )
    assert response.status_code == 422


# --- Login ---

def test_login_success_returns_token_and_user():
    username = _unique_username("login")
    _register(username)
    response = _login(username)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["username"] == username
    assert len(body["access_token"]) > 20


def test_login_with_email_success():
    username = _unique_username("login_email")
    user_data = _register(username)
    email = user_data["email"]
    response = _login(email)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == username
    assert body["user"]["email"] == email


def test_login_with_whitespace_username_success():
    username = _unique_username("login_ws")
    _register(username)
    response = _login(f"  {username}  ")
    assert response.status_code == 200
    assert response.json()["user"]["username"] == username


def test_login_wrong_password_returns_401():
    username = _unique_username("wrongpw")
    _register(username)
    response = _login(username, password="TotallyWrong999")
    assert response.status_code == 401


def test_login_nonexistent_user_returns_401_not_404():
    """Must not leak whether the username exists (enumeration protection)."""
    response = _login("does_not_exist_at_all_xyz", password="Whatever123")
    assert response.status_code == 401


# --- Current user / token validation ---

def test_me_with_valid_token():
    username = _unique_username("me")
    _register(username)
    token = _login(username).json()["access_token"]
    response = client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert response.status_code == 200
    assert response.json()["username"] == username


def test_me_without_token_returns_401():
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_with_garbage_token_returns_401():
    response = client.get("/api/v1/auth/me", headers=_auth_header("not.a.valid.jwt"))
    assert response.status_code == 401


# --- RBAC ---

def test_admin_can_list_users():
    admin_username = _unique_username("admin")
    _register(admin_username, role="ADMIN")
    token = _login(admin_username).json()["access_token"]
    response = client.get("/api/v1/users", headers=_auth_header(token))
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 1


@pytest.mark.parametrize("role", ["FINANCE_MANAGER", "FINANCE_ANALYST", "AUDITOR"])
def test_non_admin_cannot_list_users(role):
    username = _unique_username(role.lower())
    _register(username, role=role)
    token = _login(username).json()["access_token"]
    response = client.get("/api/v1/users", headers=_auth_header(token))
    assert response.status_code == 403
    assert response.json()["error"] == "AuthorizationException"


def test_admin_can_change_user_role():
    admin_username = _unique_username("admin2")
    _register(admin_username, role="ADMIN")
    admin_token = _login(admin_username).json()["access_token"]

    target_username = _unique_username("target")
    target = _register(target_username, role="FINANCE_ANALYST")

    response = client.patch(
        f"/api/v1/users/{target['id']}/role",
        headers=_auth_header(admin_token),
        json={"role": "FINANCE_MANAGER"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "FINANCE_MANAGER"


def test_deactivated_user_cannot_login():
    admin_username = _unique_username("admin3")
    _register(admin_username, role="ADMIN")
    admin_token = _login(admin_username).json()["access_token"]

    target_username = _unique_username("deact")
    target = _register(target_username)

    deactivate_response = client.patch(
        f"/api/v1/users/{target['id']}/status",
        headers=_auth_header(admin_token),
        json={"is_active": False},
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False

    login_response = _login(target_username)
    assert login_response.status_code == 401


def test_deactivation_invalidates_existing_token_immediately():
    """
    Security property: deactivating a user must immediately invalidate
    their session, even if their JWT has not expired yet. This proves
    get_current_user re-checks the database on every request rather
    than trusting the token payload alone.
    """
    admin_username = _unique_username("admin4")
    _register(admin_username, role="ADMIN")
    admin_token = _login(admin_username).json()["access_token"]

    target_username = _unique_username("midsession")
    target = _register(target_username)
    target_token = _login(target_username).json()["access_token"]

    # Token works before deactivation
    response = client.get("/api/v1/auth/me", headers=_auth_header(target_token))
    assert response.status_code == 200

    # Admin deactivates mid-session
    client.patch(
        f"/api/v1/users/{target['id']}/status",
        headers=_auth_header(admin_token),
        json={"is_active": False},
    )

    # The SAME unexpired token must now be rejected
    response = client.get("/api/v1/auth/me", headers=_auth_header(target_token))
    assert response.status_code == 401


def test_non_admin_cannot_change_roles():
    username = _unique_username("notadmin")
    user = _register(username, role="FINANCE_ANALYST")
    token = _login(username).json()["access_token"]

    response = client.patch(
        f"/api/v1/users/{user['id']}/role",
        headers=_auth_header(token),
        json={"role": "ADMIN"},
    )
    assert response.status_code == 403
