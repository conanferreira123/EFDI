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
    FieldDef("processing_status", "Processing Status", "text"),
    FieldDef("validation_status", "Validation Status", "text"),
    FieldDef("company_code", "Company Code", "code"),
    FieldDef("currency", "Currency", "code"),
    FieldDef("barcode", "Barcode", "code"),
]

# System metadata fields that are populated from database/context rather than LLM extraction
SYSTEM_METADATA_KEYS: set[str] = {
    "document_id",
    "processing_status",
    "validation_status",
    "company_code",
    "vendor_code",
    "customer_code",
}

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
        FieldDef("po_number", "PO Number", "code"),
        FieldDef("grn_number", "GRN Number", "code"),
        FieldDef("srn_number", "SRN Number", "code"),
        FieldDef("invoice_number", "Invoice Number", "code"),
        FieldDef("invoice_date", "Invoice Date", "date"),
        FieldDef("seller_name", "Seller Name", "text"),
        FieldDef("seller_address", "Seller Address", "text"),
        FieldDef("seller_tax_id", "Seller Tax ID", "code"),
        FieldDef("buyer_name", "Buyer Name", "text"),
        FieldDef("buyer_address", "Buyer Address", "text"),
        FieldDef("buyer_tax_id", "Buyer Tax ID", "code"),
        FieldDef("subtotal_net_amount", "Subtotal Net Amount", "amount"),
        FieldDef("tax_rate", "Tax Rate", "amount"),
        FieldDef("total_tax_amount", "Total Tax Amount", "amount"),
        FieldDef("grand_total_amount", "Grand Total Amount", "amount"),
        FieldDef("payment_terms", "Payment Terms", "text"),
    ],
    "NPO": [
        FieldDef("vendor_code", "Vendor Code", "code"),
        FieldDef("invoice_number", "Invoice Number", "code"),
        FieldDef("invoice_date", "Invoice Date", "date"),
        FieldDef("seller_name", "Seller Name", "text"),
        FieldDef("seller_address", "Seller Address", "text"),
        FieldDef("seller_tax_id", "Seller Tax ID", "code"),
        FieldDef("buyer_name", "Buyer Name", "text"),
        FieldDef("buyer_address", "Buyer Address", "text"),
        FieldDef("buyer_tax_id", "Buyer Tax ID", "code"),
        FieldDef("subtotal_net_amount", "Subtotal Net Amount", "amount"),
        FieldDef("tax_rate", "Tax Rate", "amount"),
        FieldDef("total_tax_amount", "Total Tax Amount", "amount"),
        FieldDef("grand_total_amount", "Grand Total Amount", "amount"),
    ],
    "DPR": [
        FieldDef("request_number", "Request Number", "code"),
        FieldDef("request_date", "Request Date", "date"),
        FieldDef("vendor_code", "Vendor Code", "code"),
        FieldDef("seller_name", "Seller Name", "text"),
        FieldDef("buyer_name", "Buyer Name", "text"),
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
        FieldDef("sales_invoice_number", "Sales Invoice Number", "code"),
        FieldDef("sales_invoice_date", "Sales Invoice Date", "date"),
        FieldDef("seller_name", "Seller Name", "text"),
        FieldDef("seller_address", "Seller Address", "text"),
        FieldDef("seller_tax_id", "Seller Tax ID", "code"),
        FieldDef("buyer_name", "Buyer Name", "text"),
        FieldDef("buyer_address", "Buyer Address", "text"),
        FieldDef("buyer_tax_id", "Buyer Tax ID", "code"),
        FieldDef("subtotal_net_amount", "Subtotal Net Amount", "amount"),
        FieldDef("tax_rate", "Tax Rate", "amount"),
        FieldDef("total_tax_amount", "Total Tax Amount", "amount"),
        FieldDef("grand_total_amount", "Grand Total Amount", "amount"),
        FieldDef("due_date", "Due Date", "date"),
        FieldDef("payment_terms", "Payment Terms", "text"),
    ],
    "PSI": [
        FieldDef("pis_number", "PIS Number", "code"),
        FieldDef("pis_date", "PIS Date", "date"),
        FieldDef("customer_code", "Customer Code", "code"),
        FieldDef("buyer_name", "Buyer Name", "text"),
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


# =====================================================================
# CANONICAL HIERARCHICAL NPO SCHEMA DEFINITIONS
# =====================================================================

@dataclass(frozen=True)
class HierarchicalFieldDef:
    """Defines a field within the canonical semantic schema."""
    path: str           # Dot-delimited path (e.g. "invoice_information.invoice_number", "line_items[].description")
    label: str          # Human-readable label
    field_type: str     # "text" | "date" | "amount" | "code"
    is_mandatory: bool  # True for mandatory core fields per spec


@dataclass(frozen=True)
class CanonicalSectionDef:
    """Defines a semantic section in the canonical schema."""
    key: str
    label: str
    is_array: bool
    fields: list[HierarchicalFieldDef]


NPO_CANONICAL_SCHEMA: list[CanonicalSectionDef] = [
    CanonicalSectionDef(
        key="invoice_information",
        label="Invoice Information",
        is_array=False,
        fields=[
            HierarchicalFieldDef("invoice_information.invoice_number", "Invoice Number", "code", True),
            HierarchicalFieldDef("invoice_information.invoice_date", "Invoice Date", "date", True),
            HierarchicalFieldDef("invoice_information.currency", "Currency", "code", True),
            HierarchicalFieldDef("invoice_information.document_type", "Document Type", "code", False),
        ],
    ),
    CanonicalSectionDef(
        key="seller",
        label="Seller / Vendor",
        is_array=False,
        fields=[
            HierarchicalFieldDef("seller.name", "Seller Name", "text", True),
            HierarchicalFieldDef("seller.tax_id", "Seller Tax ID", "code", False),
            HierarchicalFieldDef("seller.address", "Seller Address", "text", False),
        ],
    ),
    CanonicalSectionDef(
        key="buyer",
        label="Buyer / Customer",
        is_array=False,
        fields=[
            HierarchicalFieldDef("buyer.name", "Buyer Name", "text", True),
            HierarchicalFieldDef("buyer.tax_id", "Buyer Tax ID", "code", False),
            HierarchicalFieldDef("buyer.address", "Buyer Address", "text", False),
        ],
    ),
    CanonicalSectionDef(
        key="line_items",
        label="Line Items",
        is_array=True,
        fields=[
            HierarchicalFieldDef("line_items[].description", "Description", "text", False),
            HierarchicalFieldDef("line_items[].quantity", "Quantity", "amount", False),
            HierarchicalFieldDef("line_items[].uom", "Unit of Measure", "code", False),
            HierarchicalFieldDef("line_items[].unit_price", "Unit Price", "amount", False),
            HierarchicalFieldDef("line_items[].net_amount", "Net Amount", "amount", False),
            HierarchicalFieldDef("line_items[].tax_rate", "Tax Rate", "amount", False),
            HierarchicalFieldDef("line_items[].tax_amount", "Tax Amount", "amount", False),
            HierarchicalFieldDef("line_items[].gross_amount", "Gross Amount", "amount", False),
        ],
    ),
    CanonicalSectionDef(
        key="taxes",
        label="Tax Breakdown",
        is_array=True,
        fields=[
            HierarchicalFieldDef("taxes[].tax_type", "Tax Type", "code", False),
            HierarchicalFieldDef("taxes[].tax_rate", "Tax Rate", "amount", False),
            HierarchicalFieldDef("taxes[].taxable_amount", "Taxable Amount", "amount", False),
            HierarchicalFieldDef("taxes[].tax_amount", "Tax Amount", "amount", False),
        ],
    ),
    CanonicalSectionDef(
        key="totals",
        label="Totals Summary",
        is_array=False,
        fields=[
            HierarchicalFieldDef("totals.subtotal", "Subtotal Net Amount", "amount", False),
            HierarchicalFieldDef("totals.total_tax", "Total Tax Amount", "amount", False),
            HierarchicalFieldDef("totals.grand_total", "Grand Total Amount", "amount", True),
            HierarchicalFieldDef("totals.discount", "Discount", "amount", False),
            HierarchicalFieldDef("totals.shipping", "Shipping & Handling", "amount", False),
            HierarchicalFieldDef("totals.other_charges", "Other Charges", "amount", False),
            HierarchicalFieldDef("totals.rounding", "Rounding Adjustment", "amount", False),
        ],
    ),
    CanonicalSectionDef(
        key="payment",
        label="Payment & Terms",
        is_array=False,
        fields=[
            HierarchicalFieldDef("payment.payment_terms", "Payment Terms", "text", False),
            HierarchicalFieldDef("payment.due_date", "Due Date", "date", False),
            HierarchicalFieldDef("payment.payment_method", "Payment Method", "text", False),
            HierarchicalFieldDef("payment.bank_account", "Bank Account Number", "code", False),
            HierarchicalFieldDef("payment.iban", "IBAN", "code", False),
            HierarchicalFieldDef("payment.swift_bic", "SWIFT / BIC", "code", False),
            HierarchicalFieldDef("payment.remittance_reference", "Remittance Reference", "code", False),
        ],
    ),
    CanonicalSectionDef(
        key="references",
        label="References",
        is_array=False,
        fields=[
            HierarchicalFieldDef("references.po_number", "PO Number", "code", False),
            HierarchicalFieldDef("references.contract_number", "Contract Number", "code", False),
            HierarchicalFieldDef("references.delivery_note_number", "Delivery Note Number", "code", False),
            HierarchicalFieldDef("references.order_number", "Order Number", "code", False),
            HierarchicalFieldDef("references.other_reference", "Other Reference", "code", False),
        ],
    ),
    CanonicalSectionDef(
        key="metadata",
        label="System / Derived Metadata",
        is_array=False,
        fields=[
            HierarchicalFieldDef("metadata.document_id", "Document ID", "code", False),
            HierarchicalFieldDef("metadata.company_code", "Company Code", "code", False),
            HierarchicalFieldDef("metadata.vendor_code", "Vendor Code", "code", False),
            HierarchicalFieldDef("metadata.gl_account", "GL Account", "code", False),
            HierarchicalFieldDef("metadata.cost_center", "Cost Center", "code", False),
            HierarchicalFieldDef("metadata.profit_center", "Profit Center", "code", False),
            HierarchicalFieldDef("metadata.department", "Department", "text", False),
            HierarchicalFieldDef("metadata.project_code", "Project Code", "code", False),
            HierarchicalFieldDef("metadata.internal_order", "Internal Order", "code", False),
            HierarchicalFieldDef("metadata.processing_status", "Processing Status", "text", False),
            HierarchicalFieldDef("metadata.validation_status", "Validation Status", "text", False),
            HierarchicalFieldDef("metadata.approval_status", "Approval Status", "text", False),
        ],
    ),
]

# Field categorization sets for NPO:
# Mandatory processing core: required for the invoice to be considered minimally processable
NPO_MANDATORY_CORE_PATHS: set[str] = {
    "invoice_information.invoice_number",
    "invoice_information.invoice_date",
    "invoice_information.currency",
    "seller.name",
    "buyer.name",
    "totals.grand_total",
}

NPO_IMPORTANT_OPTIONAL_PATHS: set[str] = {
    "invoice_information.document_type",
    "seller.tax_id",
    "seller.address",
    "buyer.tax_id",
    "buyer.address",
    "totals.subtotal",
    "totals.total_tax",
    "totals.discount",
    "totals.shipping",
    "totals.other_charges",
    "totals.rounding",
    "payment.payment_terms",
    "payment.due_date",
    "payment.payment_method",
    "payment.bank_account",
    "payment.iban",
    "payment.swift_bic",
    "payment.remittance_reference",
    "references.po_number",
    "references.contract_number",
    "references.delivery_note_number",
    "references.order_number",
    "references.other_reference",
}

NPO_SYSTEM_METADATA_PATHS: set[str] = {
    "metadata.document_id",
    "metadata.company_code",
    "metadata.vendor_code",
    "metadata.gl_account",
    "metadata.cost_center",
    "metadata.profit_center",
    "metadata.department",
    "metadata.project_code",
    "metadata.internal_order",
    "metadata.processing_status",
    "metadata.validation_status",
    "metadata.approval_status",
}

# Bi-directional mapping between legacy flat NPO field keys and canonical paths
NPO_FLAT_TO_CANONICAL_MAPPING: dict[str, str] = {
    "invoice_number": "invoice_information.invoice_number",
    "invoice_date": "invoice_information.invoice_date",
    "currency": "invoice_information.currency",
    "seller_name": "seller.name",
    "seller_address": "seller.address",
    "seller_tax_id": "seller.tax_id",
    "buyer_name": "buyer.name",
    "buyer_address": "buyer.address",
    "buyer_tax_id": "buyer.tax_id",
    "subtotal_net_amount": "totals.subtotal",
    "tax_rate": "totals.total_tax",  # flat tax_rate maps to total_tax or first tax entry
    "total_tax_amount": "totals.total_tax",
    "grand_total_amount": "totals.grand_total",
    "vendor_code": "metadata.vendor_code",
    "company_code": "metadata.company_code",
    "document_id": "metadata.document_id",
    "processing_status": "metadata.processing_status",
    "validation_status": "metadata.validation_status",
    "barcode": "metadata.barcode",
}

NPO_CANONICAL_TO_FLAT_MAPPING: dict[str, str] = {
    canonical: flat for flat, canonical in NPO_FLAT_TO_CANONICAL_MAPPING.items()
}


def is_hierarchical_schema(document_type: str) -> bool:
    """Return True if the document type uses a canonical hierarchical schema."""
    return (document_type or "").upper() == "NPO"


def get_npo_canonical_paths() -> list[str]:
    """Return all defined canonical dot-paths for NPO."""
    paths: list[str] = []
    for section in NPO_CANONICAL_SCHEMA:
        for f in section.fields:
            paths.append(f.path)
    return paths


def map_npo_flat_to_canonical(flat_key: str) -> str:
    """Map a flat legacy field key to its canonical dot-path, or return flat_key if already canonical."""
    return NPO_FLAT_TO_CANONICAL_MAPPING.get(flat_key, flat_key)


def map_npo_canonical_to_flat(canonical_path: str) -> str:
    """Map a canonical dot-path to its flat legacy key if one exists, or return the canonical path."""
    return NPO_CANONICAL_TO_FLAT_MAPPING.get(canonical_path, canonical_path)


def convert_flat_npo_to_hierarchical_dict(flat_dict: dict) -> dict:
    """Convert a flat key-value dictionary of NPO fields into the canonical nested structure."""
    hierarchical: dict[str, Any] = {
        "invoice_information": {},
        "seller": {},
        "buyer": {},
        "line_items": flat_dict.get("line_items") or [],
        "taxes": flat_dict.get("taxes") or [],
        "totals": {},
        "payment": {},
        "references": {},
    }
    for k, v in flat_dict.items():
        if k in ("line_items", "taxes", "canonical", "_canonical"):
            continue
        canon_path = map_npo_flat_to_canonical(k)
        if "." in canon_path:
            sec, field = canon_path.split(".", 1)
            if sec in hierarchical and isinstance(hierarchical[sec], dict):
                hierarchical[sec][field] = v
    return hierarchical


