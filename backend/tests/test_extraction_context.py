"""
Unit and integration tests for Phase 1 ExtractionContext and contract propagation.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.extraction.base import ExtractedField, ExtractionContext, ExtractionResultData
from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.rule_based import RuleBasedExtractor
from app.services.extraction_service import ExtractionService


SAMPLE_POI_TEXT = """
TAX INVOICE
Invoice Number: INV-2024-9988
Invoice Date: 2024-03-15
Total Amount: 1,250.00 EUR
Due Date: 2024-04-15
Vendor: Acme Corp GmbH
"""

SAMPLE_RAW_BLOCKS = [
    {
        "page_number": 1,
        "page_width": 1000.0,
        "page_height": 1400.0,
        "blocks": [
            {
                "text": "TAX INVOICE",
                "confidence": 0.99,
                "bounding_box": [[100, 100], [300, 100], [300, 150], [100, 150]],
            },
            {
                "text": "Invoice Number: INV-2024-9988",
                "confidence": 0.95,
                "bounding_box": [[100, 200], [400, 200], [400, 250], [100, 250]],
            },
        ],
    }
]


def test_extraction_context_instantiation_minimal():
    """Context requires full_text and document_type, while other fields default safely."""
    ctx = ExtractionContext(
        full_text=SAMPLE_POI_TEXT,
        document_type="POI",
    )
    assert ctx.full_text == SAMPLE_POI_TEXT
    assert ctx.document_type == "POI"
    assert ctx.raw_blocks == []
    assert ctx.table_data is None
    assert ctx.normalized_data is None
    assert ctx.ocr_validation is None
    assert ctx.ocr_quality is None


def test_extraction_context_instantiation_full():
    """Context safely holds all OCR-derived structures."""
    dummy_table = {"headers": ["Item"], "line_items": []}
    dummy_norm = {"line_items": []}
    dummy_val = {"is_valid": True, "checks": []}
    dummy_qual = {"overall_score": 0.95}

    ctx = ExtractionContext(
        full_text=SAMPLE_POI_TEXT,
        document_type="POI",
        raw_blocks=SAMPLE_RAW_BLOCKS,
        table_data=dummy_table,
        normalized_data=dummy_norm,
        ocr_validation=dummy_val,
        ocr_quality=dummy_qual,
    )
    assert ctx.raw_blocks == SAMPLE_RAW_BLOCKS
    assert ctx.table_data == dummy_table
    assert ctx.normalized_data == dummy_norm
    assert ctx.ocr_validation == dummy_val
    assert ctx.ocr_quality == dummy_qual


def test_rule_based_extractor_with_context():
    """RuleBasedExtractor works directly with ExtractionContext."""
    extractor = RuleBasedExtractor()
    ctx = ExtractionContext(
        full_text=SAMPLE_POI_TEXT,
        document_type="POI",
        raw_blocks=SAMPLE_RAW_BLOCKS,
    )
    result = extractor.extract(ctx)

    assert isinstance(result, ExtractionResultData)
    assert result.document_type == "POI"
    assert result.fields["invoice_number"].value == "INV-2024-9988"
    assert result.fields["invoice_number"].is_found is True


def test_rule_based_extractor_legacy_signature():
    """RuleBasedExtractor maintains backward compatibility with extract(text, document_type)."""
    extractor = RuleBasedExtractor()
    result = extractor.extract(SAMPLE_POI_TEXT, "POI")

    assert isinstance(result, ExtractionResultData)
    assert result.document_type == "POI"
    assert result.fields["invoice_number"].value == "INV-2024-9988"
    assert result.fields["invoice_number"].is_found is True


def test_rule_based_extractor_keyword_args():
    """RuleBasedExtractor works with keyword arguments."""
    extractor = RuleBasedExtractor()
    ctx = ExtractionContext(full_text=SAMPLE_POI_TEXT, document_type="POI")

    res1 = extractor.extract(context=ctx)
    assert res1.fields["invoice_number"].value == "INV-2024-9988"

    res2 = extractor.extract(text=SAMPLE_POI_TEXT, document_type="POI")
    assert res2.fields["invoice_number"].value == "INV-2024-9988"


def test_llm_based_extractor_with_context_mocked():
    """LLMBasedExtractor accepts ExtractionContext and uses full_text."""
    extractor = LLMBasedExtractor(api_key="mock-key")
    ctx = ExtractionContext(
        full_text=SAMPLE_POI_TEXT,
        document_type="POI",
        raw_blocks=SAMPLE_RAW_BLOCKS,
    )

    mock_llm_response = {
        "invoice_number": {"value": "INV-2024-9988", "confidence": 0.95, "source_quote": "INV-2024-9988"},
        "invoice_date": {"value": "2024-03-15", "confidence": 0.95, "source_quote": "2024-03-15"},
        "total_amount": {"value": "1250.00", "confidence": 0.95, "source_quote": "1,250.00 EUR"},
    }

    with patch.object(extractor, "_call_llm_api", return_value=mock_llm_response) as mock_api:
        result = extractor.extract(ctx)

        assert mock_api.called
        assert SAMPLE_POI_TEXT in mock_api.call_args[1]["user_prompt"]
        assert result.document_type == "POI"
        assert result.fields["invoice_number"].value == "INV-2024-9988"
        assert result.fields["invoice_number"].is_found is True


def test_llm_based_extractor_legacy_signature_mocked():
    """LLMBasedExtractor maintains backward compatibility with legacy signature."""
    extractor = LLMBasedExtractor(api_key="mock-key")

    mock_llm_response = {
        "invoice_number": {"value": "INV-2024-9988", "confidence": 0.95, "source_quote": "INV-2024-9988"},
    }

    with patch.object(extractor, "_call_llm_api", return_value=mock_llm_response):
        result = extractor.extract(SAMPLE_POI_TEXT, "POI")
        assert result.fields["invoice_number"].value == "INV-2024-9988"


def test_llm_based_extractor_fallback_with_context():
    """LLMBasedExtractor falls back cleanly to rule extractor without API key using context."""
    extractor = LLMBasedExtractor(api_key=None)
    ctx = ExtractionContext(
        full_text=SAMPLE_POI_TEXT,
        document_type="POI",
    )
    result = extractor.extract(ctx)
    assert result.engine_name == "llm_based"
    assert result.fields["invoice_number"].value == "INV-2024-9988"


def test_extraction_service_builds_and_passes_context():
    """ExtractionService fetches OCR result and builds ExtractionContext for the engine."""
    mock_db = MagicMock()
    service = ExtractionService(mock_db)

    mock_doc = MagicMock()
    mock_doc.id = 123

    mock_ocr = MagicMock()
    mock_ocr.full_text = SAMPLE_POI_TEXT
    mock_ocr.raw_blocks = SAMPLE_RAW_BLOCKS
    mock_ocr.average_confidence = 0.97
    mock_ocr.page_count = 1

    mock_class = MagicMock()
    mock_class.predicted_type = "POI"

    service.ocr_repo.get_latest_for_document = MagicMock(return_value=mock_ocr)
    service.classification_repo.get_latest_for_document = MagicMock(return_value=mock_class)
    service.extraction_repo.create = MagicMock(return_value=MagicMock(
        document_type="POI",
        fields_found_count=3,
        fields_total_count=5,
    ))

    with patch("app.services.extraction_service.get_extraction_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_engine.extract.return_value = ExtractionResultData(
            document_type="POI",
            fields={"invoice_number": ExtractedField(value="INV-2024-9988", confidence=0.99)},
            engine_name="rule_based",
        )
        mock_get_engine.return_value = mock_engine

        service.extract(mock_doc, engine_name="rule_based")

        # Verify engine.extract was called with ExtractionContext
        assert mock_engine.extract.called
        called_arg = mock_engine.extract.call_args[0][0]
        assert isinstance(called_arg, ExtractionContext)
        assert called_arg.full_text == SAMPLE_POI_TEXT
        assert called_arg.document_type == "POI"
        assert called_arg.raw_blocks == SAMPLE_RAW_BLOCKS
        assert called_arg.table_data is not None
        assert called_arg.normalized_data is not None
        assert called_arg.ocr_validation is not None
        assert called_arg.ocr_quality is not None
