"""Phase B: Comprehensive Test Suite for NPO LLM Semantic Extraction.

Covers all 20 required Phase B test scenarios:
 1. Standard tabular NPO invoice
 2. Multiple line items
 3. Single line item
 4. Zero line items
 5. Narrative service invoice
 6. Missing quantity
 7. Missing unit price
 8. Missing tax information
 9. Multiple tax rates
10. Missing optional seller information
11. Missing optional buyer information
12. Missing payment information
13. Missing references
14. Different invoice terminology
15. Different layout/ordering
16. No hallucinated values
17. Existing regression invoice
18. Nested output structure
19. Mandatory core extraction
20. Confidence/provenance preservation
"""
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.extraction.base import ExtractionContext
from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.llm_schema import (
    LLMFieldItem,
    NPOBuyerPayload,
    NPOExtractionPayload,
    NPOInvoiceInformationPayload,
    NPOLineItemPayload,
    NPOPaymentPayload,
    NPOReferencesPayload,
    NPOSellerPayload,
    NPOTaxItemPayload,
    NPOTotalsPayload,
)


@pytest.fixture
def extractor() -> LLMBasedExtractor:
    """Fixture providing an LLMBasedExtractor with mock API credentials."""
    return LLMBasedExtractor(api_key="mock-test-key")


# =====================================================================
# 1. Standard tabular NPO invoice
# =====================================================================

def test_01_standard_tabular_npo_invoice(extractor: LLMBasedExtractor):
    """Scenario 1: Standard tabular NPO invoice with table, line items, VAT, and totals."""
    mock_payload = {
        "invoice_information": {
            "invoice_number": {"value": "INV-2026-101", "confidence": 0.98, "source_quote": "Invoice No: INV-2026-101"},
            "invoice_date": {"value": "2026-06-15", "confidence": 0.95, "source_quote": "Date: 15/06/2026"},
            "currency": {"value": "USD", "confidence": 0.95, "source_quote": "$"},
            "document_type": {"value": "NPO", "confidence": 0.90, "source_quote": "Non-PO Invoice"},
        },
        "seller": {
            "name": {"value": "Apex Technology Corp", "confidence": 0.96, "source_quote": "Apex Technology Corp"},
            "tax_id": {"value": "US-987654321", "confidence": 0.92, "source_quote": "Tax ID: US-987654321"},
            "address": {"value": "100 Tech Blvd, Austin, TX", "confidence": 0.88, "source_quote": "100 Tech Blvd, Austin, TX"},
        },
        "buyer": {
            "name": {"value": "Global Logistics Inc", "confidence": 0.95, "source_quote": "Bill To: Global Logistics Inc"},
            "tax_id": {"value": "US-123456789", "confidence": 0.90, "source_quote": "Customer VAT: US-123456789"},
            "address": {"value": "500 Harbor Way, Seattle, WA", "confidence": 0.87, "source_quote": "500 Harbor Way, Seattle, WA"},
        },
        "line_items": [
            {
                "description": {"value": "Cloud Server Instances", "confidence": 0.94, "source_quote": "Cloud Server Instances"},
                "quantity": {"value": "2", "confidence": 0.95, "source_quote": "2"},
                "uom": {"value": "MONTH", "confidence": 0.90, "source_quote": "MONTH"},
                "unit_price": {"value": "1500.00", "confidence": 0.95, "source_quote": "1500.00"},
                "net_amount": {"value": "3000.00", "confidence": 0.96, "source_quote": "3000.00"},
                "tax_rate": {"value": "10", "confidence": 0.90, "source_quote": "10%"},
                "tax_amount": {"value": "300.00", "confidence": 0.90, "source_quote": "300.00"},
                "gross_amount": {"value": "3300.00", "confidence": 0.90, "source_quote": "3300.00"},
            },
            {
                "description": {"value": "Premium Support Addon", "confidence": 0.92, "source_quote": "Premium Support Addon"},
                "quantity": {"value": "1", "confidence": 0.95, "source_quote": "1"},
                "uom": {"value": "EA", "confidence": 0.90, "source_quote": "EA"},
                "unit_price": {"value": "500.00", "confidence": 0.95, "source_quote": "500.00"},
                "net_amount": {"value": "500.00", "confidence": 0.95, "source_quote": "500.00"},
                "tax_rate": {"value": "10", "confidence": 0.90, "source_quote": "10%"},
                "tax_amount": {"value": "50.00", "confidence": 0.90, "source_quote": "50.00"},
                "gross_amount": {"value": "550.00", "confidence": 0.90, "source_quote": "550.00"},
            },
        ],
        "taxes": [
            {
                "tax_type": {"value": "VAT", "confidence": 0.95, "source_quote": "VAT 10%"},
                "tax_rate": {"value": "10", "confidence": 0.95, "source_quote": "10%"},
                "taxable_amount": {"value": "3500.00", "confidence": 0.95, "source_quote": "3500.00"},
                "tax_amount": {"value": "350.00", "confidence": 0.95, "source_quote": "350.00"},
            }
        ],
        "totals": {
            "subtotal": {"value": "3500.00", "confidence": 0.96, "source_quote": "Subtotal: 3,500.00"},
            "total_tax": {"value": "350.00", "confidence": 0.95, "source_quote": "Total Tax: 350.00"},
            "grand_total": {"value": "3850.00", "confidence": 0.98, "source_quote": "Total: 3,850.00"},
        },
        "payment": {
            "payment_terms": {"value": "Net 30", "confidence": 0.90, "source_quote": "Terms: Net 30"},
            "due_date": {"value": "2026-07-15", "confidence": 0.90, "source_quote": "Due Date: 15/07/2026"},
            "bank_account": {"value": "9876543210", "confidence": 0.90, "source_quote": "Acc: 9876543210"},
        },
        "references": {
            "other_reference": {"value": "REF-ALPHA", "confidence": 0.85, "source_quote": "Ref: REF-ALPHA"},
        },
    }

    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        ctx = ExtractionContext(full_text="Invoice No: INV-2026-101...", document_type="NPO")
        result = extractor.extract(ctx)

        assert result.document_type == "NPO"
        assert result.fields["invoice_number"].value == "INV-2026-101"
        assert result.fields["invoice_date"].value == "2026-06-15"
        assert result.fields["currency"].value == "USD"
        assert result.fields["seller_name"].value == "Apex Technology Corp"
        assert result.fields["buyer_name"].value == "Global Logistics Inc"
        assert result.fields["grand_total_amount"].value == "3850.00"
        assert result.fields["subtotal_net_amount"].value == "3500.00"

        # Line items collection
        line_items = result.fields["line_items"].value
        assert len(line_items) == 2
        assert line_items[0]["description"]["value"] == "Cloud Server Instances"
        assert line_items[0]["quantity"]["value"] == "2"
        assert line_items[0]["net_amount"]["value"] == "3000.00"

        # Canonical dict
        canonical = result.fields["canonical"].value
        assert canonical["totals"]["grand_total"]["value"] == "3850.00"
        assert len(canonical["taxes"]) == 1


# =====================================================================
# 2. Multiple line items
# =====================================================================

def test_02_multiple_line_items(extractor: LLMBasedExtractor):
    """Scenario 2: Multi-line invoice with 3 distinct items, preserving item-level provenance."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-002", "invoice_date": "2026-06-01", "currency": "EUR"},
        "seller": {"name": "European Supplies BV"},
        "buyer": {"name": "Rotterdam Port Auth"},
        "totals": {"grand_total": "4700.00"},
        "line_items": [
            {"description": "Industrial Cable 100m", "quantity": "10", "unit_price": "200.00", "net_amount": "2000.00"},
            {"description": "Junction Boxes", "quantity": "50", "unit_price": "30.00", "net_amount": "1500.00"},
            {"description": "Installation Toolset", "quantity": "4", "unit_price": "300.00", "net_amount": "1200.00"},
        ],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Multi-item invoice text", "NPO")
        items = result.fields["line_items"].value
        assert len(items) == 3
        assert items[0]["description"]["value"] == "Industrial Cable 100m"
        assert items[1]["quantity"]["value"] == "50"
        assert items[2]["net_amount"]["value"] == "1200.00"
        assert result.fields["line_items.1.unit_price"].value == "30.00"


# =====================================================================
# 3. Single line item
# =====================================================================

def test_03_single_line_item(extractor: LLMBasedExtractor):
    """Scenario 3: Exactly one itemized service."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-003", "invoice_date": "2026-06-02", "currency": "USD"},
        "seller": {"name": "Solo Contractor Inc"},
        "buyer": {"name": "Client LLC"},
        "totals": {"grand_total": "1200.00"},
        "line_items": [
            {"description": "Frontend Engineering Sprint", "quantity": "1", "unit_price": "1200.00", "net_amount": "1200.00"},
        ],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Single item invoice text", "NPO")
        items = result.fields["line_items"].value
        assert len(items) == 1
        assert items[0]["description"]["value"] == "Frontend Engineering Sprint"


# =====================================================================
# 4. Zero line items
# =====================================================================

def test_04_zero_line_items(extractor: LLMBasedExtractor):
    """Scenario 4: Invoice where reliable line items are unavailable -> line_items: []."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-004", "invoice_date": "2026-06-03", "currency": "USD"},
        "seller": {"name": "Utility Power Co"},
        "buyer": {"name": "Manufacturing Facility"},
        "totals": {"grand_total": "9450.00"},
        "line_items": [],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Utility power invoice text", "NPO")
        assert result.fields["line_items"].value == []
        assert result.fields["grand_total_amount"].value == "9450.00"


# =====================================================================
# 5. Narrative service invoice
# =====================================================================

def test_05_narrative_service_invoice(extractor: LLMBasedExtractor):
    """Scenario 5: Narrative paragraph invoice with service description and net amount, but null qty/price."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-005", "invoice_date": "2026-06-04", "currency": "USD"},
        "seller": {"name": "Strategy Partners LLP"},
        "buyer": {"name": "Fintech Holdings Corp"},
        "totals": {"grand_total": "25000.00", "subtotal": "25000.00"},
        "line_items": [
            {
                "description": "Executive advisory and corporate governance advisory for Q2 fiscal review",
                "quantity": None,
                "unit_price": None,
                "net_amount": "25000.00",
            }
        ],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Narrative service text", "NPO")
        items = result.fields["line_items"].value
        assert len(items) == 1
        assert items[0]["description"]["value"].startswith("Executive advisory")
        assert items[0]["quantity"]["value"] is None
        assert items[0]["unit_price"]["value"] is None
        assert items[0]["net_amount"]["value"] == "25000.00"


# =====================================================================
# 6. Missing quantity
# =====================================================================

def test_06_missing_quantity(extractor: LLMBasedExtractor):
    """Scenario 6: Line item with unit_price and net_amount but missing quantity does NOT infer quantity=1."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-006", "invoice_date": "2026-06-05", "currency": "USD"},
        "seller": {"name": "Vendor A"},
        "buyer": {"name": "Buyer B"},
        "totals": {"grand_total": "500.00"},
        "line_items": [
            {
                "description": "Software License Seat",
                "quantity": None,  # unstated
                "unit_price": "500.00",
                "net_amount": "500.00",
            }
        ],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Software seat text", "NPO")
        item = result.fields["line_items"].value[0]
        assert item["quantity"]["value"] is None
        assert item["unit_price"]["value"] == "500.00"


# =====================================================================
# 7. Missing unit price
# =====================================================================

def test_07_missing_unit_price(extractor: LLMBasedExtractor):
    """Scenario 7: Line item with quantity and net_amount but missing unit_price does NOT infer unit_price=net."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-007", "invoice_date": "2026-06-06", "currency": "USD"},
        "seller": {"name": "Logistics Co"},
        "buyer": {"name": "Retailer Inc"},
        "totals": {"grand_total": "1800.00"},
        "line_items": [
            {
                "description": "Freight Delivery Run",
                "quantity": "3",
                "unit_price": None,  # unstated unit price
                "net_amount": "1800.00",
            }
        ],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Freight text", "NPO")
        item = result.fields["line_items"].value[0]
        assert item["quantity"]["value"] == "3"
        assert item["unit_price"]["value"] is None
        assert item["net_amount"]["value"] == "1800.00"


# =====================================================================
# 8. Missing tax information
# =====================================================================

def test_08_missing_tax_information(extractor: LLMBasedExtractor):
    """Scenario 8: Absence of tax breakdown returns taxes: [] and null total_tax without hallucinating tax."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-008", "invoice_date": "2026-06-07", "currency": "USD"},
        "seller": {"name": "Exempt Entity"},
        "buyer": {"name": "Tax Exempt NonProfit"},
        "totals": {"grand_total": "7500.00", "subtotal": "7500.00", "total_tax": None},
        "taxes": [],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Tax-exempt text", "NPO")
        assert result.fields["taxes"].value == []
        assert result.fields["total_tax_amount"].value is None


# =====================================================================
# 9. Multiple tax rates
# =====================================================================

def test_09_multiple_tax_rates(extractor: LLMBasedExtractor):
    """Scenario 9: Invoice with multiple tax rates (e.g. 5% and 18% GST)."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-009", "invoice_date": "2026-06-08", "currency": "INR"},
        "seller": {"name": "Tech Suppliers India Pvt Ltd"},
        "buyer": {"name": "Bangalore Enterprise Ltd"},
        "totals": {"grand_total": "11800.00", "total_tax": "1800.00", "subtotal": "10000.00"},
        "taxes": [
            {"tax_type": "CGST", "tax_rate": "9", "taxable_amount": "10000.00", "tax_amount": "900.00"},
            {"tax_type": "SGST", "tax_rate": "9", "taxable_amount": "10000.00", "tax_amount": "900.00"},
        ],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Dual tax invoice text", "NPO")
        taxes = result.fields["taxes"].value
        assert len(taxes) == 2
        assert taxes[0]["tax_type"]["value"] == "CGST"
        assert taxes[0]["tax_amount"]["value"] == "900.00"
        assert taxes[1]["tax_type"]["value"] == "SGST"
        assert taxes[1]["tax_amount"]["value"] == "900.00"


# =====================================================================
# 10. Missing optional seller information
# =====================================================================

def test_10_missing_optional_seller_information(extractor: LLMBasedExtractor):
    """Scenario 10: Seller name is present, but seller.tax_id and seller.address are absent."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-010", "invoice_date": "2026-06-09", "currency": "USD"},
        "seller": {"name": "Freelancer Services", "tax_id": None, "address": None},
        "buyer": {"name": "Client Corp"},
        "totals": {"grand_total": "2000.00"},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Missing seller tax_id/address", "NPO")
        assert result.fields["seller_name"].value == "Freelancer Services"
        assert result.fields["seller_tax_id"].value is None
        assert result.fields["seller_address"].value is None


# =====================================================================
# 11. Missing optional buyer information
# =====================================================================

def test_11_missing_optional_buyer_information(extractor: LLMBasedExtractor):
    """Scenario 11: Buyer name is present, but buyer.tax_id and buyer.address are absent."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-011", "invoice_date": "2026-06-10", "currency": "USD"},
        "seller": {"name": "Office Depot Co"},
        "buyer": {"name": "Anonymous Client", "tax_id": None, "address": None},
        "totals": {"grand_total": "350.00"},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Missing buyer details", "NPO")
        assert result.fields["buyer_name"].value == "Anonymous Client"
        assert result.fields["buyer_tax_id"].value is None
        assert result.fields["buyer_address"].value is None


# =====================================================================
# 12. Missing payment information
# =====================================================================

def test_12_missing_payment_information(extractor: LLMBasedExtractor):
    """Scenario 12: Invoice without payment instructions leaves payment.* fields null."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-012", "invoice_date": "2026-06-11", "currency": "USD"},
        "seller": {"name": "Vendor 12"},
        "buyer": {"name": "Buyer 12"},
        "totals": {"grand_total": "1000.00"},
        "payment": {
            "payment_terms": None,
            "due_date": None,
            "bank_account": None,
            "iban": None,
            "swift_bic": None,
        },
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("No payment info text", "NPO")
        assert result.fields["payment.payment_terms"].value is None
        assert result.fields["payment.due_date"].value is None
        assert result.fields["payment.iban"].value is None


# =====================================================================
# 13. Missing references
# =====================================================================

def test_13_missing_references(extractor: LLMBasedExtractor):
    """Scenario 13: Invoice without purchase order or contract numbers leaves references.* null."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-013", "invoice_date": "2026-06-12", "currency": "USD"},
        "seller": {"name": "Vendor 13"},
        "buyer": {"name": "Buyer 13"},
        "totals": {"grand_total": "1500.00"},
        "references": {"po_number": None, "contract_number": None, "order_number": None},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("No reference info text", "NPO")
        assert result.fields["references.po_number"].value is None
        assert result.fields["references.contract_number"].value is None


# =====================================================================
# 14. Different invoice terminology
# =====================================================================

def test_14_different_invoice_terminology(extractor: LLMBasedExtractor):
    """Scenario 14: Synonym labels (Bill #, Sold By, Billed To, Gross Total) map semantically."""
    mock_payload = {
        "invoice_information": {
            "invoice_number": {"value": "BILL-9081", "confidence": 0.95, "source_quote": "Bill #: BILL-9081"},
            "invoice_date": {"value": "2026-06-13", "confidence": 0.90, "source_quote": "Doc Date: 13-06-2026"},
            "currency": {"value": "GBP", "confidence": 0.90, "source_quote": "£"},
        },
        "seller": {"name": {"value": "London Supplies Ltd", "confidence": 0.92, "source_quote": "Sold By: London Supplies Ltd"}},
        "buyer": {"name": {"value": "Manchester Imports Plc", "confidence": 0.92, "source_quote": "Billed To: Manchester Imports Plc"}},
        "totals": {"grand_total": {"value": "8900.00", "confidence": 0.95, "source_quote": "Gross Total: £8,900.00"}},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Bill # text with synonyms", "NPO")
        assert result.fields["invoice_number"].value == "BILL-9081"
        assert result.fields["seller_name"].value == "London Supplies Ltd"
        assert result.fields["buyer_name"].value == "Manchester Imports Plc"
        assert result.fields["grand_total_amount"].value == "8900.00"


# =====================================================================
# 15. Different layout/ordering
# =====================================================================

def test_15_different_layout_ordering(extractor: LLMBasedExtractor):
    """Scenario 15: Totals appearing at the top and parties at the bottom extracted cleanly."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-TOP-01", "invoice_date": "2026-06-14", "currency": "USD"},
        "seller": {"name": "Headerless Provider"},
        "buyer": {"name": "Footer Client"},
        "totals": {"grand_total": "12500.00", "subtotal": "12500.00"},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Top totals layout text", "NPO")
        assert result.fields["invoice_number"].value == "INV-TOP-01"
        assert result.fields["grand_total_amount"].value == "12500.00"


# =====================================================================
# 16. No hallucinated values
# =====================================================================

def test_16_no_hallucinated_values(extractor: LLMBasedExtractor):
    """Scenario 16: Unmentioned fields MUST remain strictly None with confidence=0.0 and is_found=False."""
    mock_payload = {
        "invoice_information": {
            "invoice_number": "INV-REAL",
            "invoice_date": "2026-06-15",
            "currency": "USD",
            "document_type": None,
        },
        "seller": {"name": "Real Vendor Inc", "tax_id": None, "address": None},
        "buyer": {"name": "Real Buyer Inc", "tax_id": None, "address": None},
        "totals": {"grand_total": "400.00", "subtotal": None, "total_tax": None},
        "payment": {"bank_account": None, "iban": None},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Minimal invoice without optional data", "NPO")
        # Optional unmentioned fields are strictly null
        assert result.fields["seller_tax_id"].value is None
        assert result.fields["seller_tax_id"].confidence == 0.0
        assert not result.fields["seller_tax_id"].is_found

        assert result.fields["buyer_tax_id"].value is None
        assert result.fields["buyer_tax_id"].confidence == 0.0

        assert result.fields["payment.bank_account"].value is None
        assert result.fields["payment.bank_account"].confidence == 0.0


# =====================================================================
# 17. Existing regression invoice (European amounts with spaces and commas)
# =====================================================================

def test_17_existing_regression_invoice(extractor: LLMBasedExtractor):
    """Scenario 17: European format decimal and currency normalizations ('1 394,67' -> '1394.67')."""
    mock_payload = {
        "invoice_information": {"invoice_number": "DE-88912", "invoice_date": "15.06.2026", "currency": "€"},
        "seller": {"name": "Berlin Logistics GmbH"},
        "buyer": {"name": "Munich Auto AG"},
        "totals": {
            "subtotal": "5 640,17",
            "total_tax": "1 071,63",
            "grand_total": "6 711,80",
        },
        "line_items": [
            {
                "description": "Autoteile Set",
                "quantity": "2",
                "unit_price": "2 820,085",
                "net_amount": "5 640,17",
                "tax_rate": "19%",
            }
        ],
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("German invoice text with European formatting", "NPO")

        assert result.fields["currency"].value == "EUR"
        assert result.fields["invoice_date"].value == "2026-06-15"
        assert result.fields["grand_total_amount"].value == "6711.80"
        assert result.fields["subtotal_net_amount"].value == "5640.17"
        assert result.fields["total_tax_amount"].value == "1071.63"

        # Line item amounts normalized
        item = result.fields["line_items"].value[0]
        assert item["net_amount"]["value"] == "5640.17"
        assert item["tax_rate"]["value"] == "19"


# =====================================================================
# 18. Nested output structure
# =====================================================================

def test_18_nested_output_structure(extractor: LLMBasedExtractor):
    """Scenario 18: Canonical output contains all 8 expected domain sections."""
    mock_payload = {
        "invoice_information": {"invoice_number": "INV-NPO-018", "invoice_date": "2026-06-16", "currency": "USD"},
        "seller": {"name": "Section Vendor"},
        "buyer": {"name": "Section Buyer"},
        "totals": {"grand_total": "999.00"},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Section test", "NPO")
        canonical = result.fields["canonical"].value
        required_sections = [
            "invoice_information",
            "seller",
            "buyer",
            "line_items",
            "taxes",
            "totals",
            "payment",
            "references",
        ]
        for sec in required_sections:
            assert sec in canonical, f"Missing section: {sec}"


# =====================================================================
# 19. Mandatory core extraction
# =====================================================================

def test_19_mandatory_core_extraction(extractor: LLMBasedExtractor):
    """Scenario 19: All 6 mandatory core fields are present and valid."""
    mock_payload = {
        "invoice_information": {
            "invoice_number": "CORE-999",
            "invoice_date": "2026-06-17",
            "currency": "USD",
        },
        "seller": {"name": "Core Seller LLC"},
        "buyer": {"name": "Core Buyer LLC"},
        "totals": {"grand_total": "1000.00"},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Core mandatory test", "NPO")
        core_fields = [
            "invoice_number",
            "invoice_date",
            "currency",
            "seller_name",
            "buyer_name",
            "grand_total_amount",
        ]
        for k in core_fields:
            field = result.fields[k]
            assert field.is_found is True
            assert field.value is not None


# =====================================================================
# 20. Confidence & provenance preservation
# =====================================================================

def test_20_confidence_provenance_preservation(extractor: LLMBasedExtractor):
    """Scenario 20: Confidence, provenance='llm', and source_quote are preserved on leaf fields."""
    mock_payload = {
        "invoice_information": {
            "invoice_number": {
                "value": "PROV-001",
                "confidence": 0.97,
                "source_quote": "Invoice Number: PROV-001",
            },
            "invoice_date": {"value": "2026-06-18", "confidence": 0.94, "source_quote": "Date: 2026-06-18"},
            "currency": {"value": "USD", "confidence": 0.90, "source_quote": "$"},
        },
        "seller": {"name": {"value": "Provenance Vendor", "confidence": 0.95, "source_quote": "Provenance Vendor"}},
        "buyer": {"name": {"value": "Provenance Buyer", "confidence": 0.95, "source_quote": "Provenance Buyer"}},
        "totals": {"grand_total": {"value": "777.00", "confidence": 0.98, "source_quote": "Total: $777.00"}},
    }
    with patch.object(extractor, "_call_llm_api", return_value=mock_payload):
        result = extractor.extract("Provenance preservation test", "NPO")
        inv_f = result.fields["invoice_number"]
        assert inv_f.confidence == 0.97
        assert inv_f.matched_text == "Invoice Number: PROV-001"
        assert inv_f.provenance == "llm"

        # Canonical field level provenance
        canon_item = result.fields["invoice_information.invoice_number"]
        assert canon_item.confidence == 0.97
        assert canon_item.matched_text == "Invoice Number: PROV-001"
        assert canon_item.provenance == "llm"
