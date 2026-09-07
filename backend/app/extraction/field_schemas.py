"""
Field schema definitions for document data extraction.

Single source of truth for "what fields exist for what document type."
Used by:
  - app/extraction/*_extractor.py (what to look for)
  - ExtractionResult persistence (what shape the structured JSON takes)
  - the future review/correction UI (Phase: bulk intake + review) which
    highlights OCR-filled fields vs. fields the user must fill manually

Every field is OCR-extracted from the document content itself (per
explicit client confirmation) -- none of these are silently populated
by application logic. A field that cannot be found in the OCR text is
returned as null with zero confidence, never fabricated.

COMMON_FIELDS apply to every document regardless of type. Each document
type listed in DOCUMENT_TYPE_FIELDS additionally has its own
type-specific fields. The full field set for a given document is
COMMON_FIELDS + DOCUMENT_TYPE_FIELDS[type].
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDef:
    """
    Defines a single extractable field.

    `key`: stable machine-readable identifier (snake_case), used as the
           JSON key in ExtractionResult.fields and as the dict key
           extractors fill in.
    `label`: human-readable display name, matching the client's naming.
    `field_type`: hints at expected value shape -- "text", "date",
           "amount", "code" -- used for both extraction pattern
           selection and (later) frontend input rendering in the review
           UI.
    """

    key: str
    label: str
    field_type: str  # "text" | "date" | "amount" | "code"


# --- Common fields: present on every document type ---
COMMON_FIELDS: list[FieldDef] = [
    FieldDef("document_id", "Document ID", "code"),
    FieldDef("document_type", "Document Type", "code"),
    FieldDef("document_category", "Document Category", "code"),  # AP or R2R
    FieldDef("company_code", "Company Code", "code"),
    FieldDef("company_name", "Company Name", "text"),
    FieldDef("fiscal_year", "Fiscal Year", "code"),
    FieldDef("location_code", "Location Code", "code"),
    FieldDef("vertical_code", "Vertical Code", "code"),
    FieldDef("document_source", "Document Source", "text"),  # Email, Scan, Upload, API
    FieldDef("barcode", "Barcode", "code"),
    FieldDef("currency", "Currency", "code"),
    FieldDef("document_date", "Document Date", "date"),
    FieldDef("ocr_confidence_score", "OCR Confidence Score", "amount"),
    FieldDef("processing_status", "Processing Status", "text"),
    FieldDef("validation_status", "Validation Status", "text"),
]

# Maps each DocumentType value to its AP/R2R category, used to populate
# the common "document_category" field without re-deriving it per type.
DOCUMENT_CATEGORY: dict[str, str] = {
    "POI": "AP", "NPO": "AP", "DPR": "AP", "IMA": "AP",
    "MSI": "R2R", "PSI": "R2R", "JER": "R2R", "BKA": "R2R", "LCA": "R2R",
}


# --- Type-specific fields ---
DOCUMENT_TYPE_FIELDS: dict[str, list[FieldDef]] = {
    "POI": [
        FieldDef("vendor_code", "Vendor Code", "code"),
        FieldDef("vendor_name", "Vendor Name", "text"),
        FieldDef("po_number", "PO Number", "code"),
        FieldDef("grn_number", "GRN Number", "code"),
        FieldDef("srn_number", "SRN Number", "code"),
        FieldDef("invoice_number", "Invoice Number", "code"),
        FieldDef("invoice_date", "Invoice Date", "date"),
        FieldDef("invoice_amount", "Invoice Amount", "amount"),
        FieldDef("tax_amount", "Tax Amount", "amount"),
        FieldDef("net_amount", "Net Amount", "amount"),
        FieldDef("payment_terms", "Payment Terms", "text"),
    ],
    "NPO": [
        FieldDef("vendor_code", "Vendor Code", "code"),
        FieldDef("vendor_name", "Vendor Name", "text"),
        FieldDef("invoice_number", "Invoice Number", "code"),
        FieldDef("invoice_date", "Invoice Date", "date"),
        FieldDef("invoice_amount", "Invoice Amount", "amount"),
        FieldDef("expense_category", "Expense Category", "text"),
        FieldDef("cost_center", "Cost Center", "code"),
        FieldDef("department", "Department", "text"),
        FieldDef("tax_amount", "Tax Amount", "amount"),
        FieldDef("net_amount", "Net Amount", "amount"),
    ],
    "DPR": [
        FieldDef("request_number", "Request Number", "code"),
        FieldDef("request_date", "Request Date", "date"),
        FieldDef("vendor_code", "Vendor Code", "code"),
        FieldDef("vendor_name", "Vendor Name", "text"),
        FieldDef("po_number", "PO Number", "code"),
        FieldDef("requested_amount", "Requested Amount", "amount"),
        FieldDef("advance_percentage", "Advance Percentage", "amount"),
        FieldDef("purpose", "Purpose", "text"),
        FieldDef("approval_status", "Approval Status", "text"),
    ],
    "IMA": [
        FieldDef("employee_id", "Employee ID", "code"),
        FieldDef("employee_name", "Employee Name", "text"),
        FieldDef("claim_number", "Claim Number", "code"),
        FieldDef("claim_date", "Claim Date", "date"),
        FieldDef("travel_start_date", "Travel Start Date", "date"),
        FieldDef("travel_end_date", "Travel End Date", "date"),
        FieldDef("expense_category", "Expense Category", "text"),
        FieldDef("claim_amount", "Claim Amount", "amount"),
        FieldDef("approved_amount", "Approved Amount", "amount"),
        FieldDef("manager_approval_status", "Manager Approval Status", "text"),
    ],
    "MSI": [
        FieldDef("customer_code", "Customer Code", "code"),
        FieldDef("customer_name", "Customer Name", "text"),
        FieldDef("sales_invoice_number", "Sales Invoice Number", "code"),
        FieldDef("sales_invoice_date", "Sales Invoice Date", "date"),
        FieldDef("invoice_amount", "Invoice Amount", "amount"),
        FieldDef("tax_amount", "Tax Amount", "amount"),
        FieldDef("net_amount", "Net Amount", "amount"),
        FieldDef("due_date", "Due Date", "date"),
        FieldDef("payment_terms", "Payment Terms", "text"),
    ],
    "PSI": [
        FieldDef("pis_number", "PIS Number", "code"),
        FieldDef("pis_date", "PIS Date", "date"),
        FieldDef("customer_code", "Customer Code", "code"),
        FieldDef("customer_name", "Customer Name", "text"),
        FieldDef("bank_name", "Bank Name", "text"),
        FieldDef("deposit_amount", "Deposit Amount", "amount"),
        FieldDef("deposit_reference_number", "Deposit Reference Number", "code"),
        FieldDef("deposit_date", "Deposit Date", "date"),
        FieldDef("reconciliation_status", "Reconciliation Status", "text"),
    ],
    "JER": [
        FieldDef("journal_entry_number", "Journal Entry Number", "code"),
        FieldDef("posting_date", "Posting Date", "date"),
        FieldDef("gl_account_code", "GL Account Code", "code"),
        FieldDef("gl_account_description", "GL Account Description", "text"),
        FieldDef("debit_amount", "Debit Amount", "amount"),
        FieldDef("credit_amount", "Credit Amount", "amount"),
        FieldDef("cost_center", "Cost Center", "code"),
        FieldDef("profit_center", "Profit Center", "code"),
        FieldDef("reference_number", "Reference Number", "code"),
        FieldDef("approval_status", "Approval Status", "text"),
    ],
    "BKA": [
        FieldDef("advice_number", "Advice Number", "code"),
        FieldDef("advice_date", "Advice Date", "date"),
        FieldDef("bank_name", "Bank Name", "text"),
        FieldDef("account_number", "Account Number", "code"),
        FieldDef("transaction_reference", "Transaction Reference", "code"),
        FieldDef("transaction_type", "Transaction Type", "text"),
        FieldDef("transaction_amount", "Transaction Amount", "amount"),
        FieldDef("value_date", "Value Date", "date"),
        FieldDef("reconciliation_status", "Reconciliation Status", "text"),
    ],
    "LCA": [
        FieldDef("lc_number", "LC Number", "code"),
        FieldDef("issue_date", "Issue Date", "date"),
        FieldDef("expiry_date", "Expiry Date", "date"),
        FieldDef("issuing_bank", "Issuing Bank", "text"),
        FieldDef("beneficiary_name", "Beneficiary Name", "text"),
        FieldDef("lc_amount", "LC Amount", "amount"),
        FieldDef("shipment_reference", "Shipment Reference", "code"),
        FieldDef("trade_reference_number", "Trade Reference Number", "code"),
        FieldDef("country", "Country", "text"),
        FieldDef("approval_status", "Approval Status", "text"),
    ],
}


def get_full_field_schema(document_type: str) -> list[FieldDef]:
    """Return COMMON_FIELDS + this type's specific fields, in display order."""
    return COMMON_FIELDS + DOCUMENT_TYPE_FIELDS.get(document_type, [])


def get_field_keys(document_type: str) -> list[str]:
    return [f.key for f in get_full_field_schema(document_type)]
