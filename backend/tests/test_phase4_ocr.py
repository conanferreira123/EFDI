"""
Phase 4 verification tests: OCR engine.

These tests exercise the full, real pipeline (PDF rasterization via
PyMuPDF, OpenCV preprocessing, persistence, status transitions, API
endpoints) using the StubOCREngine as the OCR backend, since PaddleOCR
and EasyOCR's model weights are not downloadable in this network-
restricted environment (see app/ocr/paddle_engine.py and
app/ocr/easyocr_engine.py docstrings for details). The pipeline code
exercised here is identical regardless of which engine is plugged in;
only the engine's extract_text_blocks() implementation differs.
"""
import io
import uuid

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.ocr.base import OCREngine, OCRTextBlock
from app.ocr.factory import get_engine_status, get_ocr_engine
from app.ocr.preprocessing import deskew, load_image_bytes, rasterize_pdf
from app.ocr.stub_engine import StubOCREngine

client = TestClient(app)


def _unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "ocruser") -> str:
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


def _solid_png_bytes(color=(255, 255, 255), size=(100, 80)) -> bytes:
    """Generate a minimal valid PNG without needing the Pillow dependency at import time."""
    from PIL import Image

    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _upload(token: str, filename: str, content: bytes, content_type: str = "application/pdf") -> int:
    response = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": (filename, io.BytesIO(content), content_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- Preprocessing: PyMuPDF rasterization ---

def test_rasterize_pdf_returns_one_page_per_pdf_page():
    pages = rasterize_pdf(_minimal_pdf_bytes())
    assert len(pages) == 1
    assert pages[0].ndim == 3  # BGR image
    assert pages[0].shape[2] == 3


def test_rasterize_pdf_respects_dpi():
    pages_low = rasterize_pdf(_minimal_pdf_bytes(), dpi=72)
    pages_high = rasterize_pdf(_minimal_pdf_bytes(), dpi=200)
    # Higher DPI must produce a larger raster for the same page size.
    assert pages_high[0].shape[0] > pages_low[0].shape[0]
    assert pages_high[0].shape[1] > pages_low[0].shape[1]


def test_rasterize_invalid_pdf_raises_clear_error():
    import pytest
    from app.core.exceptions import FileProcessingException

    with pytest.raises(FileProcessingException):
        rasterize_pdf(b"this is not a pdf at all")


# --- Preprocessing: image loading ---

def test_load_image_bytes_returns_bgr_array():
    png_bytes = _solid_png_bytes()
    image = load_image_bytes(png_bytes)
    assert image.ndim == 3
    assert image.shape[2] == 3


# --- Preprocessing: deskew ---

def test_deskew_modifies_rotated_image():
    import cv2

    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    for y in range(30, 170, 20):
        cv2.line(img, (20, y), (280, y), (0, 0, 0), 6)

    matrix = cv2.getRotationMatrix2D((150, 100), 8, 1.0)
    rotated = cv2.warpAffine(img, matrix, (300, 200), borderValue=(255, 255, 255))

    corrected = deskew(rotated)
    assert corrected.shape == rotated.shape
    assert not np.array_equal(corrected, rotated)


def test_deskew_skips_blank_image():
    blank = np.full((100, 100, 3), 255, dtype=np.uint8)
    result = deskew(blank)
    # Should return unchanged (not enough foreground pixels to estimate angle).
    assert np.array_equal(result, blank)


# --- Engine factory ---

def test_factory_returns_stub_engine():
    engine = get_ocr_engine("stub")
    assert isinstance(engine, OCREngine)
    assert engine.name == "stub"


def test_factory_rejects_unknown_engine():
    import pytest
    from app.core.exceptions import ValidationFailedException

    with pytest.raises(ValidationFailedException):
        get_ocr_engine("not_a_real_engine")


def test_factory_returns_same_singleton_instance():
    engine_a = get_ocr_engine("stub")
    engine_b = get_ocr_engine("stub")
    assert engine_a is engine_b


def test_engine_status_reports_all_supported_engines():
    # PaddleOCR is deliberately excluded from SUPPORTED_ENGINES --
    # instantiating/running it segfaults the process on this
    # deployment's ARM64 hardware (a native crash, not a catchable
    # exception), so it must never be reachable via the API. EasyOCR
    # is the supported production engine.
    status = get_engine_status()
    assert "docling" in status
    assert status["docling"]["is_production_engine"] is True
    assert status["stub"]["available"] is True
    assert status["stub"]["is_production_engine"] is False
    assert status["easyocr"]["is_production_engine"] is True


# --- Stub engine behavior ---

def test_stub_engine_is_deterministic_for_same_image():
    engine = StubOCREngine()
    image = np.zeros((50, 50, 3), dtype=np.uint8)
    blocks_a = engine.extract_text_blocks(image)
    blocks_b = engine.extract_text_blocks(image)
    assert blocks_a[0].text == blocks_b[0].text


def test_stub_engine_differs_for_different_images():
    engine = StubOCREngine()
    image_a = np.zeros((50, 50, 3), dtype=np.uint8)
    image_b = np.full((50, 50, 3), 255, dtype=np.uint8)
    blocks_a = engine.extract_text_blocks(image_a)
    blocks_b = engine.extract_text_blocks(image_b)
    assert blocks_a[0].text != blocks_b[0].text


def test_stub_engine_returns_valid_text_block():
    engine = StubOCREngine()
    image = np.zeros((50, 50, 3), dtype=np.uint8)
    blocks = engine.extract_text_blocks(image)
    assert len(blocks) == 1
    assert isinstance(blocks[0], OCRTextBlock)
    assert 0.0 <= blocks[0].confidence <= 1.0
    assert len(blocks[0].bounding_box) == 4


# --- Full pipeline via API (stub engine) ---

def test_ocr_engines_endpoint_is_public_and_reports_status():
    response = client.get("/api/v1/ocr/engines")
    assert response.status_code == 200
    body = response.json()
    assert "stub" in body["engines"]
    assert body["default_engine"] == "docling"


def test_run_ocr_with_stub_engine_succeeds_and_advances_status():
    token = _register_and_login()
    document_id = _upload(token, "ocr_test.pdf", _minimal_pdf_bytes())

    run_response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token),
        json={"engine": "stub"},
    )
    assert run_response.status_code == 201, run_response.text
    body = run_response.json()
    assert body["engine_name"] == "stub"
    assert body["is_stub_result"] is True
    assert body["page_count"] == 1
    assert "STUB OCR OUTPUT" in body["full_text"]

    doc_response = client.get(f"/api/v1/documents/{document_id}", headers=_auth_header(token))
    assert doc_response.json()["status"] == "OCR_COMPLETED"


def test_get_latest_ocr_result_after_run():
    token = _register_and_login(prefix="ocrlatest")
    document_id = _upload(token, "latest_test.pdf", _minimal_pdf_bytes())

    client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token),
        json={"engine": "stub"},
    )

    response = client.get(
        f"/api/v1/ocr/documents/{document_id}/result", headers=_auth_header(token)
    )
    assert response.status_code == 200
    assert response.json()["document_id"] == document_id


def test_get_ocr_result_before_any_run_returns_404():
    token = _register_and_login(prefix="ocrnorun")
    document_id = _upload(token, "no_ocr_yet.pdf", _minimal_pdf_bytes())

    response = client.get(
        f"/api/v1/ocr/documents/{document_id}/result", headers=_auth_header(token)
    )
    assert response.status_code == 404


def test_list_ocr_results_shows_multiple_runs():
    token = _register_and_login(prefix="ocrmulti")
    document_id = _upload(token, "multi_run.pdf", _minimal_pdf_bytes())

    client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token), json={"engine": "stub"},
    )
    client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token), json={"engine": "stub"},
    )

    response = client.get(
        f"/api/v1/ocr/documents/{document_id}/results", headers=_auth_header(token)
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_run_ocr_respects_document_access_scoping():
    """A FINANCE_ANALYST must not be able to run OCR on someone else's document."""
    owner_token = _register_and_login(prefix="ocrowner")
    other_token = _register_and_login(prefix="ocrother")

    document_id = _upload(owner_token, "owned.pdf", _minimal_pdf_bytes())

    response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(other_token),
        json={"engine": "stub"},
    )
    assert response.status_code == 403


def test_run_ocr_on_image_document():
    token = _register_and_login(prefix="ocrimage")
    document_id = _upload(
        token, "receipt.png", _solid_png_bytes(), content_type="image/png"
    )

    response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token),
        json={"engine": "stub"},
    )
    assert response.status_code == 201
    assert response.json()["page_count"] == 1


def test_run_ocr_with_unknown_engine_name_returns_422():
    token = _register_and_login(prefix="ocrbadengine")
    document_id = _upload(token, "bad_engine.pdf", _minimal_pdf_bytes())

    response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token),
        json={"engine": "definitely_not_a_real_engine"},
    )
    assert response.status_code == 422


def test_run_ocr_requesting_paddleocr_is_rejected_not_crashed():
    """
    PaddleOCR is excluded from SUPPORTED_ENGINES: actually instantiating
    and running it segfaults the whole process on this deployment's
    ARM64 hardware (confirmed via direct reproduction -- exit code 139,
    a native crash that no Python try/except can catch). A request
    naming it must therefore be rejected up front, before the engine is
    ever touched -- not attempted-and-caught. This is what keeps the
    request-handling worker alive for every other in-flight request.
    """
    token = _register_and_login(prefix="ocrpaddlecheck")
    document_id = _upload(token, "paddle_check.pdf", _minimal_pdf_bytes())

    response = client.post(
        f"/api/v1/ocr/documents/{document_id}/run",
        headers=_auth_header(token),
        json={"engine": "paddleocr"},
    )
    # Must not be a 500, and must not attempt to instantiate the engine
    # at all -- rejected as an unknown/unsupported engine name instead.
    assert response.status_code == 422
    assert response.json()["error"] == "ValidationFailedException"
