"""
Integration tests for PaddleOCR-VL-1.6 Target Architecture in EFDI.

Verifies:
1. Engine registration & availability in OCR factory.
2. Direct PDF / file processing without PyMuPDF rasterization or OpenCV preprocessing.
3. Runtime-only Markdown table parsing (table_data is NEVER persisted in DB).
4. Business validation on Markdown table output.
5. ExtractionContext consumption of runtime table_data.
6. Backward compatibility for legacy EasyOCR records.
7. Zero database migrations / schema modifications.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.ocr_result import OCRResult
from app.ocr.base import OCRPageResult, OCRResult as OCRResultData, OCRTextBlock
from app.ocr.factory import PRODUCTION_ENGINES, SUPPORTED_ENGINES, get_engine_status, get_ocr_engine
from app.ocr.markdown_table_parser import parse_markdown_table
from app.ocr.paddle_vl_engine import PaddleOCRVLEngine
from app.routers.ocr import _to_response
from app.services.extraction_service import ExtractionService
from app.services.ocr_service import OCRService


SAMPLE_PADDLE_MARKDOWN = """# INVOICE

Invoice Number: INV-98765
Invoice Date: 2026-09-15
Vendor: Apex Solutions Inc.

| Item Description | Quantity | Unit Price | Amount |
| :--- | :--- | :--- | :--- |
| Professional Consulting | 10 | 150.00 | 1500.00 |
| Cloud Infrastructure Setup | 1 | 850.00 | 850.00 |
| Security Assessment | 2 | 500.00 | 1000.00 |

Subtotal: 3350.00
Tax (10%): 335.00
Total Due: 3685.00
"""


def test_paddleocr_vl_factory_registration():
    """Verify paddleocr-vl-1.6 is registered as a legacy supported engine."""
    assert "paddleocr-vl-1.6" in SUPPORTED_ENGINES

    engine = get_ocr_engine("paddleocr-vl-1.6")
    assert isinstance(engine, PaddleOCRVLEngine)
    assert engine.name == "paddleocr-vl-1.6"

    status = get_engine_status()
    assert "paddleocr-vl-1.6" in status
    assert status["paddleocr-vl-1.6"]["is_production_engine"] is False
    assert status["paddleocr-vl-1.6"]["available"] is True


def test_markdown_table_parser_runtime_line_items():
    """Verify native Markdown table parsing produces clean in-memory table_data without spatial heuristics."""
    table_data = parse_markdown_table(SAMPLE_PADDLE_MARKDOWN)

    assert table_data is not None
    assert "headers" in table_data
    assert "line_items" in table_data
    assert len(table_data["line_items"]) == 3

    item1 = table_data["line_items"][0]
    assert item1["description"] == "Professional Consulting"
    assert item1["quantity"] == "10"
    assert item1["unit_price"] == "150.00"
    assert item1["net_amount"] == "1500.00"

    item2 = table_data["line_items"][1]
    assert item2["description"] == "Cloud Infrastructure Setup"
    assert item2["quantity"] == "1"
    assert item2["unit_price"] == "850.00"
    assert item2["net_amount"] == "850.00"


def test_ocr_service_run_paddleocr_vl_bypasses_rasterization():
    """
    Verify OCRService with paddleocr-vl-1.6:
    1. Directly calls extract_from_file (no PyMuPDF rasterize_pdf).
    2. Runs business validation on parsed Markdown table.
    3. Persists OCRResult using standard database schema (no extra columns).
    """
    mock_db = MagicMock()
    ocr_service = OCRService(mock_db)

    doc = Document(
        id=42,
        stored_filename="test_invoice.pdf",
        mime_type="application/pdf",
        status=DocumentStatus.UPLOADED.value,
    )

    mock_engine = MagicMock()
    mock_engine.name = "paddleocr-vl-1.6"
    fake_result_data = OCRResultData(engine_name="paddleocr-vl-1.6")
    fake_result_data.custom_full_text = SAMPLE_PADDLE_MARKDOWN
    fake_result_data.pages.append(
        OCRPageResult(
            page_number=1,
            blocks=[OCRTextBlock(text="INVOICE", confidence=0.99, bounding_box=[[0, 0], [10, 0], [10, 10], [0, 10]])]
        )
    )
    mock_engine.extract_from_file.return_value = fake_result_data

    # Mock file path existence
    mock_path = MagicMock()
    mock_path.exists.return_value = True

    with patch("app.services.ocr_service.get_file_path", return_value=mock_path), \
         patch("app.services.ocr_service.get_ocr_engine", return_value=mock_engine), \
         patch("app.services.ocr_service.rasterize_pdf") as mock_rasterize, \
         patch("app.services.ocr_service.AdaptivePreprocessor.process") as mock_preprocess, \
         patch.object(ocr_service.ocr_repo, "create") as mock_create_ocr, \
         patch.object(ocr_service.document_repo, "update_status") as mock_update_status, \
         patch("app.services.ocr_service.AuditService"):

        fake_saved_ocr = OCRResult(
            id=101,
            document_id=42,
            engine_name="paddleocr-vl-1.6",
            full_text=SAMPLE_PADDLE_MARKDOWN,
            page_count=1,
            average_confidence=0.99,
        )
        mock_create_ocr.return_value = fake_saved_ocr

        result = ocr_service.run_ocr(doc, engine_name="paddleocr-vl-1.6")

        # Must call extract_from_file directly with the file path
        mock_engine.extract_from_file.assert_called_once_with(mock_path)

        # Must NOT call PyMuPDF rasterize_pdf or AdaptivePreprocessor
        mock_rasterize.assert_not_called()
        mock_preprocess.assert_not_called()

        # Database creation must use standard OCRResult schema
        mock_create_ocr.assert_called_once()
        create_kwargs = mock_create_ocr.call_args.kwargs
        assert create_kwargs["document_id"] == 42
        assert create_kwargs["engine_name"] == "paddleocr-vl-1.6"
        assert create_kwargs["full_text"] == SAMPLE_PADDLE_MARKDOWN
        assert "table_data" not in create_kwargs  # MUST NOT persist table_data
        assert "model_version" not in create_kwargs
        assert "layout_data" not in create_kwargs

        assert result.full_text == SAMPLE_PADDLE_MARKDOWN


def test_extraction_service_paddleocr_vl_runtime_table_data():
    """Verify ExtractionService parses Markdown table into in-memory table_data without spatial heuristics."""
    mock_db = MagicMock()
    extraction_service = ExtractionService(mock_db)

    doc = Document(id=1, stored_filename="inv.pdf", status=DocumentStatus.OCR_COMPLETED.value)

    mock_ocr_result = OCRResult(
        id=1,
        document_id=1,
        engine_name="paddleocr-vl-1.6",
        full_text=SAMPLE_PADDLE_MARKDOWN,
        page_count=1,
        average_confidence=0.98,
        raw_blocks=[],
    )
    mock_class_result = MagicMock()
    mock_class_result.predicted_type = "invoice"

    extraction_service.ocr_repo.get_latest_for_document = MagicMock(return_value=mock_ocr_result)
    extraction_service.classification_repo.get_latest_for_document = MagicMock(return_value=mock_class_result)

    mock_engine = MagicMock()
    mock_extracted_result = MagicMock()
    mock_extracted_result.fields = {}
    mock_extracted_result.line_items = []
    mock_engine.extract.return_value = mock_extracted_result

    with patch("app.services.extraction_service.get_extraction_engine", return_value=mock_engine), \
         patch("app.services.extraction_service.reconstruct_table") as mock_legacy_reconstruct, \
         patch.object(extraction_service.extraction_repo, "create"):

        extraction_service.extract(doc, engine_name="rule_based")

        # Verify legacy spatial reconstruct_table was NOT called
        mock_legacy_reconstruct.assert_not_called()

        # Verify ExtractionContext was populated with runtime parsed table_data
        mock_engine.extract.assert_called_once()
        context = mock_engine.extract.call_args[0][0]
        assert context.full_text == SAMPLE_PADDLE_MARKDOWN
        assert context.table_data is not None
        assert len(context.table_data["line_items"]) == 3
        assert context.table_data["line_items"][0]["description"] == "Professional Consulting"
        assert context.normalized_data is not None
        assert len(context.normalized_data["line_items"]) == 3


def test_extraction_service_legacy_easyocr_fallback():
    """Verify ExtractionService maintains backward compatibility for legacy EasyOCR records."""
    mock_db = MagicMock()
    extraction_service = ExtractionService(mock_db)

    doc = Document(id=2, stored_filename="legacy.pdf", status=DocumentStatus.OCR_COMPLETED.value)

    mock_ocr_result = OCRResult(
        id=2,
        document_id=2,
        engine_name="easyocr",
        full_text="Invoice text with legacy blocks",
        page_count=1,
        average_confidence=0.90,
        raw_blocks=[{"page_number": 1, "page_width": 1000.0, "page_height": 1400.0, "blocks": [{"text": "Item", "confidence": 0.9, "bounding_box": [[0, 0], [10, 0], [10, 10], [0, 10]]}]}],
    )
    mock_class_result = MagicMock()
    mock_class_result.predicted_type = "invoice"

    extraction_service.ocr_repo.get_latest_for_document = MagicMock(return_value=mock_ocr_result)
    extraction_service.classification_repo.get_latest_for_document = MagicMock(return_value=mock_class_result)

    mock_engine = MagicMock()
    mock_extracted_result = MagicMock()
    mock_extracted_result.fields = {}
    mock_extracted_result.line_items = []
    mock_engine.extract.return_value = mock_extracted_result

    with patch("app.services.extraction_service.get_extraction_engine", return_value=mock_engine), \
         patch("app.services.extraction_service.reconstruct_table") as mock_legacy_reconstruct, \
         patch.object(extraction_service.extraction_repo, "create"):

        mock_legacy_table = MagicMock()
        mock_legacy_table.to_dict.return_value = {"headers": ["Item"], "line_items": []}
        mock_legacy_reconstruct.return_value = mock_legacy_table

        extraction_service.extract(doc, engine_name="rule_based")

        # Verify legacy spatial reconstruct_table WAS called for EasyOCR
        mock_legacy_reconstruct.assert_called_once()


def test_ocr_router_to_response_dynamic_markdown_parsing():
    """Verify API response _to_response dynamically constructs table_data from Markdown without DB columns."""
    now = datetime.now(timezone.utc)
    ocr_result = OCRResult(
        id=99,
        document_id=12,
        engine_name="paddleocr-vl-1.6",
        full_text=SAMPLE_PADDLE_MARKDOWN,
        page_count=1,
        average_confidence=0.97,
        processing_time_ms=450,
        raw_blocks=[],
        created_at=now,
        updated_at=now,
    )

    with patch("app.routers.ocr.reconstruct_table") as mock_legacy_reconstruct:
        response = _to_response(ocr_result)

        # Legacy spatial reconstruction must not be invoked
        mock_legacy_reconstruct.assert_not_called()

        assert response.engine_name == "paddleocr-vl-1.6"
        assert response.table_data is not None
        assert len(response.table_data["line_items"]) == 3
        assert response.normalized_data is not None
        assert len(response.normalized_data["line_items"]) == 3
        assert response.validation_results is not None
        assert response.quality_score is not None
