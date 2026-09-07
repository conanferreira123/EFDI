"""
Phase 8 verification tests: approval workflow.

Covers the state machine rules (app/workflow/state_machine.py), role
restrictions on approve/reject, the mandatory-comment-on-reject rule,
workflow history recording, and the resubmission-requires-revalidation
design decision end to end via the real API.
"""
import io
import uuid

from fastapi.testclient import TestClient

from app.database.session import get_db_context
from app.main import app
from app.repositories.classification_result_repository import ClassificationResultRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_result_repository import ExtractionResultRepository
from app.repositories.ocr_result_repository import OCRResultRepository
from app.workflow.state_machine import (
    WorkflowAction,
    get_required_status,
    get_resulting_status,
    is_comment_required,
    is_role_allowed,
)

client = TestClient(app)

CLEAN_POI_FIELDS = {
    "fiscal_year": "FY2026", "company_name": "Our Co", "currency": "INR",
    "document_date": "2026-06-15", "po_number": "PO-2026-789",
    "invoice_number": "INV-2026-001", "invoice_date": "2026-06-15",
    "invoice_amount": "25000.00", "tax_amount": "4500.00", "net_amount": "20500.00",
    "vendor_code": "V-1001", "vendor_name": "Acme Corp",
}


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "wfuser") -> tuple[str, dict]:
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


def _setup_validated_document(token: str) -> int:
    """Upload + stub OCR + injected classification/extraction + real validate -> VALIDATED."""
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

    validate_response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate", headers=_auth_header(token), json={}
    )
    assert validate_response.status_code == 201
    assert validate_response.json()["is_valid"] is True

    doc_response = client.get(f"/api/v1/documents/{document_id}", headers=_auth_header(token))
    assert doc_response.json()["status"] == "VALIDATED"

    return document_id


# --- State machine ---

def test_request_approval_requires_validated():
    assert get_required_status(WorkflowAction.REQUEST_APPROVAL) == "VALIDATED"
    assert get_resulting_status(WorkflowAction.REQUEST_APPROVAL) == "PENDING_APPROVAL"


def test_approve_requires_pending_approval():
    assert get_required_status(WorkflowAction.APPROVE) == "PENDING_APPROVAL"
    assert get_resulting_status(WorkflowAction.APPROVE) == "APPROVED"


def test_reject_requires_pending_approval():
    assert get_required_status(WorkflowAction.REJECT) == "PENDING_APPROVAL"
    assert get_resulting_status(WorkflowAction.REJECT) == "REJECTED"


def test_analyst_can_request_approval():
    assert is_role_allowed(WorkflowAction.REQUEST_APPROVAL, "FINANCE_ANALYST") is True


def test_analyst_cannot_approve_or_reject():
    assert is_role_allowed(WorkflowAction.APPROVE, "FINANCE_ANALYST") is False
    assert is_role_allowed(WorkflowAction.REJECT, "FINANCE_ANALYST") is False


def test_manager_auditor_admin_can_approve_and_reject():
    for role in ("FINANCE_MANAGER", "AUDITOR", "ADMIN"):
        assert is_role_allowed(WorkflowAction.APPROVE, role) is True
        assert is_role_allowed(WorkflowAction.REJECT, role) is True


def test_reject_requires_comment_approve_does_not():
    assert is_comment_required(WorkflowAction.REJECT) is True
    assert is_comment_required(WorkflowAction.APPROVE) is False
    assert is_comment_required(WorkflowAction.REQUEST_APPROVAL) is False


# --- API integration: happy path ---

def test_full_approval_path_via_api():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfanalyst")
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "wfmanager")

    document_id = _setup_validated_document(analyst_token)

    request_response = client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )
    assert request_response.status_code == 200
    assert request_response.json()["status"] == "PENDING_APPROVAL"

    approve_response = client.post(
        f"/api/v1/workflow/documents/{document_id}/approve",
        headers=_auth_header(manager_token), json={"comment": "Looks good"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "APPROVED"


def test_analyst_cannot_approve_own_document_via_api():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfselfapprove")
    document_id = _setup_validated_document(analyst_token)

    client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )

    response = client.post(
        f"/api/v1/workflow/documents/{document_id}/approve",
        headers=_auth_header(analyst_token), json={},
    )
    assert response.status_code == 403


def test_reject_without_comment_fails():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfnocoment")
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "wfnocoment_mgr")
    document_id = _setup_validated_document(analyst_token)

    client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )

    response = client.post(
        f"/api/v1/workflow/documents/{document_id}/reject",
        headers=_auth_header(manager_token), json={},
    )
    assert response.status_code == 422


def test_reject_with_comment_succeeds():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfreject")
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "wfreject_mgr")
    document_id = _setup_validated_document(analyst_token)

    client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )

    response = client.post(
        f"/api/v1/workflow/documents/{document_id}/reject",
        headers=_auth_header(manager_token), json={"comment": "Vendor code mismatch"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


# --- Resubmission flow ---

def test_cannot_request_approval_directly_from_rejected():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfresub1")
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "wfresub1_mgr")
    document_id = _setup_validated_document(analyst_token)

    client.post(f"/api/v1/workflow/documents/{document_id}/request-approval", headers=_auth_header(analyst_token), json={})
    client.post(
        f"/api/v1/workflow/documents/{document_id}/reject",
        headers=_auth_header(manager_token), json={"comment": "Fix this"},
    )

    # Direct resubmission without re-validating must fail.
    response = client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )
    assert response.status_code == 409


def test_resubmission_succeeds_after_revalidation():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfresub2")
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "wfresub2_mgr")
    document_id = _setup_validated_document(analyst_token)

    client.post(f"/api/v1/workflow/documents/{document_id}/request-approval", headers=_auth_header(analyst_token), json={})
    client.post(
        f"/api/v1/workflow/documents/{document_id}/reject",
        headers=_auth_header(manager_token), json={"comment": "Fix this"},
    )

    # Re-validate (status returns to VALIDATED).
    revalidate_response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate", headers=_auth_header(analyst_token), json={}
    )
    assert revalidate_response.json()["is_valid"] is True

    # Now resubmission should succeed.
    response = client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(analyst_token), json={},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING_APPROVAL"


# --- History ---

def test_workflow_history_records_all_actions_in_order():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfhistory")
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "wfhistory_mgr")
    document_id = _setup_validated_document(analyst_token)

    client.post(f"/api/v1/workflow/documents/{document_id}/request-approval", headers=_auth_header(analyst_token), json={})
    client.post(
        f"/api/v1/workflow/documents/{document_id}/reject",
        headers=_auth_header(manager_token), json={"comment": "Needs fixing"},
    )

    history_response = client.get(
        f"/api/v1/workflow/documents/{document_id}/history", headers=_auth_header(analyst_token)
    )
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 2
    assert history[0]["action"] == "REQUEST_APPROVAL"
    assert history[1]["action"] == "REJECT"
    assert history[1]["comment"] == "Needs fixing"
    # Oldest first.
    assert history[0]["created_at"] <= history[1]["created_at"]


def test_workflow_history_empty_for_untouched_document():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfemptyhist")
    document_id = _setup_validated_document(analyst_token)

    response = client.get(
        f"/api/v1/workflow/documents/{document_id}/history", headers=_auth_header(analyst_token)
    )
    assert response.status_code == 200
    assert response.json() == []


# --- Access scoping ---

def test_workflow_actions_respect_document_access_scoping():
    owner_token, _ = _register_and_login("FINANCE_ANALYST", "wfowner")
    other_token, _ = _register_and_login("FINANCE_ANALYST", "wfother")
    document_id = _setup_validated_document(owner_token)

    response = client.post(
        f"/api/v1/workflow/documents/{document_id}/request-approval",
        headers=_auth_header(other_token), json={},
    )
    assert response.status_code == 403


# --- Invalid transitions ---

def test_approve_on_non_pending_document_fails():
    analyst_token, _ = _register_and_login("FINANCE_ANALYST", "wfbadtrans")
    manager_token, _ = _register_and_login("FINANCE_MANAGER", "wfbadtrans_mgr")
    document_id = _setup_validated_document(analyst_token)
    # Document is VALIDATED, not PENDING_APPROVAL -- approve must fail.

    response = client.post(
        f"/api/v1/workflow/documents/{document_id}/approve",
        headers=_auth_header(manager_token), json={},
    )
    assert response.status_code == 409
