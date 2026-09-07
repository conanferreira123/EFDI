"""
Explicit, non-destructive validation engine for OCR and structured table data.

Performs mathematical balance checks, required field validation, and data consistency checks.
Flags inconsistencies without mutating or altering any OCR values.
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from enum import Enum


class ValidationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class ValidationFlag:
    """A specific validation assertion result or warning flag."""
    rule_id: str
    field_name: str
    severity: ValidationSeverity
    message: str
    is_valid: bool
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["severity"] = self.severity.value
        return res


@dataclass
class DocumentValidationResult:
    """Overall validation outcome for an OCR-processed document."""
    is_valid: bool
    flags: List[ValidationFlag] = field(default_factory=list)
    line_item_validations: List[Dict[str, Any]] = field(default_factory=list)
    summary_validations: Dict[str, Any] = field(default_factory=dict)
    passed_rules_count: int = 0
    failed_rules_count: int = 0
    warning_rules_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "passed_rules_count": self.passed_rules_count,
            "failed_rules_count": self.failed_rules_count,
            "warning_rules_count": self.warning_rules_count,
            "flags": [flag.to_dict() for flag in self.flags],
            "line_item_validations": self.line_item_validations,
            "summary_validations": self.summary_validations,
        }


class OCRValidator:
    """
    Validates arithmetic consistency and field requirements.
    Uses configurable tolerances.
    """

    def __init__(
        self,
        amount_tolerance_abs: float = 1.0,
        amount_tolerance_rel: float = 0.02,
    ):
        self.amount_tolerance_abs = amount_tolerance_abs
        self.amount_tolerance_rel = amount_tolerance_rel

    def _is_close(self, val1: Optional[float], val2: Optional[float]) -> bool:
        if val1 is None or val2 is None:
            return False
        diff = abs(val1 - val2)
        if diff <= self.amount_tolerance_abs:
            return True
        ref = max(abs(val1), abs(val2))
        return (diff / ref) <= self.amount_tolerance_rel if ref > 0 else True

    def validate_line_item(self, item: Any, item_idx: int = 1) -> List[ValidationFlag]:
        """Validate mathematical integrity of an individual line item."""
        flags: List[ValidationFlag] = []

        if hasattr(item, "normalized_quantity"):
            qty = item.normalized_quantity
            price = item.normalized_unit_price
            net = item.normalized_net_amount
            vat = item.normalized_vat_rate
            gross = item.normalized_gross_amount
            desc = item.normalized_description
        elif isinstance(item, dict):
            qty = item.get("normalized_quantity")
            price = item.get("normalized_unit_price")
            net = item.get("normalized_net_amount")
            vat = item.get("normalized_vat_rate")
            gross = item.get("normalized_gross_amount")
            desc = item.get("normalized_description", "")
        else:
            return flags

        # Check description presence
        if not desc or len(desc.strip()) == 0:
            flags.append(
                ValidationFlag(
                    rule_id=f"ITEM_{item_idx}_DESC_MISSING",
                    field_name=f"line_items[{item_idx}].description",
                    severity=ValidationSeverity.WARNING,
                    message=f"Line item #{item_idx} has empty description",
                    is_valid=False,
                )
            )

        # Check: Quantity * Unit Price ≈ Net Amount
        if qty is not None and price is not None:
            expected_net = round(qty * price, 2)
            if net is not None:
                matches = self._is_close(expected_net, net)
                flags.append(
                    ValidationFlag(
                        rule_id=f"ITEM_{item_idx}_MATH_QTY_PRICE",
                        field_name=f"line_items[{item_idx}].net_amount",
                        severity=ValidationSeverity.INFO if matches else ValidationSeverity.WARNING,
                        message=f"Item #{item_idx} Qty ({qty}) * UnitPrice ({price}) vs NetAmount ({net})",
                        is_valid=matches,
                        expected_value=expected_net,
                        actual_value=net,
                    )
                )

        # Check: Net Amount * (1 + VAT Rate) ≈ Gross Amount
        if net is not None and vat is not None:
            expected_gross = round(net * (1.0 + vat), 2)
            if gross is not None:
                matches = self._is_close(expected_gross, gross)
                flags.append(
                    ValidationFlag(
                        rule_id=f"ITEM_{item_idx}_MATH_NET_VAT_GROSS",
                        field_name=f"line_items[{item_idx}].gross_amount",
                        severity=ValidationSeverity.INFO if matches else ValidationSeverity.WARNING,
                        message=f"Item #{item_idx} Net ({net}) + VAT ({vat*100:.0f}%) vs Gross ({gross})",
                        is_valid=matches,
                        expected_value=expected_gross,
                        actual_value=gross,
                    )
                )

        return flags

    def validate_document(
        self,
        line_items: List[Any],
        raw_full_text: str = "",
        summary_data: Optional[Dict[str, Any]] = None,
    ) -> DocumentValidationResult:
        """Validate entire document table, line items, and header requirements."""
        all_flags: List[ValidationFlag] = []
        item_results: List[Dict[str, Any]] = []

        # 1. Validate individual line items
        calculated_net_total = 0.0
        calculated_gross_total = 0.0
        has_net_amounts = False

        for idx, itm in enumerate(line_items, 1):
            item_flags = self.validate_line_item(itm, item_idx=idx)
            all_flags.extend(item_flags)

            net = getattr(itm, "normalized_net_amount", None)
            gross = getattr(itm, "normalized_gross_amount", None)
            if net is not None:
                calculated_net_total += net
                has_net_amounts = True
            if gross is not None:
                calculated_gross_total += gross

            item_results.append({
                "item_index": idx,
                "is_valid": all(f.is_valid for f in item_flags),
                "flags_count": len(item_flags),
            })

        # 2. Header metadata presence checks
        has_invoice_num = any(kw in raw_full_text.upper() for kw in ["INVOICE NO", "INVOICE #", "INV-", "INVOICE NUMBER"])
        all_flags.append(
            ValidationFlag(
                rule_id="DOC_INVOICE_NUM_PRESENT",
                field_name="invoice_number",
                severity=ValidationSeverity.INFO if has_invoice_num else ValidationSeverity.WARNING,
                message="Invoice number token detected in document text",
                is_valid=has_invoice_num,
            )
        )

        has_date = any(kw in raw_full_text.upper() for kw in ["DATE", "DATE OF ISSUE", "INVOICE DATE"])
        all_flags.append(
            ValidationFlag(
                rule_id="DOC_DATE_PRESENT",
                field_name="issue_date",
                severity=ValidationSeverity.INFO if has_date else ValidationSeverity.WARNING,
                message="Date token detected in document text",
                is_valid=has_date,
            )
        )

        has_seller = any(kw in raw_full_text.upper() for kw in ["SELLER", "VENDOR", "SUPPLIER", "FROM:"])
        all_flags.append(
            ValidationFlag(
                rule_id="DOC_SELLER_PRESENT",
                field_name="seller_name",
                severity=ValidationSeverity.INFO if has_seller else ValidationSeverity.WARNING,
                message="Seller/Vendor header detected in document text",
                is_valid=has_seller,
            )
        )

        has_buyer = any(kw in raw_full_text.upper() for kw in ["CLIENT", "BUYER", "BILL TO", "CUSTOMER"])
        all_flags.append(
            ValidationFlag(
                rule_id="DOC_BUYER_PRESENT",
                field_name="buyer_name",
                severity=ValidationSeverity.INFO if has_buyer else ValidationSeverity.WARNING,
                message="Buyer/Client header detected in document text",
                is_valid=has_buyer,
            )
        )

        # 3. Document totals reconciliation
        summary_validations: Dict[str, Any] = {}
        if summary_data:
            reported_subtotal = summary_data.get("subtotal")
            reported_vat = summary_data.get("vat_total")
            reported_grand_total = summary_data.get("grand_total")

            if reported_subtotal is not None and has_net_amounts:
                matches = self._is_close(calculated_net_total, reported_subtotal)
                all_flags.append(
                    ValidationFlag(
                        rule_id="DOC_SUM_ITEMS_VS_SUBTOTAL",
                        field_name="subtotal",
                        severity=ValidationSeverity.INFO if matches else ValidationSeverity.WARNING,
                        message=f"Sum of item nets ({calculated_net_total:.2f}) vs reported subtotal ({reported_subtotal:.2f})",
                        is_valid=matches,
                        expected_value=calculated_net_total,
                        actual_value=reported_subtotal,
                    )
                )

            if reported_subtotal is not None and reported_vat is not None and reported_grand_total is not None:
                expected_total = round(reported_subtotal + reported_vat, 2)
                matches = self._is_close(expected_total, reported_grand_total)
                all_flags.append(
                    ValidationFlag(
                        rule_id="DOC_MATH_SUBTOTAL_VAT_GRAND",
                        field_name="grand_total",
                        severity=ValidationSeverity.INFO if matches else ValidationSeverity.WARNING,
                        message=f"Subtotal ({reported_subtotal:.2f}) + VAT ({reported_vat:.2f}) vs GrandTotal ({reported_grand_total:.2f})",
                        is_valid=matches,
                        expected_value=expected_total,
                        actual_value=reported_grand_total,
                    )
                )

        # Count results
        passed = sum(1 for f in all_flags if f.is_valid)
        failed = sum(1 for f in all_flags if not f.is_valid and f.severity == ValidationSeverity.ERROR)
        warnings = sum(1 for f in all_flags if not f.is_valid and f.severity == ValidationSeverity.WARNING)

        return DocumentValidationResult(
            is_valid=(failed == 0),
            flags=all_flags,
            line_item_validations=item_results,
            summary_validations=summary_validations,
            passed_rules_count=passed,
            failed_rules_count=failed,
            warning_rules_count=warnings,
        )


def validate_ocr_output(
    line_items: List[Any],
    raw_full_text: str = "",
    summary_data: Optional[Dict[str, Any]] = None,
) -> DocumentValidationResult:
    """Convenience helper to validate OCR document output."""
    validator = OCRValidator()
    return validator.validate_document(
        line_items=line_items,
        raw_full_text=raw_full_text,
        summary_data=summary_data,
    )
