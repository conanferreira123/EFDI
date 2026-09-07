"""
Phase 1 verification tests: project foundation.

These tests prove out the core scaffolding (config, logging, exception
handling, database connectivity, health check) before any business
logic (auth, documents, etc.) is layered on top in later phases.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    AlreadyExistsException,
    AuthenticationException,
    AuthorizationException,
    EFDIException,
    NotFoundException,
    ValidationFailedException,
)
from app.main import app, efdi_exception_handler, unhandled_exception_handler


def test_health_check_reports_db_connected():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database_connected"] is True
    assert body["app_name"] == "Enterprise Financial Document Intelligence"


def test_root_endpoint():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "docs" in response.json()


def test_openapi_schema_generates():
    client = TestClient(app)
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Enterprise Financial Document Intelligence"


def _build_probe_app() -> FastAPI:
    """
    Build a tiny throwaway FastAPI app that reuses our real exception
    handlers and raises each domain exception on a dedicated route.
    This proves the global exception handler machinery in main.py
    behaves correctly, without permanently adding test-only routes to
    the real application.
    """
    probe = FastAPI()
    probe.add_exception_handler(EFDIException, efdi_exception_handler)
    probe.add_exception_handler(Exception, unhandled_exception_handler)

    @probe.get("/raise/not-found")
    def raise_not_found():
        raise NotFoundException("Document", 42)

    @probe.get("/raise/already-exists")
    def raise_already_exists():
        raise AlreadyExistsException("User", "username", "jdoe")

    @probe.get("/raise/validation")
    def raise_validation():
        raise ValidationFailedException("Bad input", errors=["field x is required"])

    @probe.get("/raise/auth")
    def raise_auth():
        raise AuthenticationException()

    @probe.get("/raise/authz")
    def raise_authz():
        raise AuthorizationException()

    @probe.get("/raise/unhandled")
    def raise_unhandled():
        raise RuntimeError("boom - this should never leak to the client")

    return probe


def test_not_found_exception_maps_to_404():
    client = TestClient(_build_probe_app(), raise_server_exceptions=False)
    response = client.get("/raise/not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "NotFoundException"
    assert "Document" in body["message"]
    assert body["details"]["id"] == 42


def test_already_exists_exception_maps_to_409():
    client = TestClient(_build_probe_app(), raise_server_exceptions=False)
    response = client.get("/raise/already-exists")
    assert response.status_code == 409


def test_validation_exception_maps_to_422():
    client = TestClient(_build_probe_app(), raise_server_exceptions=False)
    response = client.get("/raise/validation")
    assert response.status_code == 422
    assert response.json()["details"]["errors"] == ["field x is required"]


def test_authentication_exception_maps_to_401():
    client = TestClient(_build_probe_app(), raise_server_exceptions=False)
    response = client.get("/raise/auth")
    assert response.status_code == 401


def test_authorization_exception_maps_to_403():
    client = TestClient(_build_probe_app(), raise_server_exceptions=False)
    response = client.get("/raise/authz")
    assert response.status_code == 403


def test_unhandled_exception_does_not_leak_details():
    client = TestClient(_build_probe_app(), raise_server_exceptions=False)
    response = client.get("/raise/unhandled")
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "InternalServerError"
    # Critical: the original exception message must NOT be exposed to the client.
    assert "boom" not in body["message"]
