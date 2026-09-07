"""
Phase 6 verification tests: data extraction.

Field schemas and document types reflect the client-provided
specification (POI, NPO, DPR, IMA, MSI, PSI, JER, BKA, LCA), not
generic placeholders. See app/extraction/field_schemas.py for the full
per-type field list and app/extraction/type_extractors.py for the
extraction logic being tested here.
"""
import io
import uuid

from fastapi.testclient import TestClient

from app.core.exceptions import ValidationFailedException
from app.database.session import get_db_context
from app.extraction.factory import get_extraction_engine
from app.extraction.field_schemas import get_field_keys, get_full_field_schema
from app.extraction.primitives import (
    extract_amount_field,
    extract_by_labels,
    extract_date_field,
    normalize_amount,
    normalize_date,
)
from app.main import app
from app.repositories.classification_result_repository import ClassificationResultRepository
from app.repositories.ocr_result_repository import OCRResultRepository

client = TestClient(app)

REALISTIC_POI_TEXT = """
TAX INVOICE
Company Name: Our Company Pvt Ltd
Company Code: CC-100
Fiscal Year: FY2026
Currency: INR
PO Number: PO-2026-789
GRN Number: GRN-445
Invoice Number: INV-2026-001
Invoice Date: 15-06-2026
Invoice Amount: 25,000.00
Tax Amount: 4,500.00
Net Amount: 20,500.00
Vendor Code: V-1001
Vendor Name: Acme Corporation
Payment Terms: Net 30
"""

REALISTIC_BKA_TEXT = """
BANK ADVICE
Bank Name: ICICI Bank
Account Number: 1234567890123
Advice Number: ADV-2026-01
Advice Date: 10-06-2026
Transaction Amount: 75,000.00
Transaction Type: Credit
Value Date: 11-06-2026
"""


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "extuser") -> str:
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

    login_response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _minimal_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF"
    )


def _upload_and_run_stub_ocr(token: str, filename: str = "test.pdf") -> int:
    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": (filename, io.BytesIO(_minimal_pdf_bytes()), "application/pdf")},
    )
    document_id = upload_response.json()["id"]
    client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token), json={"engine": "stub"},
    )
    return document_id


def _inject_ocr_text(document_id: int, text: str) -> None:
    with get_db_context() as db:
        repo = OCRResultRepository(db)
        repo.create(
            document_id=document_id, engine_name="test_injection", page_count=1,
            full_text=text, average_confidence=0.95, raw_blocks=[], processing_time_ms=0,
        )


def _inject_classification(document_id: int, predicted_type: str) -> None:
    """
    Directly insert a ClassificationResult, bypassing the classifier,
    so extraction tests can target a specific document_type
    deterministically without depending on classification accuracy.
    """
    with get_db_context() as db:
        repo = ClassificationResultRepository(db)
        repo.create(
            document_id=document_id, predicted_type=predicted_type, confidence=0.9,
            engine_name="test_injection", signals=[], scores_by_type={},
        )


def _setup_classified_document(token: str, document_type: str, ocr_text: str) -> int:
    document_id = _upload_and_run_stub_ocr(token)
    _inject_ocr_text(document_id, ocr_text)
    _inject_classification(document_id, document_type)
    return document_id


# --- Field schema ---

def test_field_schema_covers_all_nine_types():
    for doc_type in ["POI", "NPO", "DPR", "IMA", "MSI", "PSI", "JER", "BKA", "LCA"]:
        fields = get_full_field_schema(doc_type)
        assert len(fields) > 0
        keys = get_field_keys(doc_type)
        assert "document_id" in keys  # common field present
        assert len(keys) == len(set(keys))  # no duplicate keys


def test_unknown_type_returns_only_common_fields():
    fields = get_full_field_schema("UNKNOWN")
    keys = [f.key for f in fields]
    assert keys == [f.key for f in get_full_field_schema("UNKNOWN")]  # stable
    # UNKNOWN has no type-specific entry in DOCUMENT_TYPE_FIELDS, so it
    # should resolve to exactly the common fields.
    from app.extraction.field_schemas import COMMON_FIELDS
    assert len(fields) == len(COMMON_FIELDS)


# --- Primitives ---

def test_extract_by_labels_finds_value():
    field = extract_by_labels(REALISTIC_POI_TEXT, ["Invoice Number"])
    assert field.value == "INV-2026-001"
    assert field.is_found


def test_extract_by_labels_returns_none_when_absent():
    field = extract_by_labels(REALISTIC_POI_TEXT, ["Nonexistent Field Xyz"])
    assert field.value is None
    assert field.confidence == 0.0
    assert not field.is_found


def test_normalize_date_handles_multiple_formats():
    assert normalize_date("15-06-2026") == "2026-06-15"
    assert normalize_date("2026-06-15") == "2026-06-15"
    assert normalize_date("15/06/2026") == "2026-06-15"
    assert normalize_date("not a date at all") is None
    assert normalize_date(None) is None


def test_normalize_amount_strips_currency_and_commas():
    assert normalize_amount("Rs. 25,000.00") == "25000.00"
    assert normalize_amount("25000.00") == "25000.00"
    assert normalize_amount("no digits here") is None
    assert normalize_amount(None) is None


def test_extract_date_field_normalizes_to_iso():
    field = extract_date_field(REALISTIC_POI_TEXT, ["Invoice Date"])
    assert field.value == "2026-06-15"
    assert field.is_found


def test_extract_amount_field_strips_commas():
    field = extract_amount_field(REALISTIC_POI_TEXT, ["Invoice Amount"])
    assert field.value == "25000.00"


# --- Rule-based extraction engine: per-type correctness ---

def test_extracts_poi_fields_correctly():
    engine = get_extraction_engine("rule_based")
    result = engine.extract(REALISTIC_POI_TEXT, "POI")

    assert result.fields["po_number"].value == "PO-2026-789"
    assert result.fields["grn_number"].value == "GRN-445"
    assert result.fields["invoice_number"].value == "INV-2026-001"
    assert result.fields["invoice_date"].value == "2026-06-15"
    assert result.fields["invoice_amount"].value == "25000.00"
    assert result.fields["tax_amount"].value == "4500.00"
    assert result.fields["net_amount"].value == "20500.00"
    assert result.fields["vendor_code"].value == "V-1001"
    assert result.fields["vendor_name"].value == "Acme Corporation"
    assert result.fields["payment_terms"].value == "Net 30"
    # Fields genuinely absent from the sample text must be null, not guessed.
    assert result.fields["srn_number"].value is None
    assert result.fields["location_code"].value is None


def test_extracts_bka_fields_correctly():
    engine = get_extraction_engine("rule_based")
    result = engine.extract(REALISTIC_BKA_TEXT, "BKA")

    assert result.fields["bank_name"].value == "ICICI Bank"
    assert result.fields["account_number"].value == "1234567890123"
    assert result.fields["advice_number"].value == "ADV-2026-01"
    assert result.fields["advice_date"].value == "2026-06-10"
    assert result.fields["transaction_amount"].value == "75000.00"
    assert result.fields["value_date"].value == "2026-06-11"


def test_extraction_never_fabricates_values_for_empty_text():
    engine = get_extraction_engine("rule_based")
    result = engine.extract("", "POI")
    assert all(not f.is_found for f in result.fields.values())
    assert result.overall_confidence == 0.0


def test_extraction_for_unknown_type_returns_no_fields():
    engine = get_extraction_engine("rule_based")
    result = engine.extract("some random text", "UNKNOWN")
    assert result.fields == {}


def test_extraction_for_dpr_type():
    engine = get_extraction_engine("rule_based")
    text = "DOWN PAYMENT REQUEST\nRequest Number: DPR-2026-001\nPO Number: PO-2026-500\nRequested Amount: 100000.00\nAdvance Percentage: 30%"
    result = engine.extract(text, "DPR")
    assert result.fields["request_number"].value == "DPR-2026-001"
    assert result.fields["po_number"].value == "PO-2026-500"
    assert result.fields["requested_amount"].value == "100000.00"


def test_extraction_for_lca_type():
    engine = get_extraction_engine("rule_based")
    text = "LETTER OF CREDIT\nLC Number: LC-2026-099\nIssuing Bank: Standard Chartered\nBeneficiary Name: Export Co\nExpiry Date: 31-12-2026"
    result = engine.extract(text, "LCA")
    assert result.fields["lc_number"].value == "LC-2026-099"
    assert result.fields["issuing_bank"].value == "Standard Chartered"
    assert result.fields["beneficiary_name"].value == "Export Co"
    assert result.fields["expiry_date"].value == "2026-12-31"


# --- Factory ---

def test_factory_returns_rule_based_engine():
    engine = get_extraction_engine("rule_based")
    assert engine.name == "rule_based"


def test_factory_rejects_unknown_engine():
    import pytest
    with pytest.raises(ValidationFailedException):
        get_extraction_engine("not_a_real_engine")


# --- API integration ---

def test_extract_requires_ocr_first():
    token = _register_and_login(prefix="extnoocr")
    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": ("noocr.pdf", io.BytesIO(_minimal_pdf_bytes()), "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    response = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 422


def test_extract_requires_classification_first():
    token = _register_and_login(prefix="extnocls")
    document_id = _upload_and_run_stub_ocr(token)

    response = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 422


def test_extract_with_classified_poi_document_succeeds():
    token = _register_and_login(prefix="extpoi")
    document_id = _setup_classified_document(token, "POI", REALISTIC_POI_TEXT)

    response = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document_type"] == "POI"
    assert body["fields"]["po_number"]["value"] == "PO-2026-789"
    assert body["fields_found_count"] > 0


def test_extract_advances_document_status_to_extracted():
    token = _register_and_login(prefix="extstatus")
    document_id = _setup_classified_document(token, "BKA", REALISTIC_BKA_TEXT)

    client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=_auth_header(token), json={},
    )

    document_response = client.get(
        f"/api/v1/documents/{document_id}", headers=_auth_header(token)
    )
    assert document_response.json()["status"] == "EXTRACTED"


def test_extract_for_unknown_classification_succeeds_with_empty_fields():
    token = _register_and_login(prefix="extunknown")
    document_id = _setup_classified_document(token, "UNKNOWN", "irrelevant text")

    response = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 201
    assert response.json()["fields"] == {}


def test_get_latest_extraction_result():
    token = _register_and_login(prefix="extget")
    document_id = _setup_classified_document(token, "JER", "JOURNAL ENTRY\nGL Account Code: 4000\nDebit: 500\nCredit: 500")

    client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=_auth_header(token), json={},
    )

    response = client.get(
        f"/api/v1/extraction/documents/{document_id}/result", headers=_auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["document_type"] == "JER"


def test_get_extraction_result_before_any_run_returns_404():
    token = _register_and_login(prefix="extnorun")
    document_id = _upload_and_run_stub_ocr(token)

    response = client.get(
        f"/api/v1/extraction/documents/{document_id}/result", headers=_auth_header(token)
    )
    assert response.status_code == 404


def test_list_extraction_results_shows_multiple_runs():
    token = _register_and_login(prefix="extmulti")
    document_id = _setup_classified_document(token, "MSI", "MSI INVOICE\nCustomer Code: C-1\nCustomer Name: Test")

    client.post(f"/api/v1/extraction/documents/{document_id}/extract", headers=_auth_header(token), json={})
    client.post(f"/api/v1/extraction/documents/{document_id}/extract", headers=_auth_header(token), json={})

    response = client.get(
        f"/api/v1/extraction/documents/{document_id}/results", headers=_auth_header(token)
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_manually_correct_a_null_field():
    token = _register_and_login(prefix="extcorrect")
    document_id = _setup_classified_document(token, "POI", REALISTIC_POI_TEXT)

    client.post(f"/api/v1/extraction/documents/{document_id}/extract", headers=_auth_header(token), json={})

    response = client.patch(
        f"/api/v1/extraction/documents/{document_id}/fields/location_code",
        headers=_auth_header(token), json={"value": "LOC-MUM-01"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["fields"]["location_code"]["value"] == "LOC-MUM-01"
    assert body["fields"]["location_code"]["confidence"] == 1.0


def test_correcting_invalid_field_key_returns_422():
    token = _register_and_login(prefix="extbadfield")
    document_id = _setup_classified_document(token, "POI", REALISTIC_POI_TEXT)
    client.post(f"/api/v1/extraction/documents/{document_id}/extract", headers=_auth_header(token), json={})

    response = client.patch(
        f"/api/v1/extraction/documents/{document_id}/fields/totally_fake_field",
        headers=_auth_header(token), json={"value": "x"},
    )
    assert response.status_code == 422


def test_extract_respects_document_access_scoping():
    owner_token = _register_and_login(prefix="extowner")
    other_token = _register_and_login(prefix="extother")
    document_id = _setup_classified_document(owner_token, "POI", REALISTIC_POI_TEXT)

    response = client.post(
        f"/api/v1/extraction/documents/{document_id}/extract",
        headers=_auth_header(other_token), json={},
    )
    assert response.status_code == 403
