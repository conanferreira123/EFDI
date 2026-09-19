import { format, formatDistanceToNow } from "date-fns";

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(isoString: string): string {
  return format(new Date(isoString), "dd MMM yyyy, HH:mm");
}

export function formatRelative(isoString: string): string {
  return formatDistanceToNow(new Date(isoString), { addSuffix: true });
}

export function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export const CANONICAL_FIELD_LABELS: Record<string, string> = {
  // Physical / Canonical extraction fields
  seller_name: "Seller Name",
  seller_address: "Seller Address",
  seller_tax_id: "Seller Tax ID",
  buyer_name: "Buyer Name",
  buyer_address: "Buyer Address",
  buyer_tax_id: "Buyer Tax ID",
  subtotal_net_amount: "Subtotal / Net Amount",
  tax_rate: "Tax Rate",
  total_tax_amount: "Total Tax",
  grand_total_amount: "Grand Total",
  invoice_number: "Invoice Number",
  invoice_date: "Invoice Date",
  po_number: "PO Number",
  grn_number: "GRN Number",
  srn_number: "SRN Number",
  currency: "Currency",
  barcode: "Barcode",
  payment_terms: "Payment Terms",

  // Application-owned metadata
  document_id: "Document ID",
  company_code: "Company Code",
  vendor_code: "Vendor Code",
  customer_code: "Customer Code",
  processing_status: "Processing Status",
  validation_status: "Validation Status",

  // Document-type specific canonical fields
  request_number: "Request Number",
  request_date: "Request Date",
  requested_amount: "Requested Amount",
  advance_number: "Advance Number",
  advance_date: "Advance Date",
  employee_id: "Employee ID",
  employee_name: "Employee Name",
  total_advance_amount: "Total Advance Amount",
  trip_purpose: "Trip Purpose",
  travel_start_date: "Travel Start Date",
  travel_end_date: "Travel End Date",
  pis_number: "PIS Number",
  pis_date: "PIS Date",
  deposit_amount: "Deposit Amount",
  deposit_reference_number: "Deposit Reference Number",
  deposit_date: "Deposit Date",
  journal_entry_number: "Journal Entry Number",
  posting_date: "Posting Date",
  gl_account_code: "GL Account Code",
  gl_account_description: "GL Account Description",
  debit_amount: "Debit Amount",
  credit_amount: "Credit Amount",
  cost_center: "Cost Center",
  profit_center: "Profit Center",
  reference_number: "Reference Number",
  advice_number: "Advice Number",
  advice_date: "Advice Date",
  bank_name: "Bank Name",
  account_number: "Account Number",
  transaction_reference: "Transaction Reference",
  transaction_type: "Transaction Type",
  transaction_amount: "Transaction Amount",
  value_date: "Value Date",
  lc_number: "LC Number",
  issue_date: "Issue Date",
  expiry_date: "Expiry Date",
  issuing_bank: "Issuing Bank",
  beneficiary_name: "Beneficiary Name",
  lc_amount: "LC Amount",
  shipment_reference: "Shipment Reference",
  trade_reference_number: "Trade Reference Number",
  country: "Country",
  approval_status: "Approval Status",
  reconciliation_status: "Reconciliation Status",
};

export function fieldLabel(key: string): string {
  if (CANONICAL_FIELD_LABELS[key]) {
    return CANONICAL_FIELD_LABELS[key];
  }
  return key
    .split("_")
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}
