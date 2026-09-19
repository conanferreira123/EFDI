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
    "currency",
}

COMMON_OPTIONAL_DEFAULT: set[str] = {
    "document_id",
    "company_code",
    "barcode",
    "processing_status",
    "validation_status",
}

# Type-specific mandatory field sets. Only type-specific fields need
# listing here; common fields are governed by COMMON_MANDATORY_DEFAULT
# above unless a type explicitly overrides them (none currently do).
MANDATORY_FIELDS: dict[str, set[str]] = {
    "POI": {
        "po_number", "invoice_number", "invoice_date", "grand_total_amount",
        "vendor_code", "seller_name", "buyer_name",
    },
    "NPO": {
        "invoice_number", "invoice_date", "grand_total_amount",
        "seller_name", "buyer_name",
    },
    "DPR": {
        "request_number", "request_date", "vendor_code", "seller_name",
        "buyer_name", "po_number", "requested_amount",
    },
    "IMA": {
        "employee_id", "employee_name", "claim_number", "claim_date", "claim_amount",
    },
    "MSI": {
        "customer_code", "buyer_name", "sales_invoice_number",
        "sales_invoice_date", "grand_total_amount",
    },
    "PSI": {
        "pis_number", "pis_date", "bank_name",
        "customer_code", "buyer_name", "deposit_amount",
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
    """Return whether a field (flat key or canonical dot-path) is mandatory for the document type."""
    from app.extraction.field_schemas import (
        NPO_MANDATORY_CORE_PATHS,
        map_npo_canonical_to_flat,
        map_npo_flat_to_canonical,
    )

    doc_type_upper = (document_type or "").upper()
    if doc_type_upper == "NPO":
        if field_key in NPO_MANDATORY_CORE_PATHS:
            return True
        flat_key = map_npo_canonical_to_flat(field_key)
        if flat_key in get_mandatory_fields("NPO"):
            return True
        canonical_path = map_npo_flat_to_canonical(field_key)
        if canonical_path in NPO_MANDATORY_CORE_PATHS:
            return True
        return False

    return field_key in get_mandatory_fields(document_type)
