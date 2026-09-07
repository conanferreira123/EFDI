"""Unit and integration tests for Hybrid LLM + Targeted RAG extraction engine."""
import pytest
from unittest.mock import MagicMock, patch

from app.extraction.base import ExtractedField, ExtractionResultData
from app.extraction.factory import get_extraction_engine, SUPPORTED_EXTRACTORS
from app.extraction.field_schemas import get_full_field_schema
from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.llm_schema import build_dynamic_extraction_model
from app.extraction.primitives import normalize_amount, normalize_date
from app.extraction.rag_diagnostic import RAGDiagnosticService
from app.models.document_chunk import DocumentChunk


def test_dynamic_pydantic_schema_generation():
    """Verify that build_dynamic_extraction_model creates models with all declared schema fields."""
    for doc_type in ["POI", "NPO", "DPR", "IMA", "MSI", "PSI", "JER", "BKA", "LCA"]:
        DynamicModel = build_dynamic_extraction_model(doc_type)
        schema_fields = get_full_field_schema(doc_type)
        model_fields = DynamicModel.model_fields

        assert len(model_fields) == len(schema_fields)
        for f in schema_fields:
            assert f.key in model_fields, f"Field '{f.key}' missing from dynamic model for {doc_type}"


def test_normalizer_date_and_amount():
    """Verify normalize_date and normalize_amount produce correct canonical formats."""
    # Dates
    assert normalize_date("15-06-2026") == "2026-06-15"
    assert normalize_date("21st March 2024") == "2024-03-21"
    assert normalize_date("05-Jun-2026") == "2026-06-05"
    assert normalize_date("2026/08/31") == "2026-08-31"
    assert normalize_date("invalid-date") is None

    # Amounts
    assert normalize_amount("Rs. 25,000.50") == "25000.50"
    assert normalize_amount("$1,234.00") == "1234.00"
    assert normalize_amount("500") == "500"
    assert normalize_amount("N/A") is None


def test_llm_extractor_empty_text():
    """Verify LLMBasedExtractor returns structured null fields when input text is blank."""
    extractor = LLMBasedExtractor()
    result = extractor.extract("", "POI")

    assert result.document_type == "POI"
    assert result.engine_name == "llm_based"
    assert len(result.fields) == len(get_full_field_schema("POI"))
    assert all(not f.is_found for f in result.fields.values())
    assert result.overall_confidence == 0.0


def test_llm_extractor_structured_mock():
    """Verify LLMBasedExtractor maps structured LLM output to ExtractedField dictionary."""
    extractor = LLMBasedExtractor(api_key="mock-api-key")

    mock_llm_json = {
        "invoice_number": {
            "value": "INV-2026-999",
            "confidence": 0.95,
            "source_quote": "Invoice Number: INV-2026-999",
        },
        "invoice_date": {
            "value": "15-06-2026",
            "confidence": 0.90,
            "source_quote": "Invoice Date: 15-06-2026",
        },
        "invoice_amount": {
            "value": "Rs. 50,000.00",
            "confidence": 0.92,
            "source_quote": "Invoice Amount: Rs. 50,000.00",
        },
        "vendor_name": {
            "value": "Acme Global Solutions",
            "confidence": 0.88,
            "source_quote": "Vendor Name: Acme Global Solutions",
        },
    }

    with patch.object(extractor, "_call_llm_api", return_value=mock_llm_json):
        result = extractor.extract("Dummy invoice text", "POI")

        assert result.fields["invoice_number"].value == "INV-2026-999"
        assert result.fields["invoice_date"].value == "2026-06-15"  # normalized date
        assert result.fields["invoice_amount"].value == "50000.00"  # normalized amount
        assert result.fields["vendor_name"].value == "Acme Global Solutions"
        assert result.fields["vendor_name"].matched_text == "Vendor Name: Acme Global Solutions"
        assert result.fields_found_count == 4
        assert result.overall_confidence > 0.85


def test_rag_diagnostic_triggers():
    """Verify RAGDiagnosticService trigger conditions."""
    mock_db = MagicMock()
    service = RAGDiagnosticService(mock_db)

    # 1. Balanced case -> No trigger
    balanced_result = ExtractionResultData(
        document_type="POI",
        fields={
            "net_amount": ExtractedField(value="100.00", confidence=0.9),
            "tax_amount": ExtractedField(value="20.00", confidence=0.9),
            "invoice_amount": ExtractedField(value="120.00", confidence=0.9),
        },
    )
    should_run, reasons = service.should_trigger(balanced_result, page_count=1)
    assert not should_run
    assert len(reasons) == 0

    # 2. Arithmetic mismatch -> Trigger
    imbalanced_result = ExtractionResultData(
        document_type="POI",
        fields={
            "net_amount": ExtractedField(value="100.00", confidence=0.9),
            "tax_amount": ExtractedField(value="20.00", confidence=0.9),
            "invoice_amount": ExtractedField(value="150.00", confidence=0.9),
        },
    )
    should_run, reasons = service.should_trigger(imbalanced_result, page_count=1)
    assert should_run
    assert any("Arithmetic mismatch" in r for r in reasons)

    # 3. Low confidence -> Trigger
    low_conf_result = ExtractionResultData(
        document_type="POI",
        fields={
            "vendor_name": ExtractedField(value="Acme", confidence=0.45),
        },
    )
    should_run, reasons = service.should_trigger(low_conf_result, page_count=1)
    assert should_run
    assert any("Low extraction confidence" in r for r in reasons)


def test_factory_engine_registration():
    """Verify factory returns appropriate engine instances."""
    assert "rule_based" in SUPPORTED_EXTRACTORS
    assert "llm_based" in SUPPORTED_EXTRACTORS
    assert "llm_rag" in SUPPORTED_EXTRACTORS

    rule_eng = get_extraction_engine("rule_based")
    assert rule_eng.name == "rule_based"

    llm_eng = get_extraction_engine("llm_based")
    assert llm_eng.name == "llm_based"
