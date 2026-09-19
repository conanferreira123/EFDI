"""
Phase 7 verification tests: validation engine.

Covers required-field, date-format, amount-format, tax-ID-format,
duplicate-detection, and business-rule validators individually, the
combined engine, and full API integration including the
extract-before-validate prerequisite and Document.status transitions.
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
from app.validation.business_rules import validate_business_rules
from app.validation.duplicate_detection import validate_duplicate_document
from app.validation.field_validators import (
    validate_amount_fields,
    validate_date_fields,
    validate_required_fields,
    validate_tax_id_format,
)
from app.validation.mandatory_fields import get_mandatory_fields

client = TestClient(app)


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "valuser") -> str:
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
    login_response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _minimal_pdf_bytes(salt: bytes = b"") -> bytes:
    """
    `salt` lets tests create distinct file contents (and therefore
    distinct file_hash values) when needed, since duplicate detection
    is hash-based.
    """
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF" + salt
    )


def _upload(token: str, filename: str, content: bytes) -> int:
    response = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _run_stub_ocr(token: str, document_id: int) -> None:
    client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token), json={"engine": "stub"},
    )


def _inject_ocr_text(document_id: int, text: str) -> None:
    with get_db_context() as db:
        repo = OCRResultRepository(db)
        repo.create(
            document_id=document_id, engine_name="test_injection", page_count=1,
            full_text=text, average_confidence=0.95, raw_blocks=[], processing_time_ms=0,
        )


def _inject_classification(document_id: int, predicted_type: str) -> None:
    with get_db_context() as db:
        repo = ClassificationResultRepository(db)
        repo.create(
            document_id=document_id, predicted_type=predicted_type, confidence=0.9,
            engine_name="test_injection", signals=[], scores_by_type={},
        )


def _inject_extraction(document_id: int, document_type: str, fields: dict) -> None:
    """
    Directly insert an ExtractionResult with hand-crafted fields, so
    validation tests can target specific field combinations
    deterministically without depending on extraction-pattern accuracy.
    """
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


def _setup_pipeline(token: str, document_type: str, fields: dict, *, salt: bytes = b"") -> int:
    """
    Upload + stub OCR + injected classification + injected extraction,
    ready for validation.

    NOTE: classification and extraction are injected directly via their
    repositories (not run through the real classifier/extractor, since
    we want deterministic field values for these tests) but
    Document.status and Document.document_type are updated explicitly
    here to match what the real ClassificationService/ExtractionService
    would have done -- otherwise status stays at OCR_COMPLETED and
    later assertions about status transitions become meaningless.
    """
    unique_salt = salt or str(uuid.uuid4()).encode()
    document_id = _upload(token, "test.pdf", _minimal_pdf_bytes(unique_salt))
    _run_stub_ocr(token, document_id)
    _inject_classification(document_id, document_type)
    _inject_extraction(document_id, document_type, fields)

    with get_db_context() as db:
        doc_repo = DocumentRepository(db)
        document = doc_repo.get_by_id(document_id)
        document.document_type = document_type
        document.status = "EXTRACTED"
        db.commit()

    return document_id


CLEAN_POI_FIELDS = {
    "currency": "INR", "po_number": "PO-2026-789",
    "invoice_number": "INV-2026-001", "invoice_date": "2026-06-15",
    "grand_total_amount": "25000.00", "total_tax_amount": "4500.00", "subtotal_net_amount": "20500.00",
    "vendor_code": "V-1001", "seller_name": "Acme Corp", "buyer_name": "Our Co",
}


# --- Mandatory fields map sanity ---

def test_mandatory_fields_only_reference_valid_schema_keys():
    from app.extraction.field_schemas import get_field_keys
    from app.validation.mandatory_fields import MANDATORY_FIELDS

    for doc_type, mandatory_keys in MANDATORY_FIELDS.items():
        valid_keys = set(get_field_keys(doc_type))
        assert mandatory_keys <= valid_keys, f"{doc_type} has invalid mandatory keys"


def test_get_mandatory_fields_includes_common_and_specific():
    mandatory = get_mandatory_fields("POI")
    assert "currency" in mandatory  # common
    assert "po_number" in mandatory  # POI-specific


# --- Required field validator ---

def test_required_field_validator_flags_missing_mandatory_field():
    fields = {k: {"value": v} for k, v in CLEAN_POI_FIELDS.items()}
    fields["invoice_number"] = {"value": None}
    issues = validate_required_fields(fields, "POI")
    assert any(i.field_key == "invoice_number" for i in issues)


def test_required_field_validator_passes_when_all_present():
    fields = {k: {"value": v} for k, v in CLEAN_POI_FIELDS.items()}
    issues = validate_required_fields(fields, "POI")
    assert issues == []


# --- Date format validator ---

def test_date_validator_flags_invalid_date():
    fields = {"invoice_date": {"value": "2026-13-99"}}
    issues = validate_date_fields(fields, "POI")
    assert len(issues) == 1
    assert issues[0].field_key == "invoice_date"


def test_date_validator_passes_valid_iso_date():
    fields = {"invoice_date": {"value": "2026-06-15"}}
    assert validate_date_fields(fields, "POI") == []


def test_date_validator_skips_missing_field():
    assert validate_date_fields({"invoice_date": {"value": None}}, "POI") == []


# --- Amount format validator ---

def test_amount_validator_flags_negative_amount():
    fields = {"grand_total_amount": {"value": "-100.00"}}
    issues = validate_amount_fields(fields, "POI")
    assert len(issues) == 1


def test_amount_validator_passes_valid_amount():
    fields = {"grand_total_amount": {"value": "25000.00"}}
    assert validate_amount_fields(fields, "POI") == []


# --- Tax-ID format validator ---

def test_tax_id_validator_passes_valid_gst_format():
    fields = {"vendor_code": {"value": "27AAAAA0000A1Z5"}}
    assert validate_tax_id_format(fields, "POI") == []


def test_tax_id_validator_flags_malformed_gst_looking_value():
    fields = {"vendor_code": {"value": "27INVALIDFORMAT123"}}
    issues = validate_tax_id_format(fields, "POI")
    assert len(issues) == 1
    assert issues[0].severity.value == "WARNING"


def test_tax_id_validator_ignores_ordinary_short_codes():
    fields = {"vendor_code": {"value": "V-1001"}}
    assert validate_tax_id_format(fields, "POI") == []


# --- Business rules ---

def test_business_rule_poi_amount_mismatch_is_warning():
    fields = {"grand_total_amount": {"value": "25000.00"}, "total_tax_amount": {"value": "4500.00"}, "subtotal_net_amount": {"value": "15000.00"}}
    issues = validate_business_rules(fields, "POI")
    assert len(issues) == 1
    assert issues[0].severity.value == "WARNING"


def test_business_rule_jer_imbalance_is_error():
    fields = {"debit_amount": {"value": "5000.00"}, "credit_amount": {"value": "4000.00"}}
    issues = validate_business_rules(fields, "JER")
    assert len(issues) == 1
    assert issues[0].severity.value == "ERROR"


def test_business_rule_ima_travel_dates_reversed_is_error():
    fields = {"travel_start_date": {"value": "2026-06-20"}, "travel_end_date": {"value": "2026-06-10"}}
    issues = validate_business_rules(fields, "IMA")
    assert len(issues) == 1
    assert issues[0].severity.value == "ERROR"


def test_business_rule_lca_expiry_before_issue_is_error():
    fields = {"issue_date": {"value": "2026-06-20"}, "expiry_date": {"value": "2026-06-10"}}
    issues = validate_business_rules(fields, "LCA")
    assert len(issues) == 1


def test_business_rule_dpr_advance_percentage_out_of_range():
    fields = {"advance_percentage": {"value": "150"}}
    issues = validate_business_rules(fields, "DPR")
    assert len(issues) == 1


def test_business_rules_skip_silently_when_fields_missing():
    assert validate_business_rules({}, "POI") == []
    assert validate_business_rules({}, "JER") == []


# --- Duplicate detection (includes regression test for the
#     MultipleResultsFound bug found during live testing) ---

def test_duplicate_detection_flags_identical_file():
    token = _register_and_login(prefix="dupuser")
    shared_content = _minimal_pdf_bytes(f"shared-{uuid.uuid4()}".encode())

    doc_id_1 = _upload(token, "first.pdf", shared_content)
    doc_id_2 = _upload(token, "second.pdf", shared_content)

    with get_db_context() as db:
        doc_repo = DocumentRepository(db)
        document_2 = doc_repo.get_by_id(doc_id_2)
        issues = validate_duplicate_document(db, document_2)

    assert len(issues) == 1
    assert str(doc_id_1) in issues[0].message


def test_duplicate_detection_handles_three_or_more_identical_files():
    """
    Regression test: uploading the SAME content 3+ times must not
    crash get_by_hash()/get_all_by_hash() with MultipleResultsFound.
    This reproduces a real bug found during manual testing of this
    phase, where scalar_one_or_none() raised when more than one
    existing document shared a hash.
    """
    token = _register_and_login(prefix="dup3user")
    shared_content = _minimal_pdf_bytes(f"triple-{uuid.uuid4()}".encode())

    doc_id_1 = _upload(token, "a.pdf", shared_content)
    doc_id_2 = _upload(token, "b.pdf", shared_content)
    doc_id_3 = _upload(token, "c.pdf", shared_content)

    with get_db_context() as db:
        doc_repo = DocumentRepository(db)
        document_3 = doc_repo.get_by_id(doc_id_3)
        # Must not raise sqlalchemy.exc.MultipleResultsFound.
        issues = validate_duplicate_document(db, document_3)

    assert len(issues) == 1
    assert str(doc_id_1) in issues[0].message  # reports the EARLIEST match


def test_duplicate_detection_passes_for_unique_file():
    token = _register_and_login(prefix="uniqueuser")
    unique_content = _minimal_pdf_bytes(str(uuid.uuid4()).encode())
    doc_id = _upload(token, "unique.pdf", unique_content)

    with get_db_context() as db:
        doc_repo = DocumentRepository(db)
        document = doc_repo.get_by_id(doc_id)
        issues = validate_duplicate_document(db, document)

    assert issues == []


# --- API integration ---

def test_validate_requires_extraction_first():
    token = _register_and_login(prefix="valnoext")
    document_id = _upload(token, "noext.pdf", _minimal_pdf_bytes(b"noext"))
    _run_stub_ocr(token, document_id)

    response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 422


def test_validate_clean_document_passes_and_advances_status():
    token = _register_and_login(prefix="valclean")
    document_id = _setup_pipeline(token, "POI", CLEAN_POI_FIELDS)

    response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_valid"] is True
    assert body["error_count"] == 0

    doc_response = client.get(f"/api/v1/documents/{document_id}", headers=_auth_header(token))
    assert doc_response.json()["status"] == "VALIDATED"


def test_validate_broken_document_fails_and_does_not_advance_status():
    broken_fields = dict(CLEAN_POI_FIELDS)
    broken_fields["invoice_number"] = None  # remove a mandatory field

    token = _register_and_login(prefix="valbroken")
    document_id = _setup_pipeline(token, "POI", broken_fields)

    response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["is_valid"] is False
    assert body["error_count"] >= 1

    doc_response = client.get(f"/api/v1/documents/{document_id}", headers=_auth_header(token))
    assert doc_response.json()["status"] == "EXTRACTED"  # did NOT advance to VALIDATED


def test_get_latest_validation_result():
    token = _register_and_login(prefix="valget")
    document_id = _setup_pipeline(token, "POI", CLEAN_POI_FIELDS)
    client.post(f"/api/v1/validation/documents/{document_id}/validate", headers=_auth_header(token), json={})

    response = client.get(
        f"/api/v1/validation/documents/{document_id}/result", headers=_auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["is_valid"] is True


def test_get_validation_result_before_any_run_returns_404():
    token = _register_and_login(prefix="valnorun")
    document_id = _setup_pipeline(token, "POI", CLEAN_POI_FIELDS)

    response = client.get(
        f"/api/v1/validation/documents/{document_id}/result", headers=_auth_header(token)
    )
    assert response.status_code == 404


def test_list_validation_results_shows_multiple_runs():
    token = _register_and_login(prefix="valmulti")
    document_id = _setup_pipeline(token, "POI", CLEAN_POI_FIELDS)

    client.post(f"/api/v1/validation/documents/{document_id}/validate", headers=_auth_header(token), json={})
    client.post(f"/api/v1/validation/documents/{document_id}/validate", headers=_auth_header(token), json={})

    response = client.get(
        f"/api/v1/validation/documents/{document_id}/results", headers=_auth_header(token)
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_validate_respects_document_access_scoping():
    owner_token = _register_and_login(prefix="valowner")
    other_token = _register_and_login(prefix="valother")
    document_id = _setup_pipeline(owner_token, "POI", CLEAN_POI_FIELDS)

    response = client.post(
        f"/api/v1/validation/documents/{document_id}/validate",
        headers=_auth_header(other_token), json={},
    )
    assert response.status_code == 403
