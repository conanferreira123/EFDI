"""
Phase 9 verification tests: audit system.

Covers AuditLog creation across every audited action (login
success/failure, registration, upload, delete, OCR, classification,
extraction, manual field correction, validation, and all three
workflow actions), the AUDITOR/ADMIN-only access restriction on the
audit endpoints, and that login failures never leak a real user_id
(username-enumeration protection extends to the audit trail itself).
"""
import io
import uuid

from fastapi.testclient import TestClient

from app.database.session import get_db_context
from app.main import app
from app.models.document_enums import AuditAction
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.classification_result_repository import ClassificationResultRepository
from app.repositories.extraction_result_repository import ExtractionResultRepository
from app.repositories.ocr_result_repository import OCRResultRepository

client = TestClient(app)

CLEAN_POI_FIELDS = {
    "buyer_name": "Our Co", "currency": "INR",
    "po_number": "PO-2026-789",
    "invoice_number": "INV-2026-001", "invoice_date": "2026-06-15",
    "grand_total_amount": "25000.00", "total_tax_amount": "4500.00", "subtotal_net_amount": "20500.00",
    "vendor_code": "V-1001", "seller_name": "Acme Corp",
}


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "audituser") -> tuple[str, dict]:
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


def _minimal_pdf_bytes(salt: bytes = b"") -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF" + salt
    )


def _upload(token: str, content: bytes) -> int:
    response = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": ("test.pdf", io.BytesIO(content), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _logs_for_document(document_id: int) -> list[dict]:
    """Read audit_logs directly from the DB, bypassing the API, for assertions independent of access control."""
    with get_db_context() as db:
        repo = AuditLogRepository(db)
        entries = repo.list_for_document(document_id)
        return [{"action": e.action, "user_id": e.user_id, "details": e.details} for e in entries]


def _logs_for_action(action: str) -> list[dict]:
    with get_db_context() as db:
        repo = AuditLogRepository(db)
        entries, _ = repo.search(action=action, limit=200)
        return [{"action": e.action, "user_id": e.user_id, "details": e.details} for e in entries]


def _inject_classification(document_id: int, predicted_type: str) -> None:
    with get_db_context() as db:
        repo = ClassificationResultRepository(db)
        repo.create(
            document_id=document_id, predicted_type=predicted_type, confidence=0.9,
            engine_name="test_injection", signals=[], scores_by_type={},
        )


def _inject_extraction(document_id: int, document_type: str, fields: dict) -> None:
    full_fields = {
        key: {"value": val, "confidence": 0.9, "matched_text": None, "is_found": val is not None}
        for key, val in fields.items()
    }
    with get_db_context() as db:
        repo = ExtractionResultRepository(db)
        found = sum(1 for f in full_fields.values() if f["is_found"])
        repo.create(
            document_id=document_id, document_type=document_type, engine_name="test_injection",
            fields=full_fields, overall_confidence=0.9,
            fields_found_count=found, fields_total_count=len(full_fields),
        )


def _setup_extracted_document(token: str) -> int:
    """Upload + stub OCR + injected classification/extraction -> EXTRACTED, ready to validate."""
    document_id = _upload(token, _minimal_pdf_bytes(str(uuid.uuid4()).encode()))
    client.post(f"/api/v1/ocr/documents/{document_id}/run", headers=_auth_header(token), json={"engine": "stub"})

    with get_db_context() as db:
        repo = OCRResultRepository(db)
        repo.create(
            document_id=document_id, engine_name="test_injection", page_count=1,
            full_text="irrelevant for this test since classification/extraction are injected directly",
            average_confidence=0.9, raw_blocks=[], processing_time_ms=0,
        )

    _inject_classification(document_id, "POI")
    _inject_extraction(document_id, "POI", CLEAN_POI_FIELDS)
    return document_id


def _setup_validated_document(token: str) -> int:
    document_id = _setup_extracted_document(token)
    validate_response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate", headers=_auth_header(token), json={}
    )
    assert validate_response.status_code == 201
    assert validate_response.json()["is_valid"] is True
    return document_id


# --- Auth events ---

def test_registration_is_audited():
    _, user = _register_and_login("FINANCE_ANALYST", "auditreg")
    logs = _logs_for_action(AuditAction.USER_REGISTERED.value)
    matching = [l for l in logs if l["user_id"] == user["id"]]
    assert len(matching) == 1
    assert matching[0]["details"]["username"] == user["username"]


def test_successful_login_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditloginok")
    logs = _logs_for_action(AuditAction.LOGIN_SUCCESS.value)
    matching = [l for l in logs if l["user_id"] == user["id"]]
    assert len(matching) == 1


def test_failed_login_is_audited_without_leaking_user_id():
    username = _unique_username("auditloginfail")
    password = "TestPass123"
    client.post(
        "/api/v1/auth/register",
        json={
            "username": username, "email": f"{username}@efdi-corp.com",
            "full_name": "Audit Fail Test", "password": password, "role": "FINANCE_ANALYST",
        },
    )

    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "WrongPassword999"}
    )
    assert response.status_code == 401

    logs = _logs_for_action(AuditAction.LOGIN_FAILED.value)
    matching = [l for l in logs if l["details"].get("attempted_username") == username]
    assert len(matching) == 1
    # Critical: even though the username belongs to a real, known user,
    # the audit entry must NOT resolve and store that user's id -- doing
    # so would let anyone with audit access distinguish "user exists"
    # from "user doesn't exist" via the log, defeating the same
    # enumeration protection AuthService already enforces on the
    # response itself.
    assert matching[0]["user_id"] is None


def test_failed_login_for_nonexistent_user_is_audited():
    nonexistent_username = _unique_username("doesnotexist")
    response = client.post(
        "/api/v1/auth/login",
        json={"username": nonexistent_username, "password": "Whatever123"},
    )
    assert response.status_code == 401

    logs = _logs_for_action(AuditAction.LOGIN_FAILED.value)
    matching = [l for l in logs if l["details"].get("attempted_username") == nonexistent_username]
    assert len(matching) == 1
    assert matching[0]["user_id"] is None


# --- Document lifecycle events ---

def test_upload_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditupload")
    document_id = _upload(token, _minimal_pdf_bytes(str(uuid.uuid4()).encode()))

    logs = _logs_for_document(document_id)
    upload_logs = [l for l in logs if l["action"] == AuditAction.DOCUMENT_UPLOADED.value]
    assert len(upload_logs) == 1
    assert upload_logs[0]["user_id"] == user["id"]


def test_delete_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditdelete")
    document_id = _upload(token, _minimal_pdf_bytes(str(uuid.uuid4()).encode()))

    response = client.delete(f"/api/v1/documents/{document_id}", headers=_auth_header(token))
    assert response.status_code == 200

    logs = _logs_for_document(document_id)
    delete_logs = [l for l in logs if l["action"] == AuditAction.DOCUMENT_DELETED.value]
    assert len(delete_logs) == 1
    assert delete_logs[0]["user_id"] == user["id"]


# --- Processing pipeline events ---

def test_ocr_run_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditocr")
    document_id = _upload(token, _minimal_pdf_bytes(str(uuid.uuid4()).encode()))

    response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run", headers=_auth_header(token), json={"engine": "stub"}
    )
    assert response.status_code == 201

    logs = _logs_for_document(document_id)
    ocr_logs = [l for l in logs if l["action"] == AuditAction.OCR_RUN.value]
    assert len(ocr_logs) == 1
    assert ocr_logs[0]["user_id"] == user["id"]
    assert ocr_logs[0]["details"]["engine"] == "stub"


def test_classification_run_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditclassify")
    document_id = _setup_extracted_document(token)

    # _setup_extracted_document injects classification directly (bypassing
    # the API) for speed, so call the real endpoint here to exercise and
    # verify the actual audited code path.
    response = client.post(
        f"/api/v1/classification/documents/{document_id}/classify", headers=_auth_header(token), json={}
    )
    assert response.status_code == 201

    logs = _logs_for_document(document_id)
    classify_logs = [l for l in logs if l["action"] == AuditAction.CLASSIFICATION_RUN.value]
    assert len(classify_logs) == 1
    assert classify_logs[0]["user_id"] == user["id"]


def test_extraction_run_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditextract")
    document_id = _upload(token, _minimal_pdf_bytes(str(uuid.uuid4()).encode()))
    client.post(f"/api/v1/ocr/documents/{document_id}/run", headers=_auth_header(token), json={"engine": "stub"})
    client.post(f"/api/v1/classification/documents/{document_id}/classify", headers=_auth_header(token), json={})

    response = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract", headers=_auth_header(token), json={}
    )
    assert response.status_code == 201

    logs = _logs_for_document(document_id)
    extract_logs = [l for l in logs if l["action"] == AuditAction.EXTRACTION_RUN.value]
    assert len(extract_logs) == 1
    assert extract_logs[0]["user_id"] == user["id"]


def test_field_correction_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditcorrect")
    document_id = _setup_extracted_document(token)

    response = client.patch(
        f"/api/v1/extraction/documents/{document_id}/fields/seller_name",
        headers=_auth_header(token), json={"value": "Corrected Vendor Inc."},
    )
    assert response.status_code == 200

    logs = _logs_for_document(document_id)
    correction_logs = [l for l in logs if l["action"] == AuditAction.EXTRACTION_FIELD_CORRECTED.value]
    assert len(correction_logs) == 1
    assert correction_logs[0]["user_id"] == user["id"]
    assert correction_logs[0]["details"]["field_key"] == "seller_name"
    assert correction_logs[0]["details"]["new_value"] == "Corrected Vendor Inc."


def test_validation_run_is_audited():
    token, user = _register_and_login("FINANCE_ANALYST", "auditvalidate")
    document_id = _setup_extracted_document(token)

    response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate", headers=_auth_header(token), json={}
    )
    assert response.status_code == 201

    logs = _logs_for_document(document_id)
    validation_logs = [l for l in logs if l["action"] == AuditAction.VALIDATION_RUN.value]
    assert len(validation_logs) == 1
    assert validation_logs[0]["user_id"] == user["id"]
    assert validation_logs[0]["details"]["is_valid"] is True


# --- Workflow events ---

def test_workflow_actions_are_audited():
    analyst_token, analyst = _register_and_login("FINANCE_ANALYST", "auditwfanalyst")
    manager_token, manager = _register_and_login("FINANCE_MANAGER", "auditwfmanager")
    document_id = _setup_validated_document(analyst_token)

    request_response = client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )
    assert request_response.status_code == 200

    approve_response = client.post(
        f"/api/v1/workflow/documents/{document_id}/approve",
        headers=_auth_header(manager_token), json={"comment": "Looks good"},
    )
    assert approve_response.status_code == 200

    logs = _logs_for_document(document_id)
    requested = [l for l in logs if l["action"] == AuditAction.APPROVAL_REQUESTED.value]
    approved = [l for l in logs if l["action"] == AuditAction.DOCUMENT_APPROVED.value]

    assert len(requested) == 1
    assert requested[0]["user_id"] == analyst["id"]
    assert len(approved) == 1
    assert approved[0]["user_id"] == manager["id"]
    assert approved[0]["details"]["comment"] == "Looks good"


def test_rejection_is_audited():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "auditwfreject")
    manager_token, manager = _register_and_login("FINANCE_MANAGER", "auditwfreject_mgr")
    document_id = _setup_validated_document(analyst_token)

    client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )
    reject_response = client.post(
        f"/api/v1/workflow/documents/{document_id}/reject",
        headers=_auth_header(manager_token), json={"comment": "Vendor code mismatch"},
    )
    assert reject_response.status_code == 200

    logs = _logs_for_document(document_id)
    rejected = [l for l in logs if l["action"] == AuditAction.DOCUMENT_REJECTED.value]
    assert len(rejected) == 1
    assert rejected[0]["user_id"] == manager["id"]
    assert rejected[0]["details"]["comment"] == "Vendor code mismatch"


# --- Access control on audit endpoints ---

def test_analyst_cannot_view_audit_logs():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "auditnoaccess")
    response = client.get("/api/v1/audit/logs", headers=_auth_header(analyst_token))
    assert response.status_code == 403


def test_manager_cannot_view_audit_logs():
    """
    Deliberately excluded per design: managers approve/reject documents
    but don't get a cross-cutting view of every user's activity.
    """
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "auditnoaccessmgr")
    response = client.get("/api/v1/audit/logs", headers=_auth_header(manager_token))
    assert response.status_code == 403


def test_auditor_can_view_audit_logs():
    auditor_token, _ = _register_and_login("AUDITOR", "auditviewer")
    response = client.get("/api/v1/audit/logs", headers=_auth_header(auditor_token))
    assert response.status_code == 200
    body = response.json()
    assert "items" in body and "total" in body


def test_admin_can_view_audit_logs():
    admin_token, _ = _register_and_login("ADMIN", "auditviewadmin")
    response = client.get("/api/v1/audit/logs", headers=_auth_header(admin_token))
    assert response.status_code == 200


def test_auditor_can_filter_logs_by_action():
    auditor_token, _ = _register_and_login("AUDITOR", "auditfilter")
    response = client.get(
        "/api/v1/audit/logs",
        headers=_auth_header(auditor_token),
        params={"action": AuditAction.LOGIN_SUCCESS.value},
    )
    assert response.status_code == 200
    body = response.json()
    assert all(item["action"] == AuditAction.LOGIN_SUCCESS.value for item in body["items"])


def test_analyst_cannot_view_document_audit_logs():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "auditdocnoaccess")
    document_id = _upload(analyst_token, _minimal_pdf_bytes(str(uuid.uuid4()).encode()))

    # Even the document's own uploader cannot view its audit trail --
    # unlike workflow history, audit-log access is role-gated, not
    # ownership-gated (see app/routers/audit.py module docstring).
    response = client.get(
        f"/api/v1/audit/documents/{document_id}/logs", headers=_auth_header(analyst_token)
    )
    assert response.status_code == 403


def test_auditor_can_view_document_audit_logs():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "auditdocowner")
    auditor_token, _ = _register_and_login("AUDITOR", "auditdocviewer")
    document_id = _upload(analyst_token, _minimal_pdf_bytes(str(uuid.uuid4()).encode()))

    response = client.get(
        f"/api/v1/audit/documents/{document_id}/logs", headers=_auth_header(auditor_token)
    )
    assert response.status_code == 200
    body = response.json()
    assert any(item["action"] == AuditAction.DOCUMENT_UPLOADED.value for item in body)
