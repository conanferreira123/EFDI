"""Seeded evaluation dataset fixture for Global Chatbot baseline and e2e testing.

Provides consistent test entities spanning multi-currency invoices, payment obligations,
workflow history, vendors, and line items across distinct user roles.
"""
from datetime import date, datetime, timedelta, timezone
import uuid
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_enums import DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.invoice import Invoice
from app.models.invoice_line_item import InvoiceLineItem
from app.models.payment_obligation import PaymentObligation, PaymentStatus
from app.models.user import User, UserRole
from app.models.vendor import Vendor
from app.models.workflow_history import WorkflowHistory


def seed_evaluation_corpus(db_session: Session) -> Dict[str, Any]:
    """Seed a multi-vendor, multi-currency portfolio for chatbot evaluation."""
    suffix = uuid.uuid4().hex[:8]

    # 1. Users across roles
    analyst_user = User(
        username=f"analyst_{suffix}",
        email=f"analyst_{suffix}@example.com",
        full_name="Analyst User",
        password_hash="secret_hash",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    manager_user = User(
        username=f"manager_{suffix}",
        email=f"manager_{suffix}@example.com",
        full_name="Manager User",
        password_hash="secret_hash",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )
    auditor_user = User(
        username=f"auditor_{suffix}",
        email=f"auditor_{suffix}@example.com",
        full_name="Auditor User",
        password_hash="secret_hash",
        role=UserRole.AUDITOR.value,
        is_active=True,
    )
    admin_user = User(
        username=f"admin_{suffix}",
        email=f"admin_{suffix}@example.com",
        full_name="Admin User",
        password_hash="secret_hash",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db_session.add_all([analyst_user, manager_user, auditor_user, admin_user])
    db_session.flush()

    # 2. Vendors
    vendor_acme = Vendor(canonical_name=f"Acme Corp {suffix}", vendor_code=f"ACME_{suffix}")
    vendor_globex = Vendor(canonical_name=f"Globex Ltd {suffix}", vendor_code=f"GLOB_{suffix}")
    vendor_initech = Vendor(canonical_name=f"Initech LLC {suffix}", vendor_code=f"INIT_{suffix}")
    db_session.add_all([vendor_acme, vendor_globex, vendor_initech])
    db_session.flush()

    now = datetime.now(timezone.utc)
    today = now.date()

    # 3. Documents
    # Doc 1: Analyst owned, validated, USD, recent (within 30 days)
    doc1 = Document(
        original_filename=f"inv_acme_1_{suffix}.pdf",
        stored_filename=f"inv_acme_1_{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_hash=f"hash1_{suffix}",
        document_type="POI",
        status=DocumentStatus.VALIDATED.value,
        uploaded_by=analyst_user.id,
        created_at=now - timedelta(days=10),
        is_deleted=False,
    )
    # Doc 2: Manager uploaded, pending approval, NPO
    doc2 = Document(
        original_filename=f"npo_globex_2_{suffix}.pdf",
        stored_filename=f"npo_globex_2_{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_hash=f"hash2_{suffix}",
        document_type="NPO",
        status=DocumentStatus.PENDING_APPROVAL.value,
        uploaded_by=manager_user.id,
        created_at=now - timedelta(days=5),
        is_deleted=False,
    )
    # Doc 3: Admin uploaded, pending approval, POI
    doc3 = Document(
        original_filename=f"poi_initech_3_{suffix}.pdf",
        stored_filename=f"poi_initech_3_{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=3072,
        file_hash=f"hash3_{suffix}",
        document_type="POI",
        status=DocumentStatus.PENDING_APPROVAL.value,
        uploaded_by=admin_user.id,
        created_at=now - timedelta(days=2),
        is_deleted=False,
    )
    # Doc 4: EUR invoice, approved, 45 days ago
    doc4 = Document(
        original_filename=f"inv_eur_4_{suffix}.pdf",
        stored_filename=f"inv_eur_4_{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=1500,
        file_hash=f"hash4_{suffix}",
        document_type="POI",
        status=DocumentStatus.APPROVED.value,
        uploaded_by=manager_user.id,
        created_at=now - timedelta(days=45),
        is_deleted=False,
    )
    # Doc 5: Soft-deleted document
    doc5_deleted = Document(
        original_filename=f"deleted_5_{suffix}.pdf",
        stored_filename=f"deleted_5_{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=500,
        file_hash=f"hash5_{suffix}",
        document_type="POI",
        status=DocumentStatus.REJECTED.value,
        uploaded_by=manager_user.id,
        created_at=now - timedelta(days=1),
        is_deleted=True,
    )
    db_session.add_all([doc1, doc2, doc3, doc4, doc5_deleted])
    db_session.flush()

    # 4. Invoices
    # Inv 1: USD 15,000 Acme Corp (within 30 days)
    inv1 = Invoice(
        document_id=doc1.id,
        vendor_id=vendor_acme.id,
        invoice_number=f"INV-ACME-01-{suffix}",
        invoice_date=today - timedelta(days=10),
        currency="USD",
        subtotal_amount=13500.00,
        tax_amount=1500.00,
        grand_total_amount=15000.00,
        po_number="PO-99881",
    )
    # Inv 2: USD 8,000 Globex Ltd (NPO, pending approval)
    inv2 = Invoice(
        document_id=doc2.id,
        vendor_id=vendor_globex.id,
        invoice_number=f"NPO-GLOB-02-{suffix}",
        invoice_date=today - timedelta(days=5),
        currency="USD",
        subtotal_amount=7500.00,
        tax_amount=500.00,
        grand_total_amount=8000.00,
        po_number=None,
    )
    # Inv 3: USD 22,000 Initech LLC (POI, pending approval)
    inv3 = Invoice(
        document_id=doc3.id,
        vendor_id=vendor_initech.id,
        invoice_number=f"POI-INIT-03-{suffix}",
        invoice_date=today - timedelta(days=2),
        currency="USD",
        subtotal_amount=20000.00,
        tax_amount=2000.00,
        grand_total_amount=22000.00,
        po_number="PO-11223",
    )
    # Inv 4: EUR 12,000 Globex Ltd (45 days ago)
    inv4 = Invoice(
        document_id=doc4.id,
        vendor_id=vendor_globex.id,
        invoice_number=f"INV-GLOB-EUR-04-{suffix}",
        invoice_date=today - timedelta(days=45),
        currency="EUR",
        subtotal_amount=10000.00,
        tax_amount=2000.00,
        grand_total_amount=12000.00,
        po_number="PO-EUR-44",
    )
    db_session.add_all([inv1, inv2, inv3, inv4])
    db_session.flush()

    # 5. Payment Obligations
    # Ob 1: USD 15,000 due in future (not overdue)
    ob1 = PaymentObligation(
        invoice_id=inv1.id,
        amount_due=15000.00,
        amount_paid=0.00,
        amount_outstanding=15000.00,
        currency="USD",
        due_date=today + timedelta(days=20),
        status=PaymentStatus.OPEN.value,
        payment_terms="Net 30",
    )
    # Ob 2: USD 8,000 past due (OVERDUE by dynamic date, status is OPEN)
    ob2 = PaymentObligation(
        invoice_id=inv2.id,
        amount_due=8000.00,
        amount_paid=0.00,
        amount_outstanding=8000.00,
        currency="USD",
        due_date=today - timedelta(days=15),
        status=PaymentStatus.OPEN.value,  # not 'OVERDUE' string
        payment_terms="Net 15",
    )
    # Ob 3: USD 22,000 paid (PAID, not overdue)
    ob3 = PaymentObligation(
        invoice_id=inv3.id,
        amount_due=22000.00,
        amount_paid=22000.00,
        amount_outstanding=0.00,
        currency="USD",
        due_date=today - timedelta(days=1),
        status=PaymentStatus.PAID.value,
        payment_terms="Immediate",
    )
    # Ob 4: EUR 12,000 past due (OVERDUE by dynamic date, EUR)
    ob4 = PaymentObligation(
        invoice_id=inv4.id,
        amount_due=12000.00,
        amount_paid=0.00,
        amount_outstanding=12000.00,
        currency="EUR",
        due_date=today - timedelta(days=10),
        status=PaymentStatus.OPEN.value,
        payment_terms="Net 30",
    )
    db_session.add_all([ob1, ob2, ob3, ob4])
    db_session.flush()

    # 6. Workflow history entries
    wh1 = WorkflowHistory(
        document_id=doc1.id,
        action="VALIDATE",
        from_status=DocumentStatus.EXTRACTED.value,
        to_status=DocumentStatus.VALIDATED.value,
        comment="Auto-validated OCR extracted fields",
        performed_by=manager_user.id,
    )
    wh2 = WorkflowHistory(
        document_id=doc2.id,
        action="SUBMIT_APPROVAL",
        from_status=DocumentStatus.VALIDATED.value,
        to_status=DocumentStatus.PENDING_APPROVAL.value,
        comment="Submitted for manager review",
        performed_by=analyst_user.id,
    )
    wh_del = WorkflowHistory(
        document_id=doc5_deleted.id,
        action="REJECT",
        from_status=DocumentStatus.PENDING_APPROVAL.value,
        to_status=DocumentStatus.REJECTED.value,
        comment="Deleted document rejection note",
        performed_by=manager_user.id,
    )
    db_session.add_all([wh1, wh2, wh_del])
    db_session.commit()

    return {
        "users": {
            "analyst": analyst_user,
            "manager": manager_user,
            "auditor": auditor_user,
            "admin": admin_user,
        },
        "vendors": {
            "acme": vendor_acme,
            "globex": vendor_globex,
            "initech": vendor_initech,
        },
        "documents": [doc1, doc2, doc3, doc4, doc5_deleted],
        "invoices": [inv1, inv2, inv3, inv4],
        "obligations": [ob1, ob2, ob3, ob4],
        "workflow_history": [wh1, wh2, wh_del],
    }
