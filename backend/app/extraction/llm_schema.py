"""Pydantic schema definitions for LLM extraction.

Provides:
1. Dynamic Pydantic schema generation for legacy / flat document types.
2. Canonical hierarchical Pydantic models for format-agnostic NPO extraction,
   including nested objects (seller, buyer, totals, payment, references)
   and conditional arrays (line_items[], taxes[]).
"""
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field, create_model, model_validator

from app.extraction.field_schemas import (
    FieldDef,
    SYSTEM_METADATA_KEYS,
    get_full_field_schema,
    is_hierarchical_schema,
    map_npo_canonical_to_flat,
)


class LLMFieldItem(BaseModel):
    """A single field extracted with grounded evidence.

    Adheres strictly to the core requirement:
    - Missing or unverified fields MUST have value=None, confidence=0.0, is_found=False.
    - Fields are never fabricated, inferred, or hallucinated.
    """

    value: Optional[str] = Field(
        default=None,
        description="The extracted value as a clean string, or null if not found in the document.",
    )
    confidence: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Model confidence in the extracted value from 0.0 to 1.0.",
    )
    source_quote: Optional[str] = Field(
        default=None,
        description="Exact verbatim text snippet from the document proving this value.",
    )
    is_found: bool = Field(
        default=False,
        description="True if value was found and non-null in the document.",
    )
    provenance: Optional[str] = Field(
        default=None,
        description="Source provenance: 'llm', 'rule_based', 'agreed', 'system', 'manual'.",
    )
    conflict_value: Optional[str] = Field(
        default=None,
        description="Competing extracted value if an unresolved conflict exists.",
    )

    @model_validator(mode="before")
    @classmethod
    def pre_validate(cls, data: Any) -> Any:
        if data is None:
            return {"value": None, "confidence": 0.0, "is_found": False}
        if isinstance(data, (str, int, float)):
            val_str = str(data).strip()
            return {
                "value": val_str if val_str else None,
                "confidence": 0.85 if val_str else 0.0,
                "is_found": bool(val_str),
                "source_quote": val_str if val_str else None,
            }
        if isinstance(data, dict):
            val = data.get("value")
            if val is not None:
                val_str = str(val).strip()
                data["value"] = val_str if val_str else None
                if not val_str:
                    data["is_found"] = False
                    data["confidence"] = 0.0
                    data["source_quote"] = None
            else:
                data["is_found"] = False
                data["confidence"] = 0.0
                data["source_quote"] = None
        return data

    @model_validator(mode="after")
    def sync_is_found_and_confidence(self) -> "LLMFieldItem":
        if self.value is not None and str(self.value).strip():
            self.is_found = True
            if self.confidence <= 0.0:
                self.confidence = 0.85
        else:
            self.value = None
            self.is_found = False
            self.confidence = 0.0
            self.source_quote = None
        return self


    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 2),
            "matched_text": self.source_quote,
            "is_found": self.is_found,
            "provenance": self.provenance or ("llm" if self.is_found else None),
            "conflict_value": self.conflict_value,
        }


# Type alias for clarity across the codebase
ExtractedValue = LLMFieldItem


# =====================================================================
# CANONICAL NPO SECTION PAYLOAD MODELS
# =====================================================================

class NPOInvoiceInformationPayload(BaseModel):
    """Core invoice identification and issue details."""
    invoice_number: Optional[LLMFieldItem] = Field(
        default=None,
        description="Unique invoice reference number / code.",
    )
    invoice_date: Optional[LLMFieldItem] = Field(
        default=None,
        description="Issue date of the invoice (normalized to YYYY-MM-DD if unambiguous).",
    )
    currency: Optional[LLMFieldItem] = Field(
        default=None,
        description="Standard 3-letter ISO currency code (e.g. USD, EUR, INR) supported by explicit text evidence.",
    )
    document_type: Optional[LLMFieldItem] = Field(
        default=None,
        description="Invoice document category / type (e.g. 'NPO', 'Commercial Invoice', 'Tax Invoice').",
    )


class NPOSellerPayload(BaseModel):
    """Vendor / Supplier / Issuer commercial identity."""
    name: Optional[LLMFieldItem] = Field(
        default=None,
        description="Legal or business trade name of the entity issuing the invoice. Mandatory processing core.",
    )
    tax_id: Optional[LLMFieldItem] = Field(
        default=None,
        description="Seller's tax ID, GSTIN, VAT ID, or equivalent registration code (optional, null if unstated).",
    )
    address: Optional[LLMFieldItem] = Field(
        default=None,
        description="Physical or mailing address of the seller entity (optional, null if unstated).",
    )


class NPOBuyerPayload(BaseModel):
    """Customer / Client / Bill-To commercial identity."""
    name: Optional[LLMFieldItem] = Field(
        default=None,
        description="Legal or business name of the customer/recipient being billed. Mandatory processing core.",
    )
    tax_id: Optional[LLMFieldItem] = Field(
        default=None,
        description="Buyer's tax ID, GSTIN, VAT ID, or equivalent registration code (optional, null if unstated).",
    )
    address: Optional[LLMFieldItem] = Field(
        default=None,
        description="Physical or mailing address of the buyer entity (optional, null if unstated).",
    )


class NPOLineItemPayload(BaseModel):
    """A single commercial product or service itemization.

    Zero-or-many collection item. Individual line-item properties must be nullable when
    unsupported by the document. Do NOT infer quantity=1 or unit_price=net_amount
    unless the document explicitly supports that interpretation.
    """
    description: Optional[LLMFieldItem] = Field(
        default=None,
        description="Item or service description, narrative, or milestone label (or null if unstated).",
    )
    quantity: Optional[LLMFieldItem] = Field(
        default=None,
        description="Quantity billed (numeric clean string, or null if unstated). Do NOT infer quantity=1.",
    )
    uom: Optional[LLMFieldItem] = Field(
        default=None,
        description="Unit of measure (e.g., EA, HRS, MONTH, KG, or null if unstated).",
    )
    unit_price: Optional[LLMFieldItem] = Field(
        default=None,
        description="Price per unit before tax (clean decimal string, or null if unstated). Do NOT infer unit_price=net_amount.",
    )
    net_amount: Optional[LLMFieldItem] = Field(
        default=None,
        description="Line net total amount before tax (clean decimal string, or null if unstated).",
    )
    tax_rate: Optional[LLMFieldItem] = Field(
        default=None,
        description="Tax / VAT rate percentage applied to this line (or null if unstated).",
    )
    tax_amount: Optional[LLMFieldItem] = Field(
        default=None,
        description="Tax / VAT monetary amount for this line (or null if unstated).",
    )
    gross_amount: Optional[LLMFieldItem] = Field(
        default=None,
        description="Line gross total amount including tax (clean decimal string, or null if unstated).",
    )


class NPOTaxItemPayload(BaseModel):
    """A distinct tax rate and amount breakdown entry (zero-or-many collection)."""
    tax_type: Optional[LLMFieldItem] = Field(
        default=None,
        description="Type of tax (e.g., 'VAT', 'GST', 'CGST', 'Sales Tax', or null if unstated).",
    )
    tax_rate: Optional[LLMFieldItem] = Field(
        default=None,
        description="Explicitly stated tax percentage/rate (or null if unstated).",
    )
    taxable_amount: Optional[LLMFieldItem] = Field(
        default=None,
        description="Net base taxable amount subject to this tax rate (or null if unstated).",
    )
    tax_amount: Optional[LLMFieldItem] = Field(
        default=None,
        description="Monetary tax amount charged for this rate (or null if unstated).",
    )


class NPOTotalsPayload(BaseModel):
    """Document-level financial totals and adjustments."""
    subtotal: Optional[LLMFieldItem] = Field(
        default=None,
        description="Invoice net amount before tax / taxable base (optional, null if unstated).",
    )
    total_tax: Optional[LLMFieldItem] = Field(
        default=None,
        description="Total tax amount charged across all line items/rates (optional, null if unstated).",
    )
    grand_total: Optional[LLMFieldItem] = Field(
        default=None,
        description="Final total gross amount payable including tax. Mandatory processing core.",
    )
    discount: Optional[LLMFieldItem] = Field(
        default=None,
        description="Invoice-level discount amount (optional, null if absent).",
    )
    shipping: Optional[LLMFieldItem] = Field(
        default=None,
        description="Freight / shipping & handling charge (optional, null if absent).",
    )
    other_charges: Optional[LLMFieldItem] = Field(
        default=None,
        description="Miscellaneous fees / surcharges (optional, null if absent).",
    )
    rounding: Optional[LLMFieldItem] = Field(
        default=None,
        description="Rounding adjustment applied to reach the final total (optional, null if absent).",
    )


class NPOPaymentPayload(BaseModel):
    """Banking, payment instructions, and terms."""
    payment_terms: Optional[LLMFieldItem] = Field(
        default=None,
        description="Terms of payment (e.g., 'Net 30', 'Payment upon receipt').",
    )
    due_date: Optional[LLMFieldItem] = Field(
        default=None,
        description="Payment due date (normalized to YYYY-MM-DD).",
    )
    payment_method: Optional[LLMFieldItem] = Field(
        default=None,
        description="Method of payment (e.g., 'Bank Transfer', 'Wire', 'Credit Card').",
    )
    bank_account: Optional[LLMFieldItem] = Field(
        default=None,
        description="Remittance bank account number.",
    )
    iban: Optional[LLMFieldItem] = Field(
        default=None,
        description="International Bank Account Number (IBAN).",
    )
    swift_bic: Optional[LLMFieldItem] = Field(
        default=None,
        description="SWIFT / BIC code for international bank routing.",
    )
    remittance_reference: Optional[LLMFieldItem] = Field(
        default=None,
        description="Structured payment reference / customer account reference.",
    )


class NPOReferencesPayload(BaseModel):
    """Associated cross-document business references."""
    po_number: Optional[LLMFieldItem] = Field(
        default=None,
        description="Referenced purchase order number if mentioned.",
    )
    contract_number: Optional[LLMFieldItem] = Field(
        default=None,
        description="Contract or agreement reference identifier.",
    )
    delivery_note_number: Optional[LLMFieldItem] = Field(
        default=None,
        description="Delivery note / packing slip number.",
    )
    order_number: Optional[LLMFieldItem] = Field(
        default=None,
        description="Sales order or booking confirmation number.",
    )
    other_reference: Optional[LLMFieldItem] = Field(
        default=None,
        description="Any other commercial or legal reference number.",
    )


class NPOExtractionPayload(BaseModel):
    """Canonical Semantic NPO Invoice Extraction Schema Root.

    Represents the full domain structure of a Non-PO invoice independently of
    its visual arrangement (tables, narrative memos, columns, or key-value blocks).
    """
    invoice_information: NPOInvoiceInformationPayload = Field(
        default_factory=NPOInvoiceInformationPayload,
        description="Header invoice metadata.",
    )
    seller: NPOSellerPayload = Field(
        default_factory=NPOSellerPayload,
        description="Vendor / Supplier identity.",
    )
    buyer: NPOBuyerPayload = Field(
        default_factory=NPOBuyerPayload,
        description="Customer / Buyer identity.",
    )
    line_items: List[NPOLineItemPayload] = Field(
        default_factory=list,
        description="Itemized goods or services. Empty if document contains no itemization.",
    )
    taxes: List[NPOTaxItemPayload] = Field(
        default_factory=list,
        description="Tax breakdown by rate. Empty if no tax breakdown is stated.",
    )
    totals: NPOTotalsPayload = Field(
        default_factory=NPOTotalsPayload,
        description="Invoice monetary totals and adjustments.",
    )
    payment: NPOPaymentPayload = Field(
        default_factory=NPOPaymentPayload,
        description="Payment terms and remittance banking details.",
    )
    references: NPOReferencesPayload = Field(
        default_factory=NPOReferencesPayload,
        description="Commercial cross-references.",
    )

    def normalize_values(self) -> None:
        """Apply deterministic date, amount, percentage, and currency normalizations across all sections."""
        from app.extraction.primitives import normalize_amount, normalize_currency, normalize_date

        # 1. Invoice information
        if self.invoice_information.invoice_date and self.invoice_information.invoice_date.value:
            norm_date = normalize_date(self.invoice_information.invoice_date.value)
            if norm_date:
                self.invoice_information.invoice_date.value = norm_date
        if self.invoice_information.currency and self.invoice_information.currency.value:
            norm_curr = normalize_currency(self.invoice_information.currency.value)
            if norm_curr:
                self.invoice_information.currency.value = norm_curr

        # 2. Totals
        for field_name in ["subtotal", "total_tax", "grand_total", "discount", "shipping", "other_charges", "rounding"]:
            item: Optional[LLMFieldItem] = getattr(self.totals, field_name, None)
            if item and item.value:
                norm_amt = normalize_amount(item.value)
                if norm_amt:
                    item.value = norm_amt

        # 3. Payment
        if self.payment.due_date and self.payment.due_date.value:
            norm_due = normalize_date(self.payment.due_date.value)
            if norm_due:
                self.payment.due_date.value = norm_due

        # 4. Line items
        for line in self.line_items:
            for amt_field in ["unit_price", "net_amount", "tax_amount", "gross_amount"]:
                item = getattr(line, amt_field, None)
                if item and item.value:
                    norm_amt = normalize_amount(item.value)
                    if norm_amt:
                        item.value = norm_amt
            if line.quantity and line.quantity.value:
                line.quantity.value = str(line.quantity.value).strip()
            if line.tax_rate and line.tax_rate.value:
                line.tax_rate.value = str(line.tax_rate.value).replace("%", "").strip()

        # 5. Taxes
        for tax in self.taxes:
            for amt_field in ["taxable_amount", "tax_amount"]:
                item = getattr(tax, amt_field, None)
                if item and item.value:
                    norm_amt = normalize_amount(item.value)
                    if norm_amt:
                        item.value = norm_amt
            if tax.tax_rate and tax.tax_rate.value:
                tax.tax_rate.value = str(tax.tax_rate.value).replace("%", "").strip()

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Convert the entire payload into the canonical nested JSON dictionary.

        Every leaf field is converted to its standard {value, confidence, matched_text, is_found} dict.
        """
        self.normalize_values()

        def _extract_section(model_instance: Optional[BaseModel]) -> Dict[str, Any]:
            if model_instance is None:
                return {}
            out = {}
            for field_name in type(model_instance).model_fields:
                item: Optional[LLMFieldItem] = getattr(model_instance, field_name, None)
                if item is not None and isinstance(item, LLMFieldItem):
                    out[field_name] = item.to_dict()
                else:
                    out[field_name] = LLMFieldItem(value=None).to_dict()
            return out

        return {
            "invoice_information": _extract_section(self.invoice_information),
            "seller": _extract_section(self.seller),
            "buyer": _extract_section(self.buyer),
            "line_items": [
                _extract_section(item) for item in self.line_items
            ],
            "taxes": [
                _extract_section(item) for item in self.taxes
            ],
            "totals": _extract_section(self.totals),
            "payment": _extract_section(self.payment),
            "references": _extract_section(self.references),
        }

    def flatten_to_paths(self) -> Dict[str, LLMFieldItem]:
        """Flatten all leaf fields into dot-delimited path keys for validation and indexing.

        e.g. "invoice_information.invoice_number": LLMFieldItem(...)
             "line_items.0.net_amount": LLMFieldItem(...)
        """
        self.normalize_values()
        paths: Dict[str, LLMFieldItem] = {}


        def _traverse(obj: Any, prefix: str):
            if isinstance(obj, LLMFieldItem):
                paths[prefix] = obj
            elif isinstance(obj, BaseModel):
                for f_name in type(obj).model_fields:
                    sub_val = getattr(obj, f_name, None)
                    sub_prefix = f"{prefix}.{f_name}" if prefix else f_name
                    if sub_val is None:
                        paths[sub_prefix] = LLMFieldItem(value=None)
                    else:
                        _traverse(sub_val, sub_prefix)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    sub_prefix = f"{prefix}.{i}"
                    _traverse(item, sub_prefix)

        _traverse(self, "")
        return paths

    def flatten_to_legacy_dict(self) -> Dict[str, Dict[str, Any]]:
        """Flatten canonical fields to legacy flat field keys for backward compatibility."""
        paths = self.flatten_to_paths()
        legacy_dict: Dict[str, Dict[str, Any]] = {}

        for path, item in paths.items():
            flat_key = map_npo_canonical_to_flat(path)
            if flat_key and flat_key != path:
                legacy_dict[flat_key] = item.to_dict()

        return legacy_dict


# =====================================================================
# SCHEMA GENERATION HELPERS
# =====================================================================

def build_dynamic_extraction_model(document_type: str) -> Type[BaseModel]:
    """Dynamically generate a flat Pydantic model for legacy document types.

    Preserves full backward compatibility with the existing test suite and
    legacy non-NPO document types.
    """
    fields_def: list[FieldDef] = get_full_field_schema(document_type)
    field_definitions: dict[str, tuple[Type, Field]] = {}

    for f in fields_def:
        if f.key in SYSTEM_METADATA_KEYS:
            continue
        description = (
            f"Extracted '{f.label}' (field key: '{f.key}', expected data type: {f.field_type})."
        )
        field_definitions[f.key] = (
            Optional[LLMFieldItem],
            Field(default=None, description=description),
        )

    model_name = f"{document_type.upper()}ExtractionPayload"
    DynamicModel = create_model(
        model_name,
        **field_definitions,
        __base__=BaseModel,
    )
    return DynamicModel


def get_extraction_model(document_type: str, hierarchical: bool = True) -> Type[BaseModel]:
    """Retrieve the extraction model for the given document type.

    For NPO documents, returns the canonical hierarchical model `NPOExtractionPayload`.
    For other document types, returns the dynamically generated flat schema.
    """
    if hierarchical and is_hierarchical_schema(document_type):
        return NPOExtractionPayload
    return build_dynamic_extraction_model(document_type)


