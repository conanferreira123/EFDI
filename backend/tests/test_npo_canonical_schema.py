"""Unit tests for Phase A: Canonical Hierarchical NPO Schema and Pydantic Definitions."""
import pytest
from pydantic import BaseModel

from app.extraction.field_schemas import (
    NPO_CANONICAL_SCHEMA,
    NPO_MANDATORY_CORE_PATHS,
    NPO_IMPORTANT_OPTIONAL_PATHS,
    NPO_SYSTEM_METADATA_PATHS,
    NPO_FLAT_TO_CANONICAL_MAPPING,
    get_full_field_schema,
    get_npo_canonical_paths,
    is_hierarchical_schema,
    map_npo_canonical_to_flat,
    map_npo_flat_to_canonical,
)
from app.extraction.llm_schema import (
    LLMFieldItem,
    ExtractedValue,
    NPOExtractionPayload,
    NPOLineItemPayload,
    NPOTaxItemPayload,
    NPOInvoiceInformationPayload,
    NPOSellerPayload,
    NPOBuyerPayload,
    NPOTotalsPayload,
    NPOPaymentPayload,
    NPOReferencesPayload,
    build_dynamic_extraction_model,
    get_extraction_model,
)


def test_is_hierarchical_schema():
    """Verify is_hierarchical_schema flags NPO while keeping other types false."""
    assert is_hierarchical_schema("NPO") is True
    assert is_hierarchical_schema("npo") is True
    assert is_hierarchical_schema("POI") is False
    assert is_hierarchical_schema("JER") is False
    assert is_hierarchical_schema("MSI") is False
    assert is_hierarchical_schema("UNKNOWN") is False


def test_npo_canonical_schema_structure():
    """Verify NPO_CANONICAL_SCHEMA defines all 9 semantic sections with correct flags."""
    section_keys = [s.key for s in NPO_CANONICAL_SCHEMA]
    expected_sections = [
        "invoice_information",
        "seller",
        "buyer",
        "line_items",
        "taxes",
        "totals",
        "payment",
        "references",
        "metadata",
    ]
    assert section_keys == expected_sections

    line_items_sec = next(s for s in NPO_CANONICAL_SCHEMA if s.key == "line_items")
    assert line_items_sec.is_array is True

    taxes_sec = next(s for s in NPO_CANONICAL_SCHEMA if s.key == "taxes")
    assert taxes_sec.is_array is True

    seller_sec = next(s for s in NPO_CANONICAL_SCHEMA if s.key == "seller")
    assert seller_sec.is_array is False


def test_npo_path_categorization_disjoint():
    """Verify mandatory core (6 fields), important optional, and system metadata paths are defined and distinct."""
    # Mandatory processing core (exactly 6 paths)
    expected_mandatory = {
        "invoice_information.invoice_number",
        "invoice_information.invoice_date",
        "invoice_information.currency",
        "seller.name",
        "buyer.name",
        "totals.grand_total",
    }
    assert NPO_MANDATORY_CORE_PATHS == expected_mandatory

    # Optional fields (must legitimately remain null if unstated)
    assert "seller.tax_id" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "seller.address" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "buyer.tax_id" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "buyer.address" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "totals.subtotal" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "totals.total_tax" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "invoice_information.document_type" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "payment.payment_terms" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "payment.iban" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "totals.discount" in NPO_IMPORTANT_OPTIONAL_PATHS
    assert "references.po_number" in NPO_IMPORTANT_OPTIONAL_PATHS

    # System metadata fields
    assert "metadata.document_id" in NPO_SYSTEM_METADATA_PATHS
    assert "metadata.vendor_code" in NPO_SYSTEM_METADATA_PATHS
    assert "metadata.processing_status" in NPO_SYSTEM_METADATA_PATHS

    # Ensure no overlap between mandatory, optional, and system paths
    assert NPO_MANDATORY_CORE_PATHS.isdisjoint(NPO_IMPORTANT_OPTIONAL_PATHS)
    assert NPO_MANDATORY_CORE_PATHS.isdisjoint(NPO_SYSTEM_METADATA_PATHS)
    assert NPO_IMPORTANT_OPTIONAL_PATHS.isdisjoint(NPO_SYSTEM_METADATA_PATHS)


def test_npo_mapping_helpers():
    """Verify bidirectional mapping between flat keys and canonical paths."""
    assert map_npo_flat_to_canonical("invoice_number") == "invoice_information.invoice_number"
    assert map_npo_flat_to_canonical("seller_name") == "seller.name"
    assert map_npo_flat_to_canonical("grand_total_amount") == "totals.grand_total"
    assert map_npo_flat_to_canonical("unknown_custom_key") == "unknown_custom_key"

    assert map_npo_canonical_to_flat("invoice_information.invoice_number") == "invoice_number"
    assert map_npo_canonical_to_flat("seller.name") == "seller_name"
    assert map_npo_canonical_to_flat("totals.grand_total") == "grand_total_amount"


def test_legacy_full_field_schema_intact():
    """Verify get_full_field_schema('NPO') remains fully backward-compatible."""
    fields = get_full_field_schema("NPO")
    keys = [f.key for f in fields]
    assert "invoice_number" in keys
    assert "seller_name" in keys
    assert "grand_total_amount" in keys
    assert "document_id" in keys


def test_llm_field_item_missing_value_rule():
    """Verify the core rule: missing/unfound fields MUST have value=None, confidence=0.0, is_found=False."""
    # None value
    item1 = LLMFieldItem(value=None, confidence=0.9, source_quote="fabricated")
    assert item1.value is None
    assert item1.confidence == 0.0
    assert item1.is_found is False
    assert item1.source_quote is None

    # Blank whitespace value
    item2 = LLMFieldItem(value="   ", confidence=0.85)
    assert item2.value is None
    assert item2.confidence == 0.0
    assert item2.is_found is False

    # Present valid value
    item3 = LLMFieldItem(value="INV-2026-001", confidence=0.95, source_quote="INV-2026-001")
    assert item3.value == "INV-2026-001"
    assert item3.confidence == 0.95
    assert item3.is_found is True
    assert item3.source_quote == "INV-2026-001"


def test_npo_extraction_payload_empty_structure():
    """Verify NPOExtractionPayload initializes cleanly with empty line_items and taxes."""
    payload = NPOExtractionPayload()
    assert payload.line_items == []
    assert payload.taxes == []
    assert payload.invoice_information.invoice_number is None

    canonical_dict = payload.to_canonical_dict()
    assert "invoice_information" in canonical_dict
    assert "seller" in canonical_dict
    assert "buyer" in canonical_dict
    assert canonical_dict["line_items"] == []
    assert canonical_dict["taxes"] == []
    assert canonical_dict["totals"]["grand_total"]["value"] is None
    assert canonical_dict["totals"]["grand_total"]["is_found"] is False


def test_npo_extraction_payload_with_multi_items_and_taxes():
    """Verify NPOExtractionPayload correctly validates multi-line items and taxes."""
    payload = NPOExtractionPayload(
        invoice_information=NPOInvoiceInformationPayload(
            invoice_number=LLMFieldItem(value="INV-99", confidence=0.99, source_quote="Invoice: INV-99"),
            currency=LLMFieldItem(value="EUR", confidence=1.0, source_quote="EUR"),
        ),
        seller=NPOSellerPayload(
            name=LLMFieldItem(value="Acme Tech GmbH", confidence=0.95, source_quote="Acme Tech GmbH"),
            tax_id=LLMFieldItem(value="DE987654321", confidence=0.90, source_quote="DE987654321"),
        ),
        line_items=[
            NPOLineItemPayload(
                description=LLMFieldItem(value="Server rack maintenance", confidence=0.95, source_quote="Server rack"),
                quantity=LLMFieldItem(value="2", confidence=0.99, source_quote="2"),
                unit_price=LLMFieldItem(value="500.00", confidence=0.95, source_quote="500.00"),
                net_amount=LLMFieldItem(value="1000.00", confidence=0.98, source_quote="1000.00"),
                tax_rate=LLMFieldItem(value="19.0", confidence=0.95, source_quote="19%"),
                gross_amount=LLMFieldItem(value="1190.00", confidence=0.98, source_quote="1190.00"),
            ),
            NPOLineItemPayload(
                # Narrative service without explicit quantity or unit price
                description=LLMFieldItem(value="Network security setup fee", confidence=0.92, source_quote="Network fee"),
                quantity=None,    # Explicitly absent: do NOT hallucinate quantity=1
                unit_price=None,  # Explicitly absent: do NOT hallucinate unit_price=250.00
                net_amount=LLMFieldItem(value="250.00", confidence=0.95, source_quote="250.00"),
                tax_rate=LLMFieldItem(value="19.0", confidence=0.95, source_quote="19%"),
            ),
        ],
        taxes=[
            NPOTaxItemPayload(
                tax_type=LLMFieldItem(value="VAT", confidence=0.95),
                tax_rate=LLMFieldItem(value="19.0", confidence=0.99, source_quote="19%"),
                taxable_amount=LLMFieldItem(value="1250.00", confidence=0.98, source_quote="1250.00"),
                tax_amount=LLMFieldItem(value="237.50", confidence=0.98, source_quote="237.50"),
            )
        ],
        totals=NPOTotalsPayload(
            subtotal=LLMFieldItem(value="1250.00", confidence=0.98, source_quote="1250.00"),
            total_tax=LLMFieldItem(value="237.50", confidence=0.98, source_quote="237.50"),
            grand_total=LLMFieldItem(value="1487.50", confidence=0.99, source_quote="1487.50"),
        ),
    )

    canonical_dict = payload.to_canonical_dict()
    assert len(canonical_dict["line_items"]) == 2
    assert canonical_dict["line_items"][0]["description"]["value"] == "Server rack maintenance"
    assert canonical_dict["line_items"][0]["quantity"]["value"] == "2"

    # Verify narrative second item preserves null quantity without hallucination
    assert canonical_dict["line_items"][1]["description"]["value"] == "Network security setup fee"
    assert canonical_dict["line_items"][1]["quantity"]["value"] is None
    assert canonical_dict["line_items"][1]["quantity"]["is_found"] is False
    assert canonical_dict["line_items"][1]["unit_price"]["value"] is None

    # Flattened paths
    paths = payload.flatten_to_paths()
    assert "invoice_information.invoice_number" in paths
    assert paths["invoice_information.invoice_number"].value == "INV-99"
    assert "line_items.0.net_amount" in paths
    assert paths["line_items.0.net_amount"].value == "1000.00"
    assert "line_items.1.quantity" in paths
    assert paths["line_items.1.quantity"].value is None

    # Legacy flat projection
    legacy = payload.flatten_to_legacy_dict()
    assert legacy["invoice_number"]["value"] == "INV-99"
    assert legacy["seller_name"]["value"] == "Acme Tech GmbH"
    assert legacy["grand_total_amount"]["value"] == "1487.50"


def test_get_extraction_model_dispatch():
    """Verify get_extraction_model returns NPOExtractionPayload for NPO and dynamic model for POI."""
    npo_model = get_extraction_model("NPO", hierarchical=True)
    assert npo_model == NPOExtractionPayload

    poi_model = get_extraction_model("POI", hierarchical=True)
    assert issubclass(poi_model, BaseModel)
    assert poi_model != NPOExtractionPayload
    assert "po_number" in poi_model.model_fields

    # When hierarchical is False, NPO also gets dynamic flat model
    npo_flat_model = get_extraction_model("NPO", hierarchical=False)
    assert issubclass(npo_flat_model, BaseModel)
    assert "invoice_number" in npo_flat_model.model_fields
    assert "seller_name" in npo_flat_model.model_fields
