import io
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.database.session import get_db_context
from app.models.document_enums import AuditAction
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.ocr_result_repository import OCRResultRepository

client = TestClient(app)

def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "ocrtest") -> tuple[str, dict]:
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    password = "TestPass123"
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "full_name": f"Test {username}",
            "password": password,
            "role": role,
        },
    )
    assert register_response.status_code == 201, register_response.text
    user = register_response.json()
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"], user

def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

def _upload(token: str, content: bytes, filename: str = "invoice.pdf") -> int:
    response = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]

def _logs_for_document(document_id: int) -> list[dict]:
    with get_db_context() as db:
        repo = AuditLogRepository(db)
        entries = repo.list_for_document(document_id)
        return [{"action": e.action, "details": e.details, "user_id": e.user_id} for e in entries]

def _ocr_result(document_id: int) -> dict | None:
    """Return OCR result as plain dict to avoid detached ORM instance.

    Returns ``None`` if no OCR result exists for the document.
    """
    with get_db_context() as db:
        repo = OCRResultRepository(db)
        ocr = repo.get_latest_for_document(document_id)
        if ocr is None:
            return None
        return {
            "id": ocr.id,
            "document_id": ocr.document_id,
            "engine_name": ocr.engine_name,
            "full_text": ocr.full_text,
            "average_confidence": ocr.average_confidence,
            "page_count": ocr.page_count,
        }

def test_ocr_audit_success():
    token, user = _register_and_login()
    pdf_path = "C:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/invoice_51109301.pdf"
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    document_id = _upload(token, pdf_bytes, "invoice_51109301.pdf")
    response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token),
        json={"engine": "easyocr"},
    )
    assert response.status_code == 201, response.text
    ocr = _ocr_result(document_id)
    assert ocr is not None, "OCRResult missing"
    assert ocr["full_text"].strip() != "", "OCRResult.full_text empty"
    logs = _logs_for_document(document_id)
    started = [l for l in logs if l["action"] == AuditAction.OCR_STARTED.value]
    completed = [l for l in logs if l["action"] == AuditAction.OCR_COMPLETED.value]
    assert len(started) == 1, f"Expected 1 OCR_STARTED, got {len(started)}"
    assert len(completed) == 1, f"Expected 1 OCR_COMPLETED, got {len(completed)}"
    assert started[0]["details"]["engine"] == "easyocr"
    assert completed[0]["details"]["engine"] == "easyocr"
    assert completed[0]["details"]["status"] == "OCR_COMPLETED"

def test_ocr_audit_failure():
    token, user = _register_and_login()
    pdf_path = "C:/Users/conanferreira/Desktop/PROJECT-BLACKBOX/EFDI/invoice_51109301.pdf"
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    document_id = _upload(token, pdf_bytes, "corrupt.pdf")
    response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token),
        json={"engine": "nonexistent_engine"},
    )
    assert response.status_code in (400, 422, 500), f"Unexpected status {response.status_code}"
    ocr = _ocr_result(document_id)
    assert ocr is None, "OCRResult should not exist on failure"
    logs = _logs_for_document(document_id)
    started = [l for l in logs if l["action"] == AuditAction.OCR_STARTED.value]
    failed = [l for l in logs if l["action"] == AuditAction.OCR_FAILED.value]
    assert len(started) == 1, f"Expected 1 OCR_STARTED, got {len(started)}"
    assert len(failed) == 1, f"Expected 1 OCR_FAILED, got {len(failed)}"
    assert failed[0]["details"]["engine"] == "nonexistent_engine"
    assert "error" in failed[0]["details"]
