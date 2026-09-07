"""
Phase 10 verification tests: bulk intake modes (multipart bulk-upload
and server-side folder-scan).

Uses the real Postgres database and real disk I/O via FastAPI's
TestClient, same as test_phase3_documents.py. Folder-scan tests write
real files into the actual configured INTAKE_SCAN_DIR (created on
demand) rather than mocking the filesystem, so the test exercises the
real path-resolution and directory-listing code, not a stand-in for it.
"""
import io
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.utils.file_storage import get_intake_dir

client = TestClient(app)


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "intakeuser") -> tuple[str, dict]:
    username = _unique_username(prefix)
    password = "TestPass123"
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username, "email": f"{username}@efdi-corp.com",
            "full_name": f"Test {username}", "password": password, "role": role,
        },
    )
    assert register_response.status_code == 201, register_response.text
    user = register_response.json()

    login_response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"], user


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _pdf_bytes(salt: bytes = b"") -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF" + salt
    )


# --- Bulk multipart upload ---

def test_bulk_upload_all_succeed():
    token, _ = _register_and_login(prefix="bulkok")
    files = [
        ("files", (f"doc_{i}.pdf", io.BytesIO(_pdf_bytes(str(uuid.uuid4()).encode())), "application/pdf"))
        for i in range(3)
    ]
    response = client.post("/api/v1/documents/upload/bulk", headers=_auth_header(token), files=files)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_files"] == 3
    assert body["succeeded"] == 3
    assert body["failed"] == 0
    assert all(r["success"] and r["document_id"] is not None for r in body["results"])


def test_bulk_upload_partial_success_one_bad_type():
    token, _ = _register_and_login(prefix="bulkpartial")
    files = [
        ("files", ("good.pdf", io.BytesIO(_pdf_bytes(str(uuid.uuid4()).encode())), "application/pdf")),
        ("files", ("bad.exe", io.BytesIO(b"not a real document"), "application/x-msdownload")),
    ]
    response = client.post("/api/v1/documents/upload/bulk", headers=_auth_header(token), files=files)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_files"] == 2
    assert body["succeeded"] == 1
    assert body["failed"] == 1

    good_result = next(r for r in body["results"] if r["filename"] == "good.pdf")
    bad_result = next(r for r in body["results"] if r["filename"] == "bad.exe")
    assert good_result["success"] is True
    assert good_result["document_id"] is not None
    assert bad_result["success"] is False
    assert bad_result["error"] is not None


def test_bulk_upload_requires_authentication():
    files = [("files", ("doc.pdf", io.BytesIO(_pdf_bytes()), "application/pdf"))]
    response = client.post("/api/v1/documents/upload/bulk", files=files)
    assert response.status_code == 401


def test_bulk_uploaded_documents_are_individually_audited():
    """Each successful item in a bulk upload should produce its own DOCUMENT_UPLOADED audit entry."""
    from app.database.session import get_db_context
    from app.repositories.audit_log_repository import AuditLogRepository

    analyst_token, analyst = _register_and_login(prefix="bulkaudit")
    files = [
        ("files", (f"audited_{i}.pdf", io.BytesIO(_pdf_bytes(str(uuid.uuid4()).encode())), "application/pdf"))
        for i in range(2)
    ]
    response = client.post("/api/v1/documents/upload/bulk", headers=_auth_header(analyst_token), files=files)
    assert response.status_code == 201
    document_ids = [r["document_id"] for r in response.json()["results"]]

    with get_db_context() as db:
        repo = AuditLogRepository(db)
        for doc_id in document_ids:
            logs = repo.list_for_document(doc_id)
            upload_logs = [l for l in logs if l.action == "DOCUMENT_UPLOADED"]
            assert len(upload_logs) == 1
            assert upload_logs[0].user_id == analyst["id"]


# --- Folder-scan intake ---

def test_folder_scan_requires_admin():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", prefix="scannoaccess")
    response = client.post(
        "/api/v1/documents/intake/scan-folder", headers=_auth_header(analyst_token), json={}
    )
    assert response.status_code == 403


def test_folder_scan_ingests_files_in_intake_root():
    admin_token, _ = _register_and_login("ADMIN", prefix="scanadmin")

    intake_dir = get_intake_dir()
    unique_name = f"scan_{uuid.uuid4().hex[:8]}.pdf"
    (intake_dir / unique_name).write_bytes(_pdf_bytes(str(uuid.uuid4()).encode()))

    response = client.post(
        "/api/v1/documents/intake/scan-folder", headers=_auth_header(admin_token), json={}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    matching = [r for r in body["results"] if r["filename"] == unique_name]
    assert len(matching) == 1
    assert matching[0]["success"] is True
    assert matching[0]["document_id"] is not None


def test_folder_scan_subpath_must_stay_within_intake_root():
    admin_token, _ = _register_and_login("ADMIN", prefix="scanescape")
    response = client.post(
        "/api/v1/documents/intake/scan-folder",
        headers=_auth_header(admin_token),
        json={"subpath": "../../../etc"},
    )
    assert response.status_code == 422


def test_folder_scan_nonexistent_subpath_returns_clear_error():
    admin_token, _ = _register_and_login("ADMIN", prefix="scanmissing")
    response = client.post(
        "/api/v1/documents/intake/scan-folder",
        headers=_auth_header(admin_token),
        json={"subpath": f"does_not_exist_{uuid.uuid4().hex[:8]}"},
    )
    assert response.status_code == 422


def test_folder_scan_skips_disallowed_file_types():
    admin_token, _ = _register_and_login("ADMIN", prefix="scanskip")

    intake_dir = get_intake_dir()
    txt_name = f"not_a_doc_{uuid.uuid4().hex[:8]}.txt"
    (intake_dir / txt_name).write_text("this should be ignored by the scan")

    response = client.post(
        "/api/v1/documents/intake/scan-folder", headers=_auth_header(admin_token), json={}
    )
    assert response.status_code == 201
    body = response.json()
    assert not any(r["filename"] == txt_name for r in body["results"])


def test_folder_scan_results_are_individually_audited():
    from app.database.session import get_db_context
    from app.repositories.audit_log_repository import AuditLogRepository

    admin_token, admin = _register_and_login("ADMIN", prefix="scanaudit")

    intake_dir = get_intake_dir()
    unique_name = f"scanaudit_{uuid.uuid4().hex[:8]}.pdf"
    (intake_dir / unique_name).write_bytes(_pdf_bytes(str(uuid.uuid4()).encode()))

    response = client.post(
        "/api/v1/documents/intake/scan-folder", headers=_auth_header(admin_token), json={}
    )
    assert response.status_code == 201
    matching = next(r for r in response.json()["results"] if r["filename"] == unique_name)
    document_id = matching["document_id"]

    with get_db_context() as db:
        repo = AuditLogRepository(db)
        logs = repo.list_for_document(document_id)
        upload_logs = [l for l in logs if l.action == "DOCUMENT_UPLOADED"]
        assert len(upload_logs) == 1
        assert upload_logs[0].user_id == admin["id"]
        assert upload_logs[0].details.get("via") == "folder_scan"
