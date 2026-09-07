"""
Dedicated unit and integration tests for Phase 3: LLM Extractor Enhancements & LLMContextBuilder.
"""
from unittest.mock import patch
import pytest

from app.extraction.base import ExtractionContext
from app.extraction.llm_context_builder import LLMContextBuilder
from app.extraction.llm_extractor import LLMBasedExtractor


def test_table_markdown_formatting():
    """Verify table data is converted to clean Markdown table."""
    table_data = {
        "headers": ["Item #", "Description", "Qty", "Unit", "Unit Price", "Net Amount", "Tax %", "Gross Amount"],
        "line_items": [
            {
                "item_number": "1",
                "description": "Dell Latitude 5520",
                "quantity": "2",
                "unit": "pcs",
                "unit_price": "60000.00",
                "net_amount": "120000.00",
                "vat_rate": "18%",
                "gross_amount": "141600.00",
            }
        ],
    }
    md = LLMContextBuilder.format_table_as_markdown(table_data)
    assert md is not None
    assert "| Item # | Description | Qty |" in md
    assert "| 1 | Dell Latitude 5520 | 2 |" in md
    assert "141600.00" in md


def test_party_layout_segmentation():
    """Verify spatial blocks are segmented into Left and Right party sections."""
    raw_blocks = [
        {
            "page_number": 1,
            "page_width": 1000.0,
            "page_height": 1400.0,
            "blocks": [
                {
                    "text": "Acme Vendor Pvt Ltd",
                    "bounding_box": [[100, 100], [300, 100], [300, 140], [100, 140]],
                },
                {
                    "text": "Invoice To: Big Client Corp",
                    "bounding_box": [[600, 100], [850, 100], [850, 140], [600, 140]],
                },
            ],
        }
    ]
    party_text = LLMContextBuilder.format_party_layout(raw_blocks)
    assert party_text is not None
    assert "Left Section (Vendor / Seller / Header):" in party_text
    assert "Acme Vendor Pvt Ltd" in party_text
    assert "Right Section (Customer / Buyer / Summary):" in party_text
    assert "Big Client Corp" in party_text


def test_system_prompt_builder():
    """Verify system prompt includes full schema, types, and grounding rules."""
    sys_prompt = LLMContextBuilder.build_system_prompt("POI")
    assert "document type 'POI'" in sys_prompt
    assert "- invoice_number" in sys_prompt
    assert "- vendor_name" in sys_prompt
    assert "EXTRACTION GUIDELINES:" in sys_prompt
    assert "Dates must be normalized to ISO format (YYYY-MM-DD)" in sys_prompt


def test_user_prompt_builder_full_context():
    """Verify user prompt compiles full text, party layout, table markdown, and quality signals."""
    ctx = ExtractionContext(
        full_text="TAX INVOICE # INV-9988\nTotal: 141600.00",
        document_type="POI",
        raw_blocks=[
            {
                "page_number": 1,
                "page_width": 1000.0,
                "page_height": 1400.0,
                "blocks": [
                    {
                        "text": "Acme Vendor Pvt Ltd",
                        "bounding_box": [[100, 100], [300, 100], [300, 140], [100, 140]],
                    }
                ],
            }
        ],
        table_data={
            "line_items": [
                {
                    "item_number": "1",
                    "description": "Dell Latitude 5520",
                    "quantity": "2",
                    "unit": "pcs",
                    "unit_price": "60000.00",
                    "net_amount": "120000.00",
                    "vat_rate": "18%",
                    "gross_amount": "141600.00",
                }
            ]
        },
        ocr_quality={"overall_score": 0.95, "confidence_score": 0.98},
    )

    user_prompt = LLMContextBuilder.build_user_prompt(ctx)
    assert "=== PRIMARY DOCUMENT OCR TEXT ===" in user_prompt
    assert "TAX INVOICE # INV-9988" in user_prompt
    assert "=== SPATIAL PARTY & HEADER LAYOUT ===" in user_prompt
    assert "Acme Vendor Pvt Ltd" in user_prompt
    assert "=== RECONSTRUCTED LINE ITEMS TABLE ===" in user_prompt
    assert "Dell Latitude 5520" in user_prompt
    assert "=== OCR QUALITY SIGNALS ===" in user_prompt
    assert "Overall Score: 0.95" in user_prompt


def test_llm_extractor_execution_with_context_builder():
    """Verify LLMBasedExtractor compiles rich prompt and parses structured output."""
    extractor = LLMBasedExtractor(api_key="mock-key-phase3")
    ctx = ExtractionContext(
        full_text="INVOICE\nNumber: INV-2026-999\nDate: 15/06/2026\nAmount: 50,000.00 INR",
        document_type="POI",
    )

    mock_llm_response = {
        "invoice_number": {"value": "INV-2026-999", "confidence": 0.98, "source_quote": "Number: INV-2026-999"},
        "invoice_date": {"value": "15/06/2026", "confidence": 0.95, "source_quote": "Date: 15/06/2026"},
        "invoice_amount": {"value": "50,000.00", "confidence": 0.96, "source_quote": "Amount: 50,000.00 INR"},
        "vendor_name": {"value": None, "confidence": 0.0, "source_quote": None},
    }

    with patch.object(extractor, "_call_llm_api", return_value=mock_llm_response) as mock_api:
        res = extractor.extract(ctx)

        assert mock_api.called
        user_arg = mock_api.call_args[1]["user_prompt"]
        assert "=== PRIMARY DOCUMENT OCR TEXT ===" in user_arg
        assert "INVOICE\nNumber: INV-2026-999" in user_arg

        # Verification of field extractions & normalizations
        assert res.fields["invoice_number"].value == "INV-2026-999"
        # Date is normalized to ISO YYYY-MM-DD
        assert res.fields["invoice_date"].value == "2026-06-15"
        # Amount is normalized to plain numeric string
        assert res.fields["invoice_amount"].value == "50000.00"
        assert res.fields["vendor_name"].value is None
        assert res.fields["vendor_name"].is_found is False


def test_llm_extractor_fallback_when_unconfigured():
    """Verify LLMBasedExtractor gracefully falls back to RuleBasedExtractor when no key is set."""
    extractor = LLMBasedExtractor(api_key=None)
    ctx = ExtractionContext(
        full_text="TAX INVOICE\nInvoice Number: INV-FALLBACK-1\nInvoice Date: 2026-02-20",
        document_type="POI",
    )
    res = extractor.extract(ctx)
    assert res.engine_name == "llm_based"
    assert res.fields["invoice_number"].value == "INV-FALLBACK-1"
    assert res.fields["invoice_date"].value == "2026-02-20"
