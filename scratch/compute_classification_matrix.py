import os
import sys
import json

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.extraction.field_schemas import COMMON_FIELDS, DOCUMENT_TYPE_FIELDS, get_full_field_schema
from app.models.document_enums import DocumentType

# Let's define the comprehensive field classification rules based on code inspection:
# Category A: Physical document field (printed on document)
# Category B: Internal / ERP / System Metadata (ERP internal codes, workflow statuses, system flags)
# Category C: Derived / Computed field (derived from document type, calculated math)
# Category D: Ambiguous (unclear if external ERP or document printed code)

FIELD_CLASSIFICATION_REGISTRY = {
    # COMMON_FIELDS
    "document_id": ("B", "System / Intake metadata (e.g. filename, batch ID, or document reference in system)"),
    "document_type": ("C", "Derived from upstream Classifier (POI, NPO, etc.)"),
    "document_category": ("C", "Derived from DocumentType taxonomy (AP vs R2R)"),
    "company_code": ("B", "Internal ERP Company Code (e.g. 1000, US01, 4-digit ERP entity code)"),
    "company_name": ("A", "Physical document party name (Client, Buyer, or Billed Company on document)"),
    "fiscal_year": ("C", "Derived/Computed from document_date / posting_date or ERP period"),
    "location_code": ("B", "Internal ERP Location/Plant Code"),
    "vertical_code": ("B", "Internal ERP Business Unit/Vertical Code"),
    "document_source": ("B", "System Intake Channel metadata ('Email', 'Scan', 'Upload', 'API')"),
    "barcode": ("A", "Physical Barcode string printed on document if present"),
    "currency": ("A", "Physical document currency code/symbol (USD, EUR, INR, etc.)"),
    "document_date": ("A", "Physical document issuance/creation date"),
    "ocr_confidence_score": ("B", "System pipeline OCR metric (float 0.0 - 1.0)"),
    "processing_status": ("B", "System workflow status ('UPLOADED', 'EXTRACTED', etc.)"),
    "validation_status": ("B", "System validation rule outcome ('VALIDATED', 'ERROR', etc.)"),

    # POI Specific
    "vendor_code": ("B", "Internal ERP Vendor Master ID (e.g. VEND-0012)"),
    "vendor_name": ("A", "Physical Seller/Vendor Name printed on document"),
    "po_number": ("A", "Physical Purchase Order Number printed on invoice"),
    "grn_number": ("D", "Goods Receipt Note Number (sometimes printed on invoice, often internal ERP)"),
    "srn_number": ("D", "Service Receipt Note Number (sometimes printed on invoice, often internal ERP)"),
    "invoice_number": ("A", "Physical Invoice Number printed on invoice"),
    "invoice_date": ("A", "Physical Invoice Date printed on invoice"),
    "invoice_amount": ("A", "Physical Grand Total / Gross Amount printed on invoice"),
    "tax_amount": ("A", "Physical Tax / VAT / GST Amount printed on invoice"),
    "net_amount": ("A", "Physical Subtotal / Net Amount printed on invoice"),
    "payment_terms": ("A", "Physical Payment Terms text printed on invoice ('Net 30', etc.)"),

    # NPO Specific
    "expense_category": ("D", "Expense Category (usually GL account/ERP classification, rarely printed explicitly)"),
    "cost_center": ("B", "Internal ERP Cost Center Code (e.g. CC-104)"),
    "department": ("D", "Department Name (sometimes printed in attention line, usually ERP org unit)"),

    # DPR Specific
    "request_number": ("A", "Physical Direct Payment / Advance Request Number"),
    "request_date": ("A", "Physical Request Date on form"),
    "requested_amount": ("A", "Physical Requested Payment Amount"),
    "advance_percentage": ("A", "Physical Advance Percentage (e.g. 20%, 50%)"),
    "purpose": ("A", "Physical Purpose / Description of payment request"),
    "approval_status": ("B", "Internal workflow approval state ('APPROVED', 'PENDING')"),

    # IMA Specific
    "employee_id": ("A", "Physical Employee ID printed on reimbursement claim form"),
    "employee_name": ("A", "Physical Employee Name printed on reimbursement claim form"),
    "claim_number": ("A", "Physical Claim / Expense Report Number"),
    "claim_date": ("A", "Physical Claim Submission Date"),
    "travel_start_date": ("A", "Physical Travel Start Date"),
    "travel_end_date": ("A", "Physical Travel End Date"),
    "claim_amount": ("A", "Physical Total Claimed Expense Amount"),
    "approved_amount": ("D", "Approved Amount (often filled by approver or ERP, sometimes on form)"),
    "manager_approval_status": ("B", "Internal workflow approval state of manager"),

    # MSI Specific
    "customer_code": ("B", "Internal ERP Customer Account Code"),
    "customer_name": ("A", "Physical Customer / Buyer Name printed on sales invoice"),
    "sales_invoice_number": ("A", "Physical Sales Invoice Number"),
    "sales_invoice_date": ("A", "Physical Sales Invoice Date"),
    "due_date": ("A", "Physical Payment Due Date printed on invoice"),

    # PSI Specific
    "pis_number": ("A", "Physical Pay-in-Slip / Deposit Slip Number"),
    "pis_date": ("A", "Physical Pay-in-Slip Date"),
    "bank_name": ("A", "Physical Bank Name printed on slip / statement"),
    "deposit_amount": ("A", "Physical Deposit Amount printed on slip"),
    "deposit_reference_number": ("A", "Physical Deposit Reference / Cheque Number"),
    "deposit_date": ("A", "Physical Bank Deposit Clearance Date"),
    "reconciliation_status": ("B", "Internal ERP / Bank Reconciliation State"),

    # JER Specific
    "journal_entry_number": ("A", "Physical Journal Entry Voucher Number on report"),
    "posting_date": ("A", "Physical GL Posting Date on journal voucher"),
    "gl_account_code": ("A", "Physical General Ledger Account Code printed on JE line"),
    "gl_account_description": ("A", "Physical GL Account Description printed on JE line"),
    "debit_amount": ("A", "Physical Debit Transaction Amount"),
    "credit_amount": ("A", "Physical Credit Transaction Amount"),
    "profit_center": ("B", "Internal ERP Profit Center Code"),
    "reference_number": ("A", "Physical Document / Source Reference Number on JE"),

    # BKA Specific
    "advice_number": ("A", "Physical Bank Advice / Statement Number"),
    "advice_date": ("A", "Physical Bank Advice / Statement Date"),
    "account_number": ("A", "Physical Bank Account Number printed on statement"),
    "transaction_reference": ("A", "Physical Transaction Reference / UTR Number"),
    "transaction_type": ("A", "Physical Transaction Type ('NEFT', 'RTGS', 'ACH', 'Debit', 'Credit')"),
    "transaction_amount": ("A", "Physical Transaction Amount"),
    "value_date": ("A", "Physical Bank Value Date"),

    # LCA Specific
    "lc_number": ("A", "Physical Letter of Credit Number"),
    "issue_date": ("A", "Physical LC Issue Date"),
    "expiry_date": ("A", "Physical LC Expiry Date"),
    "issuing_bank": ("A", "Physical Issuing Bank Name"),
    "beneficiary_name": ("A", "Physical Beneficiary Party Name"),
    "lc_amount": ("A", "Physical LC Financial Amount"),
    "shipment_reference": ("A", "Physical Shipment / Bill of Lading Reference"),
    "trade_reference_number": ("A", "Physical Trade Reference Number"),
    "country": ("A", "Physical Country of Origin / Destination"),
}

types = [t.value for t in DocumentType if t != DocumentType.UNKNOWN]

stats_by_type = {}
for t in types:
    schema = get_full_field_schema(t)
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for f in schema:
        cat, _ = FIELD_CLASSIFICATION_REGISTRY[f.key]
        counts[cat] += 1
    total = len(schema)
    pct_a = (counts["A"] / total) * 100
    pct_b = (counts["B"] / total) * 100
    pct_c = (counts["C"] / total) * 100
    pct_d = (counts["D"] / total) * 100
    stats_by_type[t] = {
        "total": total,
        "physical_A": counts["A"],
        "metadata_B": counts["B"],
        "derived_C": counts["C"],
        "ambiguous_D": counts["D"],
        "pct_physical": round(pct_a, 1),
        "pct_metadata": round(pct_b, 1),
        "pct_derived": round(pct_c, 1),
        "pct_ambiguous": round(pct_d, 1),
    }

print("=== CLASSIFICATION SUMMARY BY DOCUMENT TYPE ===")
for t, s in stats_by_type.items():
    print(f"{t}: Total={s['total']}, Physical={s['physical_A']} ({s['pct_physical']}%), Metadata={s['metadata_B']} ({s['pct_metadata']}%), Derived={s['derived_C']} ({s['pct_derived']}%), Ambiguous={s['ambiguous_D']} ({s['pct_ambiguous']}%)")
