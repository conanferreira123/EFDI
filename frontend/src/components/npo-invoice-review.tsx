import { useState } from "react";
import {
  FileText,
  Building2,
  User,
  CreditCard,
  Hash,
  Calculator,
  Pencil,
  Check,
  X,
  Sparkles,
  Info,
  CheckCircle2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfidenceBar } from "@/components/confidence-bar";
import { extractionApi } from "@/services/pipeline";
import { useToast } from "@/components/ui/toast";
import { useApiErrorToast } from "@/hooks/useApiErrorToast";
import type { CanonicalNPO, ExtractedField, NPOLineItem, NPOTaxItem } from "@/types/api";

interface NPOInvoiceReviewProps {
  documentId: number;
  fields: Record<string, ExtractedField>;
  canonical?: CanonicalNPO | null;
  onFieldUpdated: () => void;
}

export function NPOInvoiceReview({
  documentId,
  fields,
  canonical,
  onFieldUpdated,
}: NPOInvoiceReviewProps) {
  const showError = useApiErrorToast();
  const { push } = useToast();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  // Defensive helper to resolve scalar string value from atomic field wrappers or primitives
  function getScalar(field: unknown): string | null {
    if (field == null) return null;

    if (typeof field === "object" && "value" in field) {
      const val = (field as { value: unknown }).value;
      return val != null ? String(val) : null;
    }

    if (typeof field === "object") {
      return null;
    }

    return String(field);
  }

  // Defensive helper for percentage display ("10%" -> "10%", "10" -> "10%", null -> "—")
  function formatPercent(rateVal: unknown): string {
    const scalar = getScalar(rateVal);
    if (!scalar) return "—";
    return scalar.endsWith("%") ? scalar : `${scalar}%`;
  }

  // Helper to resolve field from canonical or root fields
  function getFieldValue(path: string, fallbackKey?: string): {
    val: string | null;
    confidence?: number;
    provenance?: string;
    quote?: string | null;
    key: string;
  } {
    // 1. Direct path in fields
    if (fields[path]) {
      const f = fields[path];
      return {
        val: f.value != null ? String(f.value) : null,
        confidence: f.confidence,
        provenance: f.provenance,
        quote: f.matched_text,
        key: path,
      };
    }

    // 2. Fallback key in fields
    if (fallbackKey && fields[fallbackKey]) {
      const f = fields[fallbackKey];
      return {
        val: f.value != null ? String(f.value) : null,
        confidence: f.confidence,
        provenance: f.provenance,
        quote: f.matched_text,
        key: fallbackKey,
      };
    }

    // 3. Inspect canonical tree
    if (canonical) {
      const parts = path.split(".");
      let curr: Record<string, unknown> | null = canonical as unknown as Record<string, unknown>;
      for (const p of parts) {
        if (curr && typeof curr === "object" && p in curr) {
          curr = (curr[p] as Record<string, unknown>) ?? null;
        } else {
          curr = null;
          break;
        }
      }
      if (curr) {
        const val = typeof curr === "object" && "value" in curr ? curr.value : curr;
        return {
          val: val != null ? String(val) : null,
          confidence: (curr as { confidence?: number })?.confidence,
          provenance: (curr as { provenance?: string })?.provenance,
          quote: (curr as { matched_text?: string })?.matched_text,
          key: path,
        };
      }
    }

    return { val: null, key: fallbackKey || path };
  }

  async function handleSave(key: string) {
    setIsSaving(true);
    try {
      await extractionApi.updateField(documentId, key, draftValue);
      push({ tone: "success", title: "Field updated", description: key });
      setEditingKey(null);
      onFieldUpdated();
    } catch (err) {
      showError(err, "Could not update field");
    } finally {
      setIsSaving(false);
    }
  }

  // Resolve Line Items collection
  const lineItems: NPOLineItem[] = (() => {
    if (canonical?.line_items && Array.isArray(canonical.line_items)) {
      return canonical.line_items;
    }
    if (fields.line_items?.value && Array.isArray(fields.line_items.value)) {
      return fields.line_items.value;
    }
    return [];
  })();

  // Resolve Taxes collection
  const taxes: NPOTaxItem[] = (() => {
    if (canonical?.taxes && Array.isArray(canonical.taxes)) {
      return canonical.taxes;
    }
    if (fields.taxes?.value && Array.isArray(fields.taxes.value)) {
      return fields.taxes.value;
    }
    return [];
  })();

  // Resolvers for individual fields
  const invNumber = getFieldValue("invoice_information.invoice_number", "invoice_number");
  const invDate = getFieldValue("invoice_information.invoice_date", "invoice_date");
  const currency = getFieldValue("invoice_information.currency", "currency");
  const docType = getFieldValue("invoice_information.document_type", "document_type");

  const sellerName = getFieldValue("seller.name", "seller_name");
  const sellerTaxId = getFieldValue("seller.tax_id", "seller_tax_id");
  const sellerAddress = getFieldValue("seller.address", "seller_address");

  const buyerName = getFieldValue("buyer.name", "buyer_name");
  const buyerTaxId = getFieldValue("buyer.tax_id", "buyer_tax_id");
  const buyerAddress = getFieldValue("buyer.address", "buyer_address");

  const grandTotal = getFieldValue("totals.grand_total", "grand_total_amount");
  const subtotal = getFieldValue("totals.subtotal", "subtotal_net_amount");
  const totalTax = getFieldValue("totals.total_tax", "total_tax_amount");
  const discount = getFieldValue("totals.discount", "discount_amount");
  const shipping = getFieldValue("totals.shipping", "shipping_amount");
  const otherCharges = getFieldValue("totals.other_charges", "other_charges");
  const rounding = getFieldValue("totals.rounding", "rounding_amount");

  const paymentTerms = getFieldValue("payment.payment_terms", "payment_terms");
  const dueDate = getFieldValue("payment.due_date", "due_date");
  const paymentMethod = getFieldValue("payment.payment_method", "payment_method");
  const bankAccount = getFieldValue("payment.bank_account", "account_number");
  const iban = getFieldValue("payment.iban", "iban");
  const swiftBic = getFieldValue("payment.swift_bic", "swift_bic");

  const poNumber = getFieldValue("references.po_number", "po_number");
  const contractNumber = getFieldValue("references.contract_number", "contract_number");
  const deliveryNote = getFieldValue("references.delivery_note_number", "delivery_note_number");
  const orderNumber = getFieldValue("references.order_number", "order_number");

  const renderFieldRow = (
    label: string,
    fieldData: ReturnType<typeof getFieldValue>,
    isMandatory: boolean = false
  ) => {
    const isEditing = editingKey === fieldData.key;
    return (
      <div className="flex items-center justify-between py-2 border-b border-ink-100 last:border-b-0 text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium text-ink-700">{label}</span>
          {isMandatory && (
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-clay-50 text-clay-700 border border-clay-200">
              Mandatory
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {isEditing ? (
            <div className="flex items-center gap-1">
              <Input
                autoFocus
                value={draftValue}
                onChange={(e) => setDraftValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSave(fieldData.key)}
                className="h-7 w-48 text-xs"
              />
              <Button size="icon" variant="ghost" className="h-7 w-7" disabled={isSaving} onClick={() => handleSave(fieldData.key)}>
                <Check className="h-3.5 w-3.5 text-sage-600" />
              </Button>
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setEditingKey(null)}>
                <X className="h-3.5 w-3.5 text-ink-400" />
              </Button>
            </div>
          ) : (
            <>
              <span
                className={`font-data ${
                  fieldData.val != null
                    ? "font-medium text-ink-900"
                    : isMandatory
                    ? "italic text-clay-600 font-medium"
                    : "italic text-ink-400"
                }`}
              >
                {fieldData.val ?? (isMandatory ? "Missing" : "—")}
              </span>
              {fieldData.confidence != null && fieldData.val != null && (
                <div className="w-14 hidden sm:block">
                  <ConfidenceBar value={fieldData.confidence} />
                </div>
              )}
              {fieldData.provenance && (
                <span className="text-[10px] text-ink-400 uppercase tracking-wider font-mono">
                  {fieldData.provenance}
                </span>
              )}
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6 text-ink-400 hover:text-ink-700"
                onClick={() => {
                  setEditingKey(fieldData.key);
                  setDraftValue(fieldData.val ?? "");
                }}
              >
                <Pencil className="h-3 w-3" />
              </Button>
            </>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* 1. Header Summary Banner */}
      <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-ink-500">
              Non-PO Invoice (Canonical Review)
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-sage-50 px-2 py-0.5 text-xs font-medium text-sage-700 border border-sage-200">
              <CheckCircle2 className="h-3 w-3" /> AP Ready
            </span>
          </div>
          <h3 className="text-xl font-semibold text-ink-900">
            {invNumber.val ? `Invoice #${invNumber.val}` : "Unidentified Invoice"}
          </h3>
          <p className="text-xs text-ink-500">
            Issued on {invDate.val || "Unknown Date"} · Currency: {currency.val || "USD"}
          </p>
        </div>

        <div className="flex items-center gap-4 bg-ink-50 rounded-lg p-3 border border-ink-200">
          <div className="text-right">
            <div className="flex items-center justify-end gap-1.5 text-[11px] font-medium uppercase tracking-wider text-ink-500">
              <span>Grand Total</span>
              <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-semibold bg-clay-50 text-clay-700 border border-clay-200">
                Mandatory
              </span>
            </div>
            <div className="text-2xl font-bold text-ink-950 font-data">
              {currency.val ? `${currency.val} ` : "$"}
              {grandTotal.val || "0.00"}
            </div>
          </div>
        </div>
      </div>

      {/* 2. Side-by-Side: Invoice Details & Totals */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Invoice Information */}
        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold border-b border-ink-100 pb-2.5">
            <FileText className="h-4 w-4 text-ink-500" />
            <span>Invoice Information</span>
          </div>
          <div className="divide-y divide-ink-50">
            {renderFieldRow("Invoice Number", invNumber, true)}
            {renderFieldRow("Invoice Date", invDate, true)}
            {renderFieldRow("Currency", currency, true)}
            {renderFieldRow("Document Type", docType, false)}
          </div>
        </div>

        {/* Financial Totals */}
        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold border-b border-ink-100 pb-2.5">
            <Calculator className="h-4 w-4 text-ink-500" />
            <span>Summary Totals</span>
          </div>
          <div className="divide-y divide-ink-50">
            {renderFieldRow("Subtotal", subtotal, false)}
            {renderFieldRow("Total Tax", totalTax, false)}
            {discount.val != null && renderFieldRow("Discount", discount, false)}
            {shipping.val != null && renderFieldRow("Shipping", shipping, false)}
            {otherCharges.val != null && renderFieldRow("Other Charges", otherCharges, false)}
            {rounding.val != null && renderFieldRow("Rounding", rounding, false)}
            {renderFieldRow("Grand Total", grandTotal, true)}
          </div>
        </div>
      </div>

      {/* 3. Side-by-Side: Seller & Buyer Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Seller / Supplier */}
        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold border-b border-ink-100 pb-2.5">
            <Building2 className="h-4 w-4 text-ink-500" />
            <span>Seller / Supplier</span>
          </div>
          <div className="divide-y divide-ink-50">
            {renderFieldRow("Seller Name", sellerName, true)}
            {renderFieldRow("Tax ID / VAT", sellerTaxId, false)}
            {renderFieldRow("Address", sellerAddress, false)}
          </div>
        </div>

        {/* Buyer */}
        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold border-b border-ink-100 pb-2.5">
            <User className="h-4 w-4 text-ink-500" />
            <span>Buyer / Recipient</span>
          </div>
          <div className="divide-y divide-ink-50">
            {renderFieldRow("Buyer Name", buyerName, true)}
            {renderFieldRow("Tax ID / VAT", buyerTaxId, false)}
            {renderFieldRow("Address", buyerAddress, false)}
          </div>
        </div>
      </div>

      {/* 4. Line Items Table */}
      <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-ink-100 pb-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold">
            <Sparkles className="h-4 w-4 text-ink-500" />
            <span>Itemized Line Items</span>
            <span className="text-xs bg-ink-100 text-ink-600 px-2 py-0.5 rounded-full font-mono">
              {lineItems.length}
            </span>
          </div>
          <span className="text-xs text-ink-400">Zero-or-many collection</span>
        </div>

        {lineItems.length === 0 ? (
          <div className="rounded-lg border border-dashed border-ink-200 p-8 text-center bg-ink-50/50">
            <Info className="h-6 w-6 mx-auto text-ink-400 mb-2" />
            <p className="text-sm font-medium text-ink-700">No line items detected</p>
            <p className="text-xs text-ink-500 mt-1 max-w-sm mx-auto">
              Non-PO invoices without itemized line items are structurally valid. Processing is governed by summary totals.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-ink-50 text-ink-500 uppercase tracking-wider font-semibold border-b border-ink-200">
                <tr>
                  <th className="px-3 py-2.5 w-10">#</th>
                  <th className="px-3 py-2.5">Description</th>
                  <th className="px-3 py-2.5 text-right">Qty</th>
                  <th className="px-3 py-2.5">UOM</th>
                  <th className="px-3 py-2.5 text-right">Unit Price</th>
                  <th className="px-3 py-2.5 text-right">Net Amount</th>
                  <th className="px-3 py-2.5 text-right">Tax Rate</th>
                  <th className="px-3 py-2.5 text-right">Tax Amount</th>
                  <th className="px-3 py-2.5 text-right">Gross Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 font-data">
                {lineItems.map((item, idx) => (
                  <tr key={idx} className="hover:bg-ink-50/50">
                    <td className="px-3 py-2 text-ink-500 font-mono">
                      {getScalar(item.line_number) ?? idx + 1}
                    </td>
                    <td className="px-3 py-2 font-sans font-medium text-ink-900 max-w-xs truncate">
                      {getScalar(item.description) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-800">
                      {getScalar(item.quantity) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-ink-500">
                      {getScalar(item.uom ?? item.unit_of_measure) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-800">
                      {getScalar(item.unit_price) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-medium text-ink-950">
                      {getScalar(item.net_amount) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-500">
                      {formatPercent(item.tax_rate)}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-800">
                      {getScalar(item.tax_amount) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-semibold text-ink-950">
                      {getScalar(item.gross_amount) ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 5. Tax Breakdown Table */}
      <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-ink-100 pb-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold">
            <Calculator className="h-4 w-4 text-ink-500" />
            <span>Tax Breakdown</span>
            <span className="text-xs bg-ink-100 text-ink-600 px-2 py-0.5 rounded-full font-mono">
              {taxes.length}
            </span>
          </div>
          <span className="text-xs text-ink-400">Zero-or-many collection</span>
        </div>

        {taxes.length === 0 ? (
          <div className="rounded-lg border border-dashed border-ink-200 p-6 text-center bg-ink-50/50">
            <Info className="h-5 w-5 mx-auto text-ink-400 mb-1" />
            <p className="text-xs font-medium text-ink-600">No tax breakdown detected</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-ink-50 text-ink-500 uppercase tracking-wider font-semibold border-b border-ink-200">
                <tr>
                  <th className="px-3 py-2.5">Tax Type</th>
                  <th className="px-3 py-2.5 text-right">Taxable Amount</th>
                  <th className="px-3 py-2.5 text-right">Rate %</th>
                  <th className="px-3 py-2.5 text-right">Tax Amount</th>
                  <th className="px-3 py-2.5">Exemption Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 font-data">
                {taxes.map((t, idx) => (
                  <tr key={idx} className="hover:bg-ink-50/50">
                    <td className="px-3 py-2 font-sans font-medium text-ink-900">
                      {getScalar(t.tax_type) ?? "VAT / Tax"}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-800">
                      {getScalar(t.taxable_amount) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-ink-800">
                      {formatPercent(t.tax_rate ?? t.rate_percentage)}
                    </td>
                    <td className="px-3 py-2 text-right font-medium text-ink-950">
                      {getScalar(t.tax_amount) ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-ink-500 font-sans">
                      {getScalar(t.exemption_reason) ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 6. Side-by-Side: Payment & References */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Payment Information */}
        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold border-b border-ink-100 pb-2.5">
            <CreditCard className="h-4 w-4 text-ink-500" />
            <span>Payment & Bank Details</span>
          </div>
          <div className="divide-y divide-ink-50">
            {renderFieldRow("Payment Terms", paymentTerms, false)}
            {renderFieldRow("Due Date", dueDate, false)}
            {renderFieldRow("Payment Method", paymentMethod, false)}
            {renderFieldRow("Bank Account", bankAccount, false)}
            {renderFieldRow("IBAN", iban, false)}
            {renderFieldRow("SWIFT / BIC", swiftBic, false)}
          </div>
        </div>

        {/* References */}
        <div className="rounded-xl border border-ink-200 bg-white p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 text-ink-800 font-semibold border-b border-ink-100 pb-2.5">
            <Hash className="h-4 w-4 text-ink-500" />
            <span>References</span>
          </div>
          <div className="divide-y divide-ink-50">
            {renderFieldRow("PO Number", poNumber, false)}
            {renderFieldRow("Contract Number", contractNumber, false)}
            {renderFieldRow("Delivery Note", deliveryNote, false)}
            {renderFieldRow("Order Number", orderNumber, false)}
          </div>
        </div>
      </div>
    </div>
  );
}
