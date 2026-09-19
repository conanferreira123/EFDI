import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.field_schemas import COMMON_FIELDS, DOCUMENT_TYPE_FIELDS, get_full_field_schema
from app.models.document_enums import DocumentType

FIELD_CLASSIFICATION_REGISTRY = {
    # COMMON_FIELDS
    "document_id": ("B", "System/Intake ID", "SYSTEM / INTAKE METADATA"),
    "document_type": ("C", "Classifier Output", "DERIVED (CLASSIFIER)"),
    "document_category": ("C", "AP/R2R Taxonomy", "DERIVED (TAXONOMY)"),
    "company_code": ("B", "ERP Entity Code", "ERP / SYSTEM"),
    "company_name": ("A", "Physical Billed Party", "DOCUMENT_HEADER / OCR"),
    "fiscal_year": ("C", "Accounting Period", "DERIVED (DATE/CALENDAR)"),
    "location_code": ("B", "ERP Plant/Branch Code", "ERP / SYSTEM"),
    "vertical_code": ("B", "ERP Division Code", "ERP / SYSTEM"),
    "document_source": ("B", "Channel Tag ('Email', 'Upload')", "SYSTEM METADATA"),
    "barcode": ("A", "Physical Barcode String", "DOCUMENT_OCR"),
    "currency": ("A", "Document Currency Code", "DOCUMENT_OCR"),
    "document_date": ("A", "Document Issue Date", "DOCUMENT_HEADER / OCR"),
    "ocr_confidence_score": ("B", "OCR Engine Quality Metric", "SYSTEM PIPELINE"),
    "processing_status": ("B", "Workflow Execution State", "SYSTEM / WORKFLOW"),
    "validation_status": ("B", "Rule Validation Outcome", "SYSTEM / WORKFLOW"),

    # POI Specific
    "vendor_code": ("B", "ERP Vendor Master ID", "ERP / SYSTEM"),
    "vendor_name": ("A", "Physical Seller/Vendor Name", "DOCUMENT_HEADER / OCR"),
    "po_number": ("A", "Purchase Order Number", "DOCUMENT_HEADER / OCR"),
    "grn_number": ("D", "Goods Receipt Note Number", "ERP / DOCUMENT_REF"),
    "srn_number": ("D", "Service Receipt Note Number", "ERP / DOCUMENT_REF"),
    "invoice_number": ("A", "Physical Invoice Number", "DOCUMENT_HEADER / OCR"),
    "invoice_date": ("A", "Physical Invoice Date", "DOCUMENT_HEADER / OCR"),
    "invoice_amount": ("A", "Total Payable Amount", "DOCUMENT_SUMMARY / TABLE"),
    "tax_amount": ("A", "Total Tax / VAT Amount", "DOCUMENT_SUMMARY / TABLE"),
    "net_amount": ("A", "Subtotal / Net Worth", "DOCUMENT_SUMMARY / TABLE"),
    "payment_terms": ("A", "Payment Terms Text", "DOCUMENT_OCR"),

    # NPO Specific
    "expense_category": ("D", "GL / Expense Classification", "ERP / DOCUMENT_NOTE"),
    "cost_center": ("B", "ERP Cost Center Code", "ERP / SYSTEM"),
    "department": ("D", "Internal Department Name", "ERP / DOCUMENT_NOTE"),

    # DPR Specific
    "request_number": ("A", "Advance Request Number", "DOCUMENT_HEADER / OCR"),
    "request_date": ("A", "Advance Request Date", "DOCUMENT_HEADER / OCR"),
    "requested_amount": ("A", "Requested Advance Amount", "DOCUMENT_OCR"),
    "advance_percentage": ("A", "Advance Percentage", "DOCUMENT_OCR"),
    "purpose": ("A", "Payment Purpose Text", "DOCUMENT_OCR"),
    "approval_status": ("B", "Workflow Approval State", "SYSTEM / WORKFLOW"),

    # IMA Specific
    "employee_id": ("A", "Claimant Employee ID", "DOCUMENT_HEADER / OCR"),
    "employee_name": ("A", "Claimant Employee Name", "DOCUMENT_HEADER / OCR"),
    "claim_number": ("A", "Expense Claim Number", "DOCUMENT_HEADER / OCR"),
    "claim_date": ("A", "Claim Filing Date", "DOCUMENT_HEADER / OCR"),
    "travel_start_date": ("A", "Travel Start Date", "DOCUMENT_OCR"),
    "travel_end_date": ("A", "Travel End Date", "DOCUMENT_OCR"),
    "claim_amount": ("A", "Total Claim Amount", "DOCUMENT_OCR"),
    "approved_amount": ("D", "Approved Reimbursement", "ERP / APPROVER"),
    "manager_approval_status": ("B", "Workflow Approval State", "SYSTEM / WORKFLOW"),

    # MSI Specific
    "customer_code": ("B", "ERP Customer Master ID", "ERP / SYSTEM"),
    "customer_name": ("A", "Customer / Buyer Name", "DOCUMENT_HEADER / OCR"),
    "sales_invoice_number": ("A", "Sales Invoice Number", "DOCUMENT_HEADER / OCR"),
    "sales_invoice_date": ("A", "Sales Invoice Date", "DOCUMENT_HEADER / OCR"),
    "due_date": ("A", "Payment Due Date", "DOCUMENT_OCR"),

    # PSI Specific
    "pis_number": ("A", "Pay-in Slip Number", "DOCUMENT_HEADER / OCR"),
    "pis_date": ("A", "Deposit Slip Date", "DOCUMENT_HEADER / OCR"),
    "bank_name": ("A", "Bank Institution Name", "DOCUMENT_HEADER / OCR"),
    "deposit_amount": ("A", "Deposit Financial Amount", "DOCUMENT_OCR"),
    "deposit_reference_number": ("A", "Deposit / Cheque Ref", "DOCUMENT_OCR"),
    "deposit_date": ("A", "Deposit Clearance Date", "DOCUMENT_OCR"),
    "reconciliation_status": ("B", "Bank Reconciliation State", "SYSTEM / WORKFLOW"),

    # JER Specific
    "journal_entry_number": ("A", "JE Voucher Number", "DOCUMENT_HEADER / OCR"),
    "posting_date": ("A", "GL Posting Date", "DOCUMENT_HEADER / OCR"),
    "gl_account_code": ("A", "General Ledger Account Code", "DOCUMENT_TABLE / OCR"),
    "gl_account_description": ("A", "GL Account Description", "DOCUMENT_TABLE / OCR"),
    "debit_amount": ("A", "Debit Amount", "DOCUMENT_TABLE / OCR"),
    "credit_amount": ("A", "Credit Amount", "DOCUMENT_TABLE / OCR"),
    "profit_center": ("B", "ERP Profit Center Code", "ERP / SYSTEM"),
    "reference_number": ("A", "Source Document Ref", "DOCUMENT_OCR"),

    # BKA Specific
    "advice_number": ("A", "Bank Advice / Advice No", "DOCUMENT_HEADER / OCR"),
    "advice_date": ("A", "Bank Advice Date", "DOCUMENT_HEADER / OCR"),
    "account_number": ("A", "Bank Account Number", "DOCUMENT_HEADER / OCR"),
    "transaction_reference": ("A", "Transaction Ref / UTR", "DOCUMENT_TABLE / OCR"),
    "transaction_type": ("A", "Transaction Type", "DOCUMENT_TABLE / OCR"),
    "transaction_amount": ("A", "Transaction Amount", "DOCUMENT_TABLE / OCR"),
    "value_date": ("A", "Value Date", "DOCUMENT_TABLE / OCR"),

    # LCA Specific
    "lc_number": ("A", "Letter of Credit Number", "DOCUMENT_HEADER / OCR"),
    "issue_date": ("A", "LC Issuance Date", "DOCUMENT_HEADER / OCR"),
    "expiry_date": ("A", "LC Expiration Date", "DOCUMENT_HEADER / OCR"),
    "issuing_bank": ("A", "Issuing Bank Name", "DOCUMENT_HEADER / OCR"),
    "beneficiary_name": ("A", "Beneficiary Name", "DOCUMENT_HEADER / OCR"),
    "lc_amount": ("A", "LC Amount", "DOCUMENT_HEADER / OCR"),
    "shipment_reference": ("A", "Shipment / BL Reference", "DOCUMENT_OCR"),
    "trade_reference_number": ("A", "Trade Reference Number", "DOCUMENT_OCR"),
    "country": ("A", "Country Name", "DOCUMENT_OCR"),
}

common_keys = {f.key for f in COMMON_FIELDS}

types = [t.value for t in DocumentType if t != DocumentType.UNKNOWN]

with open("scratch/full_master_inventory.md", "w") as f_out:
    f_out.write("| Document Type | Field Key | Display Name | Expected Type | Source Definition | Common / Specific | Classification | Intended Source |\n")
    f_out.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
    for t in types:
        schema = get_full_field_schema(t)
        for f in schema:
            is_common = "Common" if f.key in common_keys else "Type-Specific"
            cat, desc, src = FIELD_CLASSIFICATION_REGISTRY[f.key]
            cat_label = f"Category {cat}"
            f_out.write(f"| {t} | `{f.key}` | {f.label} | `{f.field_type}` | `field_schemas.py` | {is_common} | **{cat_label}** | {src} |\n")

print("Generated scratch/full_master_inventory.md successfully.")
