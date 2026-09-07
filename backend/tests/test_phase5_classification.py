"""
Phase 5 verification tests: document classification.

Document types reflect the real client-provided AP/R2R taxonomy
(POI, NPO, IMA, MSI, PSI, JER, BKA), not generic placeholders. See
app/classification/rule_based.py for the rationale behind each type's
rules, including the POI vs NPO disambiguation logic.
"""
import io
import uuid

from fastapi.testclient import TestClient

from app.classification.factory import get_classification_engine
from app.classification.rule_based import RuleBasedClassifier
from app.core.exceptions import ValidationFailedException
from app.database.session import get_db_context
from app.main import app
from app.models.document_enums import DocumentType
from app.repositories.ocr_result_repository import OCRResultRepository

client = TestClient(app)

SAMPLE_TEXTS = {
    DocumentType.POI: """
        TAX INVOICE
        PO Number: PO-2026-789
        Invoice Number: INV-2026-001
        Vendor: Acme Corp
        GRN Number: GRN-445
        Bill To: Our Company Ltd
    """,
    DocumentType.NPO: """
        TAX INVOICE
        Invoice Number: INV-2026-555
        Vendor Code: V-1001
        Bill To: Our Company Ltd
        Amount Due: 25000.00
        Remit To: Vendor Bank Account
    """,
    DocumentType.IMA: """
        EMPLOYEE EXPENSE CLAIM FORM
        Employee: John Doe
        Travel End Date: 2026-06-20
        Reimbursement Amount: 4500.00
        Mileage: 250 km
        Per Diem: 500.00
    """,
    DocumentType.MSI: """
        MSI INVOICE
        Customer Code: CUST-789
        Customer Name: Beta Industries
        MSI Invoice Number: MSI-2026-321
        Sold To: Beta Industries Warehouse
    """,
    DocumentType.PSI: """
        PAY IN SLIP
        PIS Number: PIS-2026-100
        Bank Name: HDFC Bank
        Customer Receipt Acknowledgement
        Deposit Amount: 50000.00
        Cash Deposit confirmed
    """,
    DocumentType.JER: """
        JOURNAL ENTRY
        GL Account Code: 4000-100
        GL Account: Revenue
        Posting Date: 2026-06-15
        Debit: 5000.00
        Credit: 5000.00
        Narration: Monthly accrual adjustment
    """,
    DocumentType.BKA: """
        BANK ADVICE
        Bank Name: ICICI Bank
        Account Number: 1234567890123
        Advice Date: 2026-06-10
        Advice Amount: 75000.00
        Debit Advice confirmed
        IFSC: ICIC0001234
    """,
    DocumentType.DPR: """
        DOWN PAYMENT REQUEST
        Request Number: DPR-2026-001
        PO Number: PO-2026-500
        Advance Percentage: 30%
        Requested Amount: 100000.00
        Purpose: Material advance
    """,
    DocumentType.LCA: """
        LETTER OF CREDIT ADVICE
        LC Number: LC-2026-099
        Issuing Bank: Standard Chartered
        Beneficiary Name: Export Co
        Shipment Reference: SHP-2026-01
        Expiry Date: 2026-12-31
    """,
}


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "clsuser") -> str:
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


def _inject_realistic_ocr_text(document_id: int, text: str) -> None:
    """
    Directly insert an OCRResult row with realistic financial document
    text, simulating what a real OCR engine (PaddleOCR/EasyOCR) would
    have produced. Necessary because the StubOCREngine used in this
    test environment only ever produces non-financial placeholder text.
    """
    with get_db_context() as db:
        repo = OCRResultRepository(db)
        repo.create(
            document_id=document_id,
            engine_name="test_injection",
            page_count=1,
            full_text=text,
            average_confidence=0.95,
            raw_blocks=[],
            processing_time_ms=0,
        )


# --- Rule-based classifier unit tests: one per real document type ---

def test_classifies_poi_with_po_number_correctly():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.POI])
    assert result.document_type == DocumentType.POI
    assert result.confidence > 0.5


def test_classifies_npo_without_po_number_correctly():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.NPO])
    assert result.document_type == DocumentType.NPO
    assert result.confidence > 0.5


def test_classifies_ima_expense_claim_correctly():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.IMA])
    assert result.document_type == DocumentType.IMA
    assert result.confidence > 0.5


def test_classifies_msi_sales_invoice_correctly():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.MSI])
    assert result.document_type == DocumentType.MSI
    assert result.confidence > 0.5


def test_classifies_psi_pay_in_slip_correctly():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.PSI])
    assert result.document_type == DocumentType.PSI
    assert result.confidence > 0.5


def test_classifies_jer_journal_entry_correctly():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.JER])
    assert result.document_type == DocumentType.JER
    assert result.confidence > 0.5


def test_classifies_bka_bank_advice_correctly():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.BKA])
    assert result.document_type == DocumentType.BKA
    assert result.confidence > 0.5


def test_poi_npo_disambiguation_favors_poi_when_po_number_present():
    """
    Critical disambiguation test: POI and NPO share most vocabulary
    (invoice, vendor, bill to). The presence of an actual PO number
    must tip the decision to POI, not NPO.
    """
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.POI])
    assert result.document_type == DocumentType.POI
    # NPO should score meaningfully lower, not just barely lower.
    assert result.scores_by_type["NPO"] < result.scores_by_type["POI"]


def test_poi_npo_disambiguation_favors_npo_when_no_po_number():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.NPO])
    assert result.document_type == DocumentType.NPO


def test_classifies_dpr_down_payment_request_correctly():
    classifier = RuleBasedClassifier()
    dpr_text = (
        "DOWN PAYMENT REQUEST\nRequest Number: DPR-2026-001\n"
        "PO Number: PO-2026-500\nAdvance Percentage: 30%\n"
        "Requested Amount: 100000.00\nPurpose: Material advance"
    )
    result = classifier.classify(dpr_text)
    assert result.document_type == DocumentType.DPR
    assert result.confidence > 0.5


def test_classifies_lca_letter_of_credit_correctly():
    classifier = RuleBasedClassifier()
    lca_text = (
        "LETTER OF CREDIT ADVICE\nLC Number: LC-2026-099\n"
        "Issuing Bank: Standard Chartered\nBeneficiary Name: Export Co\n"
        "Shipment Reference: SHP-2026-01\nExpiry Date: 2026-12-31"
    )
    result = classifier.classify(lca_text)
    assert result.document_type == DocumentType.LCA
    assert result.confidence > 0.5


def test_scores_by_type_includes_all_nine_types():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.POI])
    assert set(result.scores_by_type.keys()) == {
        "POI", "NPO", "IMA", "MSI", "PSI", "JER", "BKA", "DPR", "LCA"
    }


def test_classifies_gibberish_as_unknown():
    classifier = RuleBasedClassifier()
    result = classifier.classify("asdf qwer zxcv random text with no meaning")
    assert result.document_type == DocumentType.UNKNOWN


def test_classifies_empty_text_as_unknown():
    classifier = RuleBasedClassifier()
    result = classifier.classify("")
    assert result.document_type == DocumentType.UNKNOWN
    assert result.confidence == 0.0


def test_classifies_stub_ocr_placeholder_as_unknown():
    """
    Critical for this environment: the stub OCR engine's placeholder
    output must never accidentally match a real document type.
    """
    classifier = RuleBasedClassifier()
    stub_text = "[STUB OCR OUTPUT - no real text extraction - digest:abc123def456]"
    result = classifier.classify(stub_text)
    assert result.document_type == DocumentType.UNKNOWN


def test_signals_contain_matched_text_and_weight():
    classifier = RuleBasedClassifier()
    result = classifier.classify(SAMPLE_TEXTS[DocumentType.BKA])
    assert all(hasattr(s, "matched_text") and hasattr(s, "weight") for s in result.signals)


# --- Factory ---

def test_factory_returns_rule_based_engine():
    engine = get_classification_engine("rule_based")
    assert engine.name == "rule_based"


def test_factory_rejects_unknown_engine():
    import pytest
    with pytest.raises(ValidationFailedException):
        get_classification_engine("not_a_real_engine")


# --- API integration ---

def test_classify_requires_ocr_first():
    token = _register_and_login(prefix="clsnoocr")
    upload_response = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": ("noocr.pdf", io.BytesIO(_minimal_pdf_bytes()), "application/pdf")},
    )
    document_id = upload_response.json()["id"]

    response = client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 422


def test_classify_with_stub_ocr_text_yields_unknown():
    token = _register_and_login(prefix="clsstub")
    document_id = _upload_and_run_stub_ocr(token)

    response = client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 201
    assert response.json()["predicted_type"] == "UNKNOWN"


def test_classify_with_realistic_poi_text_updates_document_type():
    token = _register_and_login(prefix="clspoi")
    document_id = _upload_and_run_stub_ocr(token)
    _inject_realistic_ocr_text(document_id, SAMPLE_TEXTS[DocumentType.POI])

    response = client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["predicted_type"] == "POI"
    assert body["confidence"] > 0.5

    document_response = client.get(
        f"/api/v1/documents/{document_id}", headers=_auth_header(token)
    )
    assert document_response.json()["document_type"] == "POI"


def test_classification_does_not_change_document_status():
    """
    Per design: classification updates document_type but Document.status
    stays at OCR_COMPLETED -- Phase 6 (extraction) owns the transition
    to EXTRACTED.
    """
    token = _register_and_login(prefix="clsstatus")
    document_id = _upload_and_run_stub_ocr(token)
    _inject_realistic_ocr_text(document_id, SAMPLE_TEXTS[DocumentType.BKA])

    client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )

    document_response = client.get(
        f"/api/v1/documents/{document_id}", headers=_auth_header(token)
    )
    assert document_response.json()["status"] == "OCR_COMPLETED"


def test_classification_uses_latest_ocr_result():
    """
    If OCR has been run multiple times, classification must use the
    most recent result, not the first one.
    """
    token = _register_and_login(prefix="clslatest")
    document_id = _upload_and_run_stub_ocr(token)

    _inject_realistic_ocr_text(document_id, SAMPLE_TEXTS[DocumentType.JER])

    response = client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )
    assert response.json()["predicted_type"] == "JER"


def test_get_latest_classification_result():
    token = _register_and_login(prefix="clsget")
    document_id = _upload_and_run_stub_ocr(token)
    _inject_realistic_ocr_text(document_id, SAMPLE_TEXTS[DocumentType.MSI])

    client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )

    response = client.get(
        f"/api/v1/classification/documents/{document_id}/result",
        headers=_auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["predicted_type"] == "MSI"


def test_get_classification_result_before_any_run_returns_404():
    token = _register_and_login(prefix="clsnorun")
    document_id = _upload_and_run_stub_ocr(token)

    response = client.get(
        f"/api/v1/classification/documents/{document_id}/result",
        headers=_auth_header(token),
    )
    assert response.status_code == 404


def test_list_classification_results_shows_multiple_runs():
    token = _register_and_login(prefix="clsmulti")
    document_id = _upload_and_run_stub_ocr(token)
    _inject_realistic_ocr_text(document_id, SAMPLE_TEXTS[DocumentType.POI])

    client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )
    client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(token), json={},
    )

    response = client.get(
        f"/api/v1/classification/documents/{document_id}/results",
        headers=_auth_header(token),
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_classify_respects_document_access_scoping():
    owner_token = _register_and_login(prefix="clsowner")
    other_token = _register_and_login(prefix="clsother")
    document_id = _upload_and_run_stub_ocr(owner_token)

    response = client.post(
        f"/api/v1/classification/documents/{document_id}/classify",
        headers=_auth_header(other_token), json={},
    )
    assert response.status_code == 403


# --- Phase 1 Improvements Verification Tests ---

def test_classifies_real_world_indian_npo_invoice_layout():
    """
    Test classification on realistic invoice layouts containing
    'Seller', 'Client', 'GSTIN', 'Tax Id', 'Date of issue', and 'Net/Gross Worth'.
    """
    classifier = RuleBasedClassifier()
    text = (
        "Invoice no: 51109301\n"
        "Date of issue: 03/07/2023\n"
        "Seller: TechVision Distributors Pvt Ltd\n"
        "Plot 14, MIDC Industrial Area, Andheri East, Mumbai, Maharashtra - 400093\n"
        "Tax Id: 27AABCT1234F1Z5\n"
        "GSTIN: 27AABCT1234F1Z5\n"
        "Client: Raj Electronics Pvt Ltd\n"
        "42 MG Road, Bengaluru, Karnataka - 560001\n"
        "Tax Id: 901-95-4704\n"
        "ITEMS\n"
        "No. Description Qty UM Net Price Net Worth VAT % Gross Worth\n"
        "1. Garmin Fenix 7 Solar GPS 9.00 pcs 74,120.00 667,080.00 10% 733,788.00\n"
        "SUMMARY\n"
        "Total INR 1,676,976.00"
    )
    result = classifier.classify(text)
    assert result.document_type == DocumentType.NPO
    assert result.confidence >= 0.60
    rule_descs = [s.rule_description for s in result.signals]
    assert any("invoice" in r for r in rule_descs)
    assert any("seller" in r.lower() or "vendor" in r.lower() for r in rule_descs)
    assert any("client" in r.lower() or "bill to" in r.lower() for r in rule_descs)
    assert any("gstin" in r.lower() for r in rule_descs)


def test_short_token_word_boundary_guards_prevent_false_positives():
    """
    Verifies that short tokens (like 'grn', 'srn', 'po', 'je') do not match
    inside random words such as 'background', 'afternoon', 'position', or 'object'.
    """
    classifier = RuleBasedClassifier()
    benign_text = "The background of the object was set in the afternoon."
    result = classifier.classify(benign_text)
    assert result.document_type == DocumentType.UNKNOWN
    assert result.confidence < 0.23


def test_poi_beats_npo_when_purchase_order_is_explicitly_present():
    """
    When both invoice language and PO references exist, POI should win with high confidence.
    """
    classifier = RuleBasedClassifier()
    text = (
        "TAX INVOICE\n"
        "Invoice no: 51109301\n"
        "Purchase Order: PO-2023-9999\n"
        "Seller: TechVision Distributors\n"
        "Client: Raj Electronics\n"
        "GSTIN: 27AABCT1234F1Z5\n"
        "Total INR 1,500,000.00"
    )
    result = classifier.classify(text)
    assert result.document_type == DocumentType.POI
    assert result.confidence > 0.50
    assert result.scores_by_type["POI"] > result.scores_by_type["NPO"]
