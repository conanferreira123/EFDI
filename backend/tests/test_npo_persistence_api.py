"""
Tests for Phase C: Persistence & API Integration.

Verifies end-to-end transport and storage of canonical hierarchical NPO
extractions through ExtractionResultData -> ExtractionResult (DB) -> Service Layer -> API Response.

Requirements tested:
1. Canonical NPO extraction can be persisted.
2. Canonical nested structure survives persistence unchanged.
3. line_items=[] persists correctly.
4. Multiple line_items persist correctly.
5. taxes=[] persists correctly.
6. Multiple taxes persist correctly.
7. Nullable optional fields persist as null.
8. Six mandatory core fields remain represented correctly.
9. Provenance/confidence/source_quote survive persistence.
10. API returns canonical nested NPO structure.
11. Legacy flat aliases remain available where currently required.
12. Existing NPO behavior does not regress.
13. Non-NPO document types remain unaffected.
14. Existing extraction/persistence behavior remains compatible.
15. Round-trip test: extraction -> persistence -> retrieval -> API preserves structure.
16. Manual field correction on canonical dot-paths updates database cleanly.
17. Dual synchronization: manual edit to flat alias updates canonical representation.
18. Dual synchronization: manual edit to canonical path updates legacy flat alias.
19. Export rows handle complex collections and canonical payloads without crashing.
20. Empty collections line_items=[] and taxes=[] do not cause persistence or schema validation errors.
"""
import uuid
from typing import Any
import pytest
from app.database.session import get_db_context
from app.extraction.base import ExtractedField, ExtractionResultData
from app.extraction.llm_schema import (
    LLMFieldItem,
    NPOExtractionPayload,
    NPOLineItemPayload,
    NPOTaxItemPayload,
)
from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.extraction_result import ExtractionResult
from app.repositories.extraction_result_repository import ExtractionResultRepository
from app.schemas.extraction import ExtractionResultResponse, ExtractedFieldSchema
from app.services.extraction_service import ExtractionService


from app.models.user import User


@pytest.fixture
def db_session():
    """Use the real database session via get_db_context to support JSONB fields."""
    with get_db_context() as session:
        yield session


@pytest.fixture
def test_user(db_session):
    """Ensure at least one user exists for document foreign key."""
    user = db_session.query(User).first()
    if not user:
        user = User(
            username=f"testuser_{uuid.uuid4().hex[:8]}",
            email=f"test_{uuid.uuid4().hex[:8]}@example.com",
            full_name="Test User",
            password_hash="fakehash",
            role="FINANCE_ANALYST",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


@pytest.fixture
def test_document(db_session, test_user):
    """Create a test document in the database."""
    doc = Document(
        original_filename="npo_invoice_sample.pdf",
        stored_filename=f"stored_{uuid.uuid4().hex}.pdf",
        file_size_bytes=1024,
        mime_type="application/pdf",
        file_hash=uuid.uuid4().hex,
        company_code="CC100",
        vendor_code="V100",
        document_type="NPO",
        status=DocumentStatus.UPLOADED.value,
        uploaded_by=test_user.id,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


def _create_sample_npo_payload(
    num_items: int = 2,
    num_taxes: int = 1,
    include_optional: bool = True,
) -> NPOExtractionPayload:
    """Helper to construct a fully populated or sparse NPOExtractionPayload."""
    payload = NPOExtractionPayload()
    payload.invoice_information.invoice_number = LLMFieldItem(
        value="INV-2026-9001", confidence=0.98, source_quote="Invoice: INV-2026-9001", is_found=True
    )
    payload.invoice_information.invoice_date = LLMFieldItem(
        value="2026-06-15", confidence=0.95, source_quote="Date: 15/06/2026", is_found=True
    )
    payload.invoice_information.currency = LLMFieldItem(
        value="USD", confidence=0.99, source_quote="$", is_found=True
    )
    payload.seller.name = LLMFieldItem(
        value="Acme Corp Global", confidence=0.96, source_quote="Acme Corp Global", is_found=True
    )
    payload.buyer.name = LLMFieldItem(
        value="Beta Solutions LLC", confidence=0.95, source_quote="Beta Solutions LLC", is_found=True
    )
    payload.totals.grand_total = LLMFieldItem(
        value="1150.00", confidence=0.97, source_quote="Total: $1,150.00", is_found=True
    )

    if include_optional:
        payload.seller.tax_id = LLMFieldItem(
            value="US123456789", confidence=0.90, source_quote="Tax ID: US123456789", is_found=True
        )
        payload.buyer.address = LLMFieldItem(
            value="456 Market St, Boston, MA", confidence=0.88, source_quote="456 Market St", is_found=True
        )
        payload.totals.subtotal = LLMFieldItem(
            value="1000.00", confidence=0.95, source_quote="Subtotal: $1,000.00", is_found=True
        )
        payload.totals.total_tax = LLMFieldItem(
            value="150.00", confidence=0.94, source_quote="Tax: $150.00", is_found=True
        )

    for i in range(num_items):
        item = NPOLineItemPayload()
        item.description = LLMFieldItem(
            value=f"Service Item {i+1}", confidence=0.90, source_quote=f"Service Item {i+1}", is_found=True
        )
        item.quantity = LLMFieldItem(
            value=str(i + 1), confidence=0.85, source_quote=str(i + 1), is_found=True
        )
        item.unit_price = LLMFieldItem(
            value="500.00", confidence=0.90, source_quote="500.00", is_found=True
        )
        item.net_amount = LLMFieldItem(
            value=str((i + 1) * 500), confidence=0.92, source_quote=str((i + 1) * 500), is_found=True
        )
        payload.line_items.append(item)

    for i in range(num_taxes):
        tax = NPOTaxItemPayload()
        tax.tax_type = LLMFieldItem(value="VAT", confidence=0.95, is_found=True)
        tax.tax_rate = LLMFieldItem(value="15%", confidence=0.90, source_quote="15%", is_found=True)
        tax.tax_amount = LLMFieldItem(value="150.00", confidence=0.92, source_quote="150.00", is_found=True)
        payload.taxes.append(tax)

    return payload


def _payload_to_db_fields(payload: NPOExtractionPayload) -> dict[str, Any]:
    """Simulate extraction layer populating fields for storage."""
    payload.normalize_values()
    canonical_dict = payload.to_canonical_dict()
    paths = payload.flatten_to_paths()
    legacy_dict = payload.flatten_to_legacy_dict()

    fields_payload = {}
    for path, item in paths.items():
        fields_payload[path] = {
            "value": item.value,
            "confidence": round(item.confidence, 2),
            "matched_text": item.source_quote,
            "is_found": item.is_found,
            "manually_entered": False,
            "provenance": item.provenance or "llm",
            "conflict_value": None,
        }

    fields_payload["line_items"] = {
        "value": canonical_dict["line_items"],
        "confidence": 1.0 if canonical_dict["line_items"] else 0.0,
        "matched_text": None,
        "is_found": bool(canonical_dict["line_items"]),
        "manually_entered": False,
        "provenance": "llm",
        "conflict_value": None,
    }

    fields_payload["taxes"] = {
        "value": canonical_dict["taxes"],
        "confidence": 1.0 if canonical_dict["taxes"] else 0.0,
        "matched_text": None,
        "is_found": bool(canonical_dict["taxes"]),
        "manually_entered": False,
        "provenance": "llm",
        "conflict_value": None,
    }

    fields_payload["canonical"] = {
        "value": canonical_dict,
        "confidence": 0.95,
        "matched_text": None,
        "is_found": True,
        "manually_entered": False,
        "provenance": "llm",
        "conflict_value": None,
    }

    for flat_key, item_dict in legacy_dict.items():
        fields_payload[flat_key] = {
            "value": item_dict["value"],
            "confidence": item_dict["confidence"],
            "matched_text": item_dict.get("matched_text"),
            "is_found": item_dict["value"] is not None,
            "manually_entered": False,
            "provenance": item_dict.get("provenance") or "llm",
            "conflict_value": None,
        }

    return fields_payload


def test_01_canonical_npo_extraction_can_be_persisted(db_session, test_document):
    """Test 1: Canonical NPO extraction can be saved in the database repository."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    result = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    assert result.id is not None
    assert result.document_id == test_document.id
    assert result.document_type == "NPO"
    assert "canonical" in result.fields


def test_02_canonical_nested_structure_survives_persistence_unchanged(db_session, test_document):
    """Test 2: Canonical nested structure is retrieved from DB exactly as stored."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    retrieved = repo.get_by_id(created.id)
    assert retrieved is not None
    canonical = retrieved.fields["canonical"]["value"]
    assert canonical["invoice_information"]["invoice_number"]["value"] == "INV-2026-9001"
    assert canonical["seller"]["name"]["value"] == "Acme Corp Global"
    assert canonical["totals"]["grand_total"]["value"] == "1150.00"


def test_03_empty_line_items_persists_correctly(db_session, test_document):
    """Test 3: Zero-or-many semantics: line_items=[] persists cleanly without failure."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_items=0)
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.90,
        fields_found_count=6,
        fields_total_count=15,
    )

    retrieved = repo.get_by_id(created.id)
    assert retrieved.fields["line_items"]["value"] == []
    assert retrieved.fields["canonical"]["value"]["line_items"] == []


def test_04_multiple_line_items_persist_correctly(db_session, test_document):
    """Test 4: Multiple line items persist with all individual leaf fields intact."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_items=3)
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.92,
        fields_found_count=15,
        fields_total_count=25,
    )

    retrieved = repo.get_by_id(created.id)
    items = retrieved.fields["line_items"]["value"]
    assert len(items) == 3
    assert items[0]["description"]["value"] == "Service Item 1"
    assert items[1]["description"]["value"] == "Service Item 2"
    assert items[2]["description"]["value"] == "Service Item 3"


def test_05_empty_taxes_persists_correctly(db_session, test_document):
    """Test 5: Zero-or-many semantics: taxes=[] persists cleanly."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_taxes=0)
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.90,
        fields_found_count=6,
        fields_total_count=15,
    )

    retrieved = repo.get_by_id(created.id)
    assert retrieved.fields["taxes"]["value"] == []
    assert retrieved.fields["canonical"]["value"]["taxes"] == []


def test_06_multiple_taxes_persist_correctly(db_session, test_document):
    """Test 6: Multiple tax entries persist distinctly."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_taxes=2)
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.92,
        fields_found_count=12,
        fields_total_count=20,
    )

    retrieved = repo.get_by_id(created.id)
    taxes = retrieved.fields["taxes"]["value"]
    assert len(taxes) == 2
    assert taxes[0]["tax_type"]["value"] == "VAT"
    assert taxes[1]["tax_type"]["value"] == "VAT"


def test_07_nullable_optional_fields_persist_as_null(db_session, test_document):
    """Test 7: Unstated optional fields persist strictly as null, without dummy strings."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(include_optional=False)
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.90,
        fields_found_count=6,
        fields_total_count=15,
    )

    retrieved = repo.get_by_id(created.id)
    assert retrieved.fields["seller.tax_id"]["value"] is None
    assert retrieved.fields["seller.address"]["value"] is None
    assert retrieved.fields["payment.bank_account"]["value"] is None
    assert retrieved.fields["references.po_number"]["value"] is None


def test_08_six_mandatory_core_fields_represented_correctly(db_session, test_document):
    """Test 8: The 6 mandatory core fields are present, populated, and queryable."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    retrieved = repo.get_by_id(created.id)
    fields = retrieved.fields
    assert fields["invoice_information.invoice_number"]["value"] == "INV-2026-9001"
    assert fields["invoice_information.invoice_date"]["value"] == "2026-06-15"
    assert fields["invoice_information.currency"]["value"] == "USD"
    assert fields["seller.name"]["value"] == "Acme Corp Global"
    assert fields["buyer.name"]["value"] == "Beta Solutions LLC"
    assert fields["totals.grand_total"]["value"] == "1150.00"


def test_09_provenance_confidence_source_quote_survive_persistence(db_session, test_document):
    """Test 9: Provenance, confidence, and source quotes survive DB round-trip."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    retrieved = repo.get_by_id(created.id)
    field_item = retrieved.fields["invoice_information.invoice_number"]
    assert field_item["confidence"] == 0.98
    assert field_item["matched_text"] == "Invoice: INV-2026-9001"
    assert field_item["provenance"] == "llm"


def test_10_api_response_model_exposes_canonical_structure(db_session, test_document):
    """Test 10: ExtractionResultResponse serializes canonical nested dictionary on top level."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    api_response = ExtractionResultResponse.model_validate(created)
    dumped = api_response.model_dump()

    assert "canonical" in dumped
    assert dumped["canonical"] is not None
    assert dumped["canonical"]["invoice_information"]["invoice_number"]["value"] == "INV-2026-9001"
    assert dumped["canonical"]["totals"]["grand_total"]["value"] == "1150.00"


def test_11_legacy_flat_aliases_remain_available(db_session, test_document):
    """Test 11: Legacy consumers can continue reading flat keys like invoice_number."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    api_response = ExtractionResultResponse.model_validate(created)
    fields = api_response.fields

    assert "invoice_number" in fields
    assert fields["invoice_number"].value == "INV-2026-9001"
    assert "seller_name" in fields
    assert fields["seller_name"].value == "Acme Corp Global"
    assert "grand_total_amount" in fields
    assert fields["grand_total_amount"].value == "1150.00"


def test_12_non_npo_document_types_remain_unaffected(db_session, test_user):
    """Test 12: Non-NPO documents (e.g. POI) persist and serialize normally without canonical overhead."""
    doc = Document(
        original_filename="poi_invoice.pdf",
        stored_filename=f"stored_poi_{uuid.uuid4().hex}.pdf",
        file_size_bytes=1024,
        mime_type="application/pdf",
        file_hash=uuid.uuid4().hex,
        company_code="CC100",
        document_type="POI",
        status=DocumentStatus.UPLOADED.value,
        uploaded_by=test_user.id,
    )
    db_session.add(doc)
    db_session.commit()

    repo = ExtractionResultRepository(db_session)
    poi_fields = {
        "po_number": {"value": "PO-123", "confidence": 0.95, "matched_text": "PO-123", "is_found": True},
        "invoice_number": {"value": "INV-555", "confidence": 0.90, "matched_text": "INV-555", "is_found": True},
    }
    created = repo.create(
        document_id=doc.id,
        document_type="POI",
        engine_name="rule_based",
        fields=poi_fields,
        overall_confidence=0.92,
        fields_found_count=2,
        fields_total_count=10,
    )

    api_response = ExtractionResultResponse.model_validate(created)
    dumped = api_response.model_dump()
    assert dumped["canonical"] is None
    assert dumped["fields"]["po_number"]["value"] == "PO-123"


def test_13_hybrid_reconciliation_preserves_npo_collections(db_session):
    """Test 13: Hybrid extraction reconciliation preserves line_items, taxes, and canonical root."""
    from app.extraction.reconciliation import ReconciliationEngine
    from app.extraction.parallel_orchestrator import DualExtractionResult
    from app.extraction.base import ExtractionContext

    rule_res = ExtractionResultData(document_type="NPO", engine_name="rule_based")
    llm_res = ExtractionResultData(document_type="NPO", engine_name="llm_based")

    llm_res.fields["invoice_information.invoice_number"] = ExtractedField(
        value="INV-RECON-1", confidence=0.98, provenance="llm"
    )
    llm_res.fields["line_items"] = ExtractedField(
        value=[{"description": {"value": "Reconciled item"}}], confidence=1.0, provenance="llm"
    )
    llm_res.fields["taxes"] = ExtractedField(value=[], confidence=0.0, provenance="llm")
    llm_res.fields["canonical"] = ExtractedField(
        value={"invoice_information": {"invoice_number": {"value": "INV-RECON-1"}}},
        confidence=0.98,
        provenance="llm",
    )
    llm_res.fields["invoice_number"] = ExtractedField(value="INV-RECON-1", confidence=0.98, provenance="llm")

    dual = DualExtractionResult(document_type="NPO", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="Invoice text", document_type="NPO")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    assert "invoice_information.invoice_number" in reconciled.fields
    assert "line_items" in reconciled.fields
    assert "taxes" in reconciled.fields
    assert "canonical" in reconciled.fields


def test_14_round_trip_extraction_persistence_api(db_session, test_document):
    """Test 14: Full round-trip test from payload -> DB -> API schema."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_items=1, num_taxes=1)
    db_fields = _payload_to_db_fields(payload)

    # 1. Persist
    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=8,
        fields_total_count=18,
    )

    # 2. Retrieve
    retrieved = repo.get_latest_for_document(test_document.id)
    assert retrieved is not None
    assert retrieved.id == created.id

    # 3. Serialize to API
    api_response = ExtractionResultResponse.model_validate(retrieved)
    assert api_response.document_type == "NPO"
    assert api_response.canonical is not None
    assert len(api_response.canonical["line_items"]) == 1
    assert api_response.canonical["line_items"][0]["description"]["value"] == "Service Item 1"


def test_15_manual_field_correction_on_canonical_path(db_session, test_document):
    """Test 15: Manually correcting a canonical dot-path updates DB and keeps flat alias synced."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    service = ExtractionService(db_session)
    updated = service.update_field(
        test_document.id, "invoice_information.invoice_number", "INV-CORRECTED-999"
    )

    # Both dot-path and flat alias should be updated
    assert updated.fields["invoice_information.invoice_number"]["value"] == "INV-CORRECTED-999"
    assert updated.fields["invoice_number"]["value"] == "INV-CORRECTED-999"
    assert updated.fields["canonical"]["value"]["invoice_information"]["invoice_number"]["value"] == "INV-CORRECTED-999"


def test_16_manual_field_correction_on_flat_alias_syncs_canonical(db_session, test_document):
    """Test 16: Manually correcting a legacy flat key updates canonical dot-path and canonical dictionary."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    service = ExtractionService(db_session)
    updated = service.update_field(test_document.id, "grand_total_amount", "9999.50")

    assert updated.fields["grand_total_amount"]["value"] == "9999.50"
    assert updated.fields["totals.grand_total"]["value"] == "9999.50"
    assert updated.fields["canonical"]["value"]["totals"]["grand_total"]["value"] == "9999.50"


def test_17_manual_date_correction_normalization(db_session, test_document):
    """Test 17: Manual correction of date on canonical path normalizes to ISO."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload()
    db_fields = _payload_to_db_fields(payload)

    repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    service = ExtractionService(db_session)
    updated = service.update_field(test_document.id, "invoice_information.invoice_date", "21/03/2026")

    assert updated.fields["invoice_information.invoice_date"]["value"] == "2026-03-21"
    assert updated.fields["invoice_date"]["value"] == "2026-03-21"


def test_18_get_export_rows_handles_complex_collections_safely(db_session, test_document):
    """Test 18: Export rows serialize collections as JSON string rather than crashing."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_items=2)
    db_fields = _payload_to_db_fields(payload)

    repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.95,
        fields_found_count=10,
        fields_total_count=20,
    )

    service = ExtractionService(db_session)
    rows = service.get_export_rows(test_document.id)

    # canonical container is excluded from flat export rows
    assert all(r["key"] != "canonical" for r in rows)
    # line_items key should have stringified JSON value if present
    li_row = next((r for r in rows if r["key"] == "line_items"), None)
    if li_row and li_row["value"]:
        assert isinstance(li_row["value"], str)


def test_19_empty_collections_remain_valid_in_api_response(db_session, test_document):
    """Test 19: An invoice with line_items=[] and taxes=[] serializes with empty arrays, not errors."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_items=0, num_taxes=0)
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.90,
        fields_found_count=6,
        fields_total_count=15,
    )

    api_response = ExtractionResultResponse.model_validate(created)
    assert api_response.canonical["line_items"] == []
    assert api_response.canonical["taxes"] == []
    assert api_response.fields["line_items"].value == []
    assert api_response.fields["taxes"].value == []


def test_20_mandatory_core_present_with_all_optional_null_in_api(db_session, test_document):
    """Test 20: Minimal invoice with only 6 mandatory core fields serializes cleanly with nulls."""
    repo = ExtractionResultRepository(db_session)
    payload = _create_sample_npo_payload(num_items=0, num_taxes=0, include_optional=False)
    db_fields = _payload_to_db_fields(payload)

    created = repo.create(
        document_id=test_document.id,
        document_type="NPO",
        engine_name="llm_based",
        fields=db_fields,
        overall_confidence=0.88,
        fields_found_count=6,
        fields_total_count=15,
    )

    api_response = ExtractionResultResponse.model_validate(created)
    canonical = api_response.canonical

    # 6 Mandatory core
    assert canonical["invoice_information"]["invoice_number"]["value"] == "INV-2026-9001"
    assert canonical["invoice_information"]["invoice_date"]["value"] == "2026-06-15"
    assert canonical["invoice_information"]["currency"]["value"] == "USD"
    assert canonical["seller"]["name"]["value"] == "Acme Corp Global"
    assert canonical["buyer"]["name"]["value"] == "Beta Solutions LLC"
    assert canonical["totals"]["grand_total"]["value"] == "1150.00"

    # Optionals are null
    assert canonical["seller"]["tax_id"]["value"] is None
    assert canonical["buyer"]["tax_id"]["value"] is None
    assert canonical["totals"]["subtotal"]["value"] is None
    assert canonical["payment"]["bank_account"]["value"] is None
