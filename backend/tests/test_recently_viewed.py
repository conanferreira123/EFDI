"""
Tests for the Recently Viewed feature on the Documents page.

Verifies:
1. A new user has no Recently Viewed documents.
2. Opening a document records activity.
3. Reopening the same document updates its activity rather than creating a duplicate.
4. OCR user action records activity.
5. Classification user action records activity.
6. Extraction user action records activity.
7. Validation user action records activity.
8. Document-level Ask AI interaction records activity.
9. Background processing does not update activity.
10. Different users have independent Recently Viewed lists.
11. Maximum 5 documents are returned.
12. Documents are ordered by latest activity.
13. Duplicate documents are not displayed.
14. Existing authorization is respected (analysts only see their uploads).
15. Inaccessible/soft-deleted documents do not appear.
16. Existing Documents page behavior remains unchanged.
"""
import io
import time
import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.database.session import get_db_context
from app.main import app
from app.models.document_user_activity import DocumentUserActivity
from app.models.roles import UserRole
from app.services.rag_ingestion_service import RAGIngestionService

client = TestClient(app)


def _unique_username(prefix: str = "user") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_login(role: str = "FINANCE_ANALYST", prefix: str = "rv_user") -> tuple[str, dict]:
    username = _unique_username(prefix)
    password = "TestPassword123!"
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
    user = register_response.json()

    login_response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login_response.status_code == 200, login_response.text
    token = login_response.json()["access_token"]
    return token, user


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _minimal_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF"
    )


def _upload_doc(token: str, filename: str = "test.pdf") -> dict:
    res = client.post(
        "/api/v1/documents/upload",
        headers=_auth_header(token),
        files={"file": (filename, io.BytesIO(_minimal_pdf_bytes()), "application/pdf")},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_new_user_has_no_recently_viewed():
    """Requirement 1: A new user has no Recently Viewed documents."""
    token, _ = _register_and_login()
    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    assert res.status_code == 200
    assert res.json() == []


def test_opening_document_records_activity():
    """Requirement 2: Opening a document via GET /documents/{id} records activity."""
    token, _ = _register_and_login()
    doc = _upload_doc(token, "invoice_alpha.pdf")

    # Before opening, recently viewed is empty
    res_before = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    assert res_before.status_code == 200
    assert res_before.json() == []

    # Open the document
    open_res = client.get(f"/api/v1/documents/{doc['id']}", headers=_auth_header(token))
    assert open_res.status_code == 200

    # Now it appears in recently viewed
    res_after = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    assert res_after.status_code == 200
    items = res_after.json()
    assert len(items) == 1
    assert items[0]["id"] == doc["id"]
    assert items[0]["original_filename"] == "invoice_alpha.pdf"


def test_reopening_same_document_updates_activity_and_no_duplicates():
    """Requirements 3, 12, 13: Reopening updates last_activity_at and changes ordering without duplicates."""
    token, _ = _register_and_login()
    doc1 = _upload_doc(token, "doc_1.pdf")
    doc2 = _upload_doc(token, "doc_2.pdf")

    # Open doc1, then doc2
    client.get(f"/api/v1/documents/{doc1['id']}", headers=_auth_header(token))
    time.sleep(0.05)
    client.get(f"/api/v1/documents/{doc2['id']}", headers=_auth_header(token))

    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    items = res.json()
    assert len(items) == 2
    assert [i["id"] for i in items] == [doc2["id"], doc1["id"]]

    # Re-open doc1
    time.sleep(0.05)
    client.get(f"/api/v1/documents/{doc1['id']}", headers=_auth_header(token))

    # doc1 should now be at the top, and still only 2 items total (no duplicate)
    res2 = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    items2 = res2.json()
    assert len(items2) == 2
    assert [i["id"] for i in items2] == [doc1["id"], doc2["id"]]


def test_ocr_user_action_records_activity():
    """Requirement 4: OCR user action records activity."""
    token, _ = _register_and_login()
    doc = _upload_doc(token, "doc_ocr.pdf")

    # Run OCR with stub engine
    ocr_res = client.post(
        f"/api/v1/ocr/documents/{doc['id']}/run",
        headers=_auth_header(token),
        json={"engine": "stub"},
    )
    assert ocr_res.status_code == 201

    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == doc["id"]


def test_classification_user_action_records_activity():
    """Requirement 5: Classification user action records activity."""
    token, _ = _register_and_login()
    doc = _upload_doc(token, "doc_cls.pdf")

    # Run OCR first so classification can run
    client.post(
        f"/api/v1/ocr/documents/{doc['id']}/run",
        headers=_auth_header(token),
        json={"engine": "stub"},
    )

    # Re-verify classification triggers activity
    cls_res = client.post(
        f"/api/v1/classification/documents/{doc['id']}/classify",
        headers=_auth_header(token),
        json={},
    )
    assert cls_res.status_code == 201

    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == doc["id"]


def test_extraction_user_action_records_activity():
    """Requirement 6: Extraction user action records activity."""
    token, _ = _register_and_login()
    doc = _upload_doc(token, "doc_ext.pdf")

    client.post(
        f"/api/v1/ocr/documents/{doc['id']}/run",
        headers=_auth_header(token),
        json={"engine": "stub"},
    )
    client.post(
        f"/api/v1/classification/documents/{doc['id']}/classify",
        headers=_auth_header(token),
        json={},
    )

    ext_res = client.post(
        f"/api/v1/extraction/documents/{doc['id']}/extract",
        headers=_auth_header(token),
        json={"engine": "rule_based"},
    )
    assert ext_res.status_code == 201

    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == doc["id"]


def test_validation_user_action_records_activity():
    """Requirement 7: Validation user action records activity."""
    token, _ = _register_and_login()
    doc = _upload_doc(token, "doc_val.pdf")

    client.post(
        f"/api/v1/ocr/documents/{doc['id']}/run",
        headers=_auth_header(token),
        json={"engine": "stub"},
    )
    client.post(
        f"/api/v1/classification/documents/{doc['id']}/classify",
        headers=_auth_header(token),
        json={},
    )
    client.post(
        f"/api/v1/extraction/documents/{doc['id']}/extract",
        headers=_auth_header(token),
        json={"engine": "rule_based"},
    )

    val_res = client.post(
        f"/api/v1/validation/documents/{doc['id']}/validate",
        headers=_auth_header(token),
        json={},
    )
    assert val_res.status_code == 201

    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == doc["id"]


def test_document_chatbot_records_activity():
    """Requirement 8: Document-level Ask AI / chatbot interaction records activity."""
    token, _ = _register_and_login()
    doc = _upload_doc(token, "doc_chat.pdf")

    # Send a document chat message
    chat_res = client.post(
        f"/api/v1/chat/documents/{doc['id']}/messages",
        headers=_auth_header(token),
        json={"message": "What is the payment discount on this document?"},
    )
    assert chat_res.status_code == 200

    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == doc["id"]


def test_background_processing_does_not_update_activity():
    """Requirement 9: Background processing (RAG ingestion, chunking) does not update activity."""
    token, user = _register_and_login()
    doc = _upload_doc(token, "doc_bg.pdf")

    # Run background RAG ingestion directly (service-level call)
    ingestion_service = RAGIngestionService()
    ingestion_res = ingestion_service.ingest_document(doc["id"])
    assert ingestion_res["status"] in ("success", "skipped")

    # Verify no activity record was created by background ingestion
    with get_db_context() as session:
        activity = session.query(DocumentUserActivity).filter_by(
            user_id=user["id"], document_id=doc["id"]
        ).first()
        assert activity is None

    res = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token))
    assert res.json() == []


def test_independent_users_and_limit_5():
    """Requirements 10, 11, 12: Independent users and max 5 documents returned in correct order."""
    token_a, user_a = _register_and_login(prefix="user_a")
    token_b, user_b = _register_and_login(prefix="user_b")

    # User A uploads and opens 6 documents
    docs_a = []
    for i in range(1, 7):
        d = _upload_doc(token_a, f"user_a_doc_{i}.pdf")
        time.sleep(0.02)
        client.get(f"/api/v1/documents/{d['id']}", headers=_auth_header(token_a))
        docs_a.append(d)

    # User A's recently viewed should return exactly 5, latest first (doc 6 down to doc 2)
    res_a = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token_a))
    assert res_a.status_code == 200
    items_a = res_a.json()
    assert len(items_a) == 5
    expected_ids_a = [docs_a[i]["id"] for i in range(5, 0, -1)]  # doc 6, 5, 4, 3, 2
    assert [i["id"] for i in items_a] == expected_ids_a

    # User B should have 0 recently viewed
    res_b = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token_b))
    assert res_b.json() == []

    # User B uploads and opens 1 document
    doc_b = _upload_doc(token_b, "user_b_doc.pdf")
    client.get(f"/api/v1/documents/{doc_b['id']}", headers=_auth_header(token_b))

    res_b2 = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token_b))
    items_b = res_b2.json()
    assert len(items_b) == 1
    assert items_b[0]["id"] == doc_b["id"]

    # User A's list remains unchanged
    res_a2 = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token_a))
    assert [i["id"] for i in res_a2.json()] == expected_ids_a


def test_authorization_and_soft_delete_filtered_out():
    """Requirements 14, 15: Existing authorization is respected; inaccessible/deleted docs filtered out."""
    token_analyst_1, user_analyst_1 = _register_and_login("FINANCE_ANALYST", prefix="analyst_1")
    token_analyst_2, user_analyst_2 = _register_and_login("FINANCE_ANALYST", prefix="analyst_2")

    doc1 = _upload_doc(token_analyst_1, "private_doc.pdf")
    # Analyst 1 opens doc1
    client.get(f"/api/v1/documents/{doc1['id']}", headers=_auth_header(token_analyst_1))

    # Analyst 2 attempts to open doc1 -> 403 Forbidden
    forbidden_res = client.get(f"/api/v1/documents/{doc1['id']}", headers=_auth_header(token_analyst_2))
    assert forbidden_res.status_code == 403

    # Even if an activity row existed in the database for Analyst 2 on doc1,
    # recently-viewed must NOT return it because Analyst 2 does not have access!
    with get_db_context() as session:
        manual_activity = DocumentUserActivity(
            user_id=user_analyst_2["id"],
            document_id=doc1["id"],
            last_activity_at=datetime.now(timezone.utc),
        )
        session.add(manual_activity)
        session.commit()

    res_analyst_2 = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token_analyst_2))
    assert res_analyst_2.status_code == 200
    # Must NOT include doc1 because Analyst 2 did not upload it
    assert res_analyst_2.json() == []

    # Soft-deletion test: Analyst 1 deletes doc1
    del_res = client.delete(f"/api/v1/documents/{doc1['id']}", headers=_auth_header(token_analyst_1))
    assert del_res.status_code == 200

    # Analyst 1's recently-viewed must now exclude deleted doc1
    res_analyst_1 = client.get("/api/v1/documents/recently-viewed", headers=_auth_header(token_analyst_1))
    assert res_analyst_1.status_code == 200
    assert res_analyst_1.json() == []


def test_existing_documents_page_behavior_unchanged():
    """Requirement 16: Existing documents listing endpoint continues to work normally."""
    token, _ = _register_and_login()
    d1 = _upload_doc(token, "list_test_1.pdf")
    d2 = _upload_doc(token, "list_test_2.pdf")

    res = client.get("/api/v1/documents", headers=_auth_header(token))
    assert res.status_code == 200
    body = res.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 2
    filenames = [item["original_filename"] for item in body["items"]]
    assert "list_test_1.pdf" in filenames
    assert "list_test_2.pdf" in filenames
