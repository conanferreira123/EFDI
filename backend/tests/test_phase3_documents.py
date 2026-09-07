"""
Phase 3 verification tests: document management.

Uses the real Postgres database and real disk I/O (the configured
UPLOAD_DIR) via FastAPI's TestClient. Each test creates its own
uniquely-named users to avoid collisions across test runs.
"""
import io
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str, prefix: str = "user") -> tuple[str, dict]:
    username = _unique_username(prefix)
    password = "TestPass123"
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@efdi-corp.com",
            "full_name": f"Test {username}",
            "password": password,
            "role": role,
        },
    )
    assert register_response.status_code == 201, register_response.text
    user = register_response.json()

    login_response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    return token, user


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _minimal_pdf_bytes() -> bytes:
    """A syntactically minimal but valid-enough PDF for upload testing."""
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF"
    )


def _upload(token: str, filename: str, content: bytes, content_type: str = "application/pdf"):
    return client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": (filename, io.BytesIO(content), content_type)},
    )


# --- Upload ---

def test_upload_pdf_succeeds():
    token, _ = _register_and_login("FINANCE_ANALYST")
    response = _upload(token, "invoice.pdf", _minimal_pdf_bytes())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["original_filename"] == "invoice.pdf"
    assert body["status"] == "UPLOADED"
    assert body["document_type"] == "UNKNOWN"


def test_upload_disallowed_file_type_rejected():
    token, _ = _register_and_login("FINANCE_ANALYST")
    response = _upload(token, "notes.txt", b"plain text content", content_type="text/plain")
    assert response.status_code == 422
    assert response.json()["error"] == "FileProcessingException"


def test_upload_oversized_file_rejected(monkeypatch):
    """
    Patch the configured max size down to something tiny so the test
    doesn't need to generate a real 25MB+ payload.
    """
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)
    # max_upload_size_bytes is a property computed from MAX_UPLOAD_SIZE_MB,
    # so patching the underlying field is sufficient; 0 MB means any
    # non-empty file exceeds it.
    token, _ = _register_and_login("FINANCE_ANALYST")
    response = _upload(token, "invoice.pdf", _minimal_pdf_bytes())
    assert response.status_code == 422
    assert "exceeds the maximum allowed size" in response.json()["message"]


def test_upload_requires_authentication():
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("invoice.pdf", io.BytesIO(_minimal_pdf_bytes()), "application/pdf")},
    )
    assert response.status_code == 401


# --- Download round-trip ---

def test_download_returns_identical_bytes():
    token, _ = _register_and_login("FINANCE_ANALYST")
    original_content = _minimal_pdf_bytes()
    upload_response = _upload(token, "roundtrip.pdf", original_content)
    document_id = upload_response.json()["id"]

    download_response = client.get(
        f"/api/v1/documents/{document_id}/download", headers=_auth_header(token)
    )
    assert download_response.status_code == 200
    assert download_response.content == original_content


def test_get_nonexistent_document_returns_404():
    token, _ = _register_and_login("FINANCE_ANALYST")
    response = client.get("/api/v1/documents/99999999", headers=_auth_header(token))
    assert response.status_code == 404


# --- List / search ---

def test_list_returns_only_own_documents_for_analyst():
    token_a, _ = _register_and_login("FINANCE_ANALYST", "analyst_a")
    token_b, _ = _register_and_login("FINANCE_ANALYST", "analyst_b")

    _upload(token_a, "a_doc.pdf", _minimal_pdf_bytes())
    _upload(token_b, "b_doc.pdf", _minimal_pdf_bytes())

    response = client.get("/api/v1/documents", headers=_auth_header(token_a))
    assert response.status_code == 200
    body = response.json()
    filenames = [item["original_filename"] for item in body["items"]]
    assert "a_doc.pdf" in filenames
    assert "b_doc.pdf" not in filenames


def test_analyst_cannot_get_other_analyst_document_directly():
    token_a, _ = _register_and_login("FINANCE_ANALYST", "direct_a")
    token_b, _ = _register_and_login("FINANCE_ANALYST", "direct_b")

    upload_response = _upload(token_b, "private.pdf", _minimal_pdf_bytes())
    document_id = upload_response.json()["id"]

    response = client.get(f"/api/v1/documents/{document_id}", headers=_auth_header(token_a))
    assert response.status_code == 403


def test_auditor_can_see_all_documents():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "oversight_target")
    auditor_token, _ = _register_and_login("AUDITOR", "oversight_auditor")

    upload_response = _upload(analyst_token, "oversight.pdf", _minimal_pdf_bytes())
    document_id = upload_response.json()["id"]

    response = client.get(f"/api/v1/documents/{document_id}", headers=_auth_header(auditor_token))
    assert response.status_code == 200


def test_filename_search_filters_correctly():
    token, _ = _register_and_login("FINANCE_ANALYST", "search_user")
    unique_marker = uuid.uuid4().hex[:8]
    _upload(token, f"findme_{unique_marker}.pdf", _minimal_pdf_bytes())
    _upload(token, f"other_{unique_marker}.pdf", _minimal_pdf_bytes())

    response = client.get(
        f"/api/v1/documents?filename=findme_{unique_marker}", headers=_auth_header(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["original_filename"] == f"findme_{unique_marker}.pdf"


# --- Delete ---

def test_user_can_soft_delete_own_document():
    token, _ = _register_and_login("FINANCE_ANALYST", "deleter")
    upload_response = _upload(token, "to_delete.pdf", _minimal_pdf_bytes())
    document_id = upload_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/documents/{document_id}", headers=_auth_header(token)
    )
    assert delete_response.status_code == 200

    get_response = client.get(f"/api/v1/documents/{document_id}", headers=_auth_header(token))
    assert get_response.status_code == 404


def test_user_cannot_delete_other_users_document():
    token_a, _ = _register_and_login("FINANCE_ANALYST", "victim")
    token_b, _ = _register_and_login("FINANCE_ANALYST", "attacker")

    upload_response = _upload(token_a, "victim_doc.pdf", _minimal_pdf_bytes())
    document_id = upload_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/documents/{document_id}", headers=_auth_header(token_b)
    )
    assert delete_response.status_code == 403
