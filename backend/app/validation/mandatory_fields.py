"""
Mandatory field definitions per document type.

The client's original field-mapping Excel (AP-AR_DocuementTypes.xlsx)
marked certain fields as mandatory (shown in red). That spreadsheet was
later superseded by a more complete field specification (see
app/extraction/field_schemas.py) which did not carry forward
mandatory/optional flags. Per explicit instruction, this module
reconstructs mandatory-ness by:

1. Carrying forward the original Excel's mandatory markings wherever
   the field still exists under its new name (e.g. old "VENDOR CODE"
   mandatory -> new "vendor_code" mandatory).
2. Some originally-mandatory fields no longer exist in the new schema
   at all (PRIORITY, NEW COMPANY CODE, SYSTEM DATE, LOC CODE) -- these
   are simply dropped; there is nothing to carry forward.
3. Fields that are new in the updated schema (not present in the old
   Excel at all -- e.g. GRN/SRN Number, Tax/Net Amount, Payment Terms,
   Cost Center, Department, all of DPR's and LCA's fields since those
   two types had no Excel field definitions originally) are assigned
   mandatory status using the same judgment the Excel applied
   elsewhere: identifying numbers, dates, and primary amounts are
   mandatory; descriptive/secondary fields are optional.

This mapping is intentionally centralized and explicit (rather than
inferred from FieldDef.field_type) so it can be reviewed and adjusted
by the client independently of the extraction schema itself.
"""

# Common fields mandatory across (almost) every document type.
# COMMON_MANDATORY_DEFAULT applies unless overridden per type below.
COMMON_MANDATORY_DEFAULT: set[str] = {
    "fiscal_year",
    "company_name",
    "currency",
    "document_date",
}

COMMON_OPTIONAL_DEFAULT: set[str] = {
    "document_id",
    "document_category",
    "company_code",
    "location_code",
    "vertical_code",
    "document_source",
    "barcode",
    "ocr_confidence_score",
    "processing_status",
    "validation_status",
}

# Type-specific mandatory field sets. Only type-specific fields need
# listing here; common fields are governed by COMMON_MANDATORY_DEFAULT
# above unless a type explicitly overrides them (none currently do).
MANDATORY_FIELDS: dict[str, set[str]] = {
    "POI": {
        "po_number", "invoice_number", "invoice_date", "invoice_amount",
        "vendor_code", "vendor_name",
    },
    "NPO": {
        "invoice_number", "invoice_date", "invoice_amount",
        "vendor_code", "vendor_name",
    },
    "DPR": {
        "request_number", "request_date", "vendor_code", "vendor_name",
        "po_number", "requested_amount",
    },
    "IMA": {
        "employee_id", "employee_name", "claim_number", "claim_date", "claim_amount",
    },
    "MSI": {
        "customer_code", "customer_name", "sales_invoice_number",
        "sales_invoice_date", "invoice_amount",
    },
    "PSI": {
        "pis_number", "pis_date", "bank_name",
        "customer_code", "customer_name", "deposit_amount",
    },
    "JER": {
        "journal_entry_number", "posting_date", "gl_account_code",
        "debit_amount", "credit_amount",
    },
    "BKA": {
        "bank_name", "account_number", "advice_date", "advice_number",
        "transaction_amount",
    },
    "LCA": {
        "lc_number", "issue_date", "expiry_date", "issuing_bank",
        "beneficiary_name", "lc_amount",
    },
}


def get_mandatory_fields(document_type: str) -> set[str]:
    """All mandatory field keys for a document type (common + type-specific)."""
    return COMMON_MANDATORY_DEFAULT | MANDATORY_FIELDS.get(document_type, set())


def is_field_mandatory(document_type: str, field_key: str) -> bool:
    return field_key in get_mandatory_fields(document_type)
