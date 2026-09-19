"""
Per-document-type field extraction.

Each function takes raw OCR text and optional OCR layout structures (raw_blocks,
table_data), returning a dict of {field_key: ExtractedField} covering every field
in that type's schema (app/extraction/field_schemas.py).
"""
from typing import Any

from app.extraction.base import ExtractedField
from app.extraction.primitives import (
    extract_amount_field,
    extract_amount_hybrid,
    extract_by_labels,
    extract_date_field,
    extract_date_hybrid,
    extract_field_hybrid,
)

# --- Common fields, shared across every document type ---


def extract_common_fields(
    text: str, raw_blocks: list[dict] | None = None
) -> dict[str, ExtractedField]:
    return {
        "document_id": extract_field_hybrid(text, ["Document ID", "Doc ID", "DOCID"], raw_blocks, field_type="code"),
        "processing_status": extract_by_labels(text, ["Processing Status"]),
        "validation_status": extract_by_labels(text, ["Validation Status"]),
        "company_code": extract_field_hybrid(text, ["Company Code", "COCODE", "CO CODE"], raw_blocks, field_type="code"),
        "currency": extract_by_labels(text, ["Currency"]),
        "barcode": extract_by_labels(text, ["Barcode", "Bar Code"]),
    }


# --- Type-specific extractors ---


def extract_poi_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "vendor_code": extract_field_hybrid(text, ["Vendor Code"], raw_blocks, field_type="code"),
        "po_number": extract_field_hybrid(text, ["PO Number", "Purchase Order Number", "PO No"], raw_blocks, field_type="code"),
        "grn_number": extract_field_hybrid(text, ["GRN Number", "GRN No", "GRN"], raw_blocks, field_type="code"),
        "srn_number": extract_field_hybrid(text, ["SRN Number", "SRN No", "SRN"], raw_blocks, field_type="code"),
        "invoice_number": extract_field_hybrid(text, ["Invoice Number", "Invoice No"], raw_blocks, field_type="code"),
        "invoice_date": extract_date_hybrid(text, ["Invoice Date"], raw_blocks),
        "seller_name": extract_field_hybrid(text, ["Seller Name", "Vendor Name", "Vendor", "Supplier"], raw_blocks, field_type="text"),
        "seller_address": extract_field_hybrid(text, ["Seller Address", "Vendor Address", "Supplier Address"], raw_blocks, field_type="text"),
        "seller_tax_id": extract_field_hybrid(text, ["Seller Tax ID", "Vendor Tax ID", "GSTIN", "VAT", "Tax ID"], raw_blocks, field_type="code"),
        "buyer_name": extract_field_hybrid(text, ["Buyer Name", "Customer Name", "Bill To", "Company Name"], raw_blocks, field_type="text"),
        "buyer_address": extract_field_hybrid(text, ["Buyer Address", "Customer Address", "Bill To Address"], raw_blocks, field_type="text"),
        "buyer_tax_id": extract_field_hybrid(text, ["Buyer Tax ID", "Customer Tax ID", "Buyer GSTIN"], raw_blocks, field_type="code"),
        "subtotal_net_amount": extract_amount_hybrid(text, ["Subtotal Net Amount", "Net Amount", "Subtotal"], raw_blocks, table_data, role="subtotal_net_amount"),
        "tax_rate": extract_amount_hybrid(text, ["Tax Rate", "GST Rate", "VAT Rate"], raw_blocks, table_data, role="tax_rate"),
        "total_tax_amount": extract_amount_hybrid(text, ["Total Tax Amount", "Tax Amount", "GST Amount", "Tax"], raw_blocks, table_data, role="total_tax_amount"),
        "grand_total_amount": extract_amount_hybrid(text, ["Grand Total Amount", "Invoice Amount", "Total Amount", "Gross Amount"], raw_blocks, table_data, role="grand_total_amount"),
        "payment_terms": extract_by_labels(text, ["Payment Terms"]),
    }


def extract_npo_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "vendor_code": extract_field_hybrid(text, ["Vendor Code"], raw_blocks, field_type="code"),
        "invoice_number": extract_field_hybrid(text, ["Invoice Number", "Invoice No"], raw_blocks, field_type="code"),
        "invoice_date": extract_date_hybrid(text, ["Invoice Date"], raw_blocks),
        "seller_name": extract_field_hybrid(text, ["Seller Name", "Vendor Name", "Vendor", "Supplier"], raw_blocks, field_type="text"),
        "seller_address": extract_field_hybrid(text, ["Seller Address", "Vendor Address", "Supplier Address"], raw_blocks, field_type="text"),
        "seller_tax_id": extract_field_hybrid(text, ["Seller Tax ID", "Vendor Tax ID", "GSTIN", "VAT", "Tax ID"], raw_blocks, field_type="code"),
        "buyer_name": extract_field_hybrid(text, ["Buyer Name", "Customer Name", "Bill To", "Company Name"], raw_blocks, field_type="text"),
        "buyer_address": extract_field_hybrid(text, ["Buyer Address", "Customer Address", "Bill To Address"], raw_blocks, field_type="text"),
        "buyer_tax_id": extract_field_hybrid(text, ["Buyer Tax ID", "Customer Tax ID", "Buyer GSTIN"], raw_blocks, field_type="code"),
        "subtotal_net_amount": extract_amount_hybrid(text, ["Subtotal Net Amount", "Net Amount", "Subtotal"], raw_blocks, table_data, role="subtotal_net_amount"),
        "tax_rate": extract_amount_hybrid(text, ["Tax Rate", "GST Rate", "VAT Rate"], raw_blocks, table_data, role="tax_rate"),
        "total_tax_amount": extract_amount_hybrid(text, ["Total Tax Amount", "Tax Amount", "GST Amount"], raw_blocks, table_data, role="total_tax_amount"),
        "grand_total_amount": extract_amount_hybrid(text, ["Grand Total Amount", "Invoice Amount", "Amount Due", "Total Amount"], raw_blocks, table_data, role="grand_total_amount"),
    }


def extract_dpr_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "request_number": extract_field_hybrid(text, ["Request Number", "DPR Number", "Request No"], raw_blocks, field_type="code"),
        "request_date": extract_date_hybrid(text, ["Request Date"], raw_blocks),
        "vendor_code": extract_field_hybrid(text, ["Vendor Code"], raw_blocks, field_type="code"),
        "seller_name": extract_field_hybrid(text, ["Seller Name", "Vendor Name", "Vendor"], raw_blocks, field_type="text"),
        "buyer_name": extract_field_hybrid(text, ["Buyer Name", "Company Name", "Customer Name"], raw_blocks, field_type="text"),
        "po_number": extract_field_hybrid(text, ["PO Number", "PO No"], raw_blocks, field_type="code"),
        "requested_amount": extract_amount_hybrid(text, ["Requested Amount"], raw_blocks, table_data, role="invoice_amount"),
        "advance_percentage": extract_by_labels(text, ["Advance Percentage", "Advance %"]),
        "purpose": extract_by_labels(text, ["Purpose"]),
        "approval_status": extract_by_labels(text, ["Approval Status"]),
    }


def extract_ima_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "employee_id": extract_field_hybrid(text, ["Employee ID", "Employee Code"], raw_blocks, field_type="code"),
        "employee_name": extract_field_hybrid(text, ["Employee Name", "Employee"], raw_blocks, field_type="text"),
        "claim_number": extract_field_hybrid(text, ["Claim Number", "Claim No"], raw_blocks, field_type="code"),
        "claim_date": extract_date_hybrid(text, ["Claim Date"], raw_blocks),
        "travel_start_date": extract_date_hybrid(text, ["Travel Start Date"], raw_blocks),
        "travel_end_date": extract_date_hybrid(text, ["Travel End Date"], raw_blocks),
        "expense_category": extract_by_labels(text, ["Expense Category"]),
        "claim_amount": extract_amount_hybrid(text, ["Claim Amount", "Reimbursement Amount"], raw_blocks, table_data, role="invoice_amount"),
        "approved_amount": extract_amount_hybrid(text, ["Approved Amount"], raw_blocks, table_data, role="invoice_amount"),
        "manager_approval_status": extract_by_labels(text, ["Manager Approval Status", "Approval Status"]),
    }


def extract_msi_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "customer_code": extract_field_hybrid(text, ["Customer Code"], raw_blocks, field_type="code"),
        "sales_invoice_number": extract_field_hybrid(text, ["Sales Invoice Number", "MSI Invoice Number", "Invoice Number", "Invoice #", "Invoice"], raw_blocks, field_type="code"),
        "sales_invoice_date": extract_date_hybrid(text, ["Sales Invoice Date", "MSI Invoice Date", "Invoice Date", "Date"], raw_blocks),
        "seller_name": extract_field_hybrid(text, ["Seller Name", "Vendor Name", "Company Name"], raw_blocks, field_type="text"),
        "seller_address": extract_field_hybrid(text, ["Seller Address", "Vendor Address"], raw_blocks, field_type="text"),
        "seller_tax_id": extract_field_hybrid(text, ["Seller Tax ID", "Vendor Tax ID", "GSTIN", "VAT"], raw_blocks, field_type="code"),
        "buyer_name": extract_field_hybrid(text, ["Buyer Name", "Customer Name", "Customer", "Bill To"], raw_blocks, field_type="text"),
        "buyer_address": extract_field_hybrid(text, ["Buyer Address", "Customer Address", "Bill To Address"], raw_blocks, field_type="text"),
        "buyer_tax_id": extract_field_hybrid(text, ["Buyer Tax ID", "Customer Tax ID", "Buyer GSTIN"], raw_blocks, field_type="code"),
        "subtotal_net_amount": extract_amount_hybrid(text, ["Subtotal Net Amount", "Net Amount", "Subtotal"], raw_blocks, table_data, role="subtotal_net_amount"),
        "tax_rate": extract_amount_hybrid(text, ["Tax Rate", "GST Rate", "VAT Rate"], raw_blocks, table_data, role="tax_rate"),
        "total_tax_amount": extract_amount_hybrid(text, ["Total Tax Amount", "Tax Amount"], raw_blocks, table_data, role="total_tax_amount"),
        "grand_total_amount": extract_amount_hybrid(text, ["Grand Total Amount", "Invoice Amount", "MSI Invoice Amount", "Total"], raw_blocks, table_data, role="grand_total_amount"),
        "due_date": extract_date_hybrid(text, ["Due Date"], raw_blocks),
        "payment_terms": extract_by_labels(text, ["Payment Terms"]),
    }


def extract_psi_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "pis_number": extract_field_hybrid(text, ["PIS Number", "Pay In Slip Number"], raw_blocks, field_type="code"),
        "pis_date": extract_date_hybrid(text, ["PIS Date"], raw_blocks),
        "customer_code": extract_field_hybrid(text, ["Customer Code", "PIS Customer Code"], raw_blocks, field_type="code"),
        "buyer_name": extract_field_hybrid(text, ["Buyer Name", "Customer Name", "PIS Customer Name"], raw_blocks, field_type="text"),
        "bank_name": extract_field_hybrid(text, ["Bank Name"], raw_blocks, field_type="text"),
        "deposit_amount": extract_amount_hybrid(text, ["Deposit Amount", "PIS Deposit Amount"], raw_blocks, table_data, role="invoice_amount"),
        "deposit_reference_number": extract_field_hybrid(text, ["Deposit Reference Number", "Reference Number"], raw_blocks, field_type="code"),
        "deposit_date": extract_date_hybrid(text, ["Deposit Date"], raw_blocks),
        "reconciliation_status": extract_by_labels(text, ["Reconciliation Status"]),
    }


def extract_jer_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "journal_entry_number": extract_field_hybrid(text, ["Journal Entry Number", "JE Number", "JE No"], raw_blocks, field_type="code"),
        "posting_date": extract_date_hybrid(text, ["Posting Date"], raw_blocks),
        "gl_account_code": extract_field_hybrid(text, ["GL Account Code", "GL Account"], raw_blocks, field_type="code"),
        "gl_account_description": extract_by_labels(text, ["GL Account Description", "Account Description"]),
        "debit_amount": extract_amount_hybrid(text, ["Debit Amount", "Debit"], raw_blocks, table_data, role="invoice_amount"),
        "credit_amount": extract_amount_hybrid(text, ["Credit Amount", "Credit"], raw_blocks, table_data, role="invoice_amount"),
        "cost_center": extract_by_labels(text, ["Cost Center", "Cost Centre"]),
        "profit_center": extract_by_labels(text, ["Profit Center", "Profit Centre"]),
        "reference_number": extract_field_hybrid(text, ["Reference Number"], raw_blocks, field_type="code"),
        "approval_status": extract_by_labels(text, ["Approval Status"]),
    }


def extract_bka_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "advice_number": extract_field_hybrid(text, ["Advice Number", "Advice No"], raw_blocks, field_type="code"),
        "advice_date": extract_date_hybrid(text, ["Advice Date"], raw_blocks),
        "bank_name": extract_field_hybrid(text, ["Bank Name"], raw_blocks, field_type="text"),
        "account_number": extract_field_hybrid(text, ["Account Number", "Account No"], raw_blocks, field_type="code"),
        "transaction_reference": extract_field_hybrid(text, ["Transaction Reference", "Transaction Ref"], raw_blocks, field_type="code"),
        "transaction_type": extract_by_labels(text, ["Transaction Type"]),
        "transaction_amount": extract_amount_hybrid(text, ["Transaction Amount", "Advice Amount"], raw_blocks, table_data, role="invoice_amount"),
        "value_date": extract_date_hybrid(text, ["Value Date"], raw_blocks),
        "reconciliation_status": extract_by_labels(text, ["Reconciliation Status"]),
    }


def extract_lca_fields(
    text: str,
    raw_blocks: list[dict] | None = None,
    table_data: dict | None = None,
) -> dict[str, ExtractedField]:
    return {
        "lc_number": extract_field_hybrid(text, ["LC Number", "Letter of Credit Number"], raw_blocks, field_type="code"),
        "issue_date": extract_date_hybrid(text, ["Issue Date"], raw_blocks),
        "expiry_date": extract_date_hybrid(text, ["Expiry Date"], raw_blocks),
        "issuing_bank": extract_field_hybrid(text, ["Issuing Bank"], raw_blocks, field_type="text"),
        "beneficiary_name": extract_field_hybrid(text, ["Beneficiary Name", "Beneficiary"], raw_blocks, field_type="text"),
        "lc_amount": extract_amount_hybrid(text, ["LC Amount"], raw_blocks, table_data, role="invoice_amount"),
        "shipment_reference": extract_field_hybrid(text, ["Shipment Reference"], raw_blocks, field_type="code"),
        "trade_reference_number": extract_field_hybrid(text, ["Trade Reference Number", "Trade Reference"], raw_blocks, field_type="code"),
        "country": extract_by_labels(text, ["Country"]),
        "approval_status": extract_by_labels(text, ["Approval Status"]),
    }


# Dispatch table used by the rule-based extraction engine.
TYPE_EXTRACTORS = {
    "POI": extract_poi_fields,
    "NPO": extract_npo_fields,
    "DPR": extract_dpr_fields,
    "IMA": extract_ima_fields,
    "MSI": extract_msi_fields,
    "PSI": extract_psi_fields,
    "JER": extract_jer_fields,
    "BKA": extract_bka_fields,
    "LCA": extract_lca_fields,
}

