"""
Unit and integration tests for Phase 5: Deterministic Reconciliation & Provenance Tracking.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.extraction.base import (
    ExtractedField,
    ExtractionContext,
    ExtractionResultData,
)
from app.extraction.parallel_orchestrator import DualExtractionResult, HybridExtractor
from app.extraction.reconciliation import ReconciliationEngine


def test_reconciliation_exact_agreement():
    """Verify exact match between Rule and LLM yields agreed provenance and boosted confidence."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-2026-999", confidence=0.90, matched_text="INV-2026-999")},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-2026-999", confidence=0.92, matched_text="INV-2026-999")},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="Invoice: INV-2026-999", document_type="POI")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["invoice_number"]

    assert field.value == "INV-2026-999"
    assert field.provenance == "agreed"
    assert field.confidence == 0.97  # 0.92 + 0.05
    assert field.conflict_value is None


def test_reconciliation_normalized_date_agreement():
    """Verify different date formats that parse to same ISO date are reconciled as agreed."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_date": ExtractedField(value="15/06/2026", confidence=0.88)},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_date": ExtractedField(value="2026-06-15", confidence=0.94)},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="Date: 15/06/2026", document_type="POI")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["invoice_date"]

    assert field.value == "2026-06-15"
    assert field.provenance == "agreed"
    assert field.confidence == 0.99


def test_reconciliation_normalized_amount_agreement():
    """Verify currency/comma formatted amounts that normalize to same float are agreed."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"grand_total_amount": ExtractedField(value="25,000.00", confidence=0.85)},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"grand_total_amount": ExtractedField(value="25000.00", confidence=0.90)},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="Total: 25,000.00", document_type="POI")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["grand_total_amount"]

    assert field.value == "25000.00"
    assert field.provenance == "agreed"


def test_reconciliation_only_rule_found():
    """Verify single-extractor find assigns rule_based provenance."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"po_number": ExtractedField(value="PO-9988", confidence=0.89)},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"po_number": ExtractedField(value=None, confidence=0.0)},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="PO: PO-9988", document_type="POI")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["po_number"]

    assert field.value == "PO-9988"
    assert field.provenance == "rule_based"
    assert field.conflict_value is None


def test_reconciliation_only_llm_found():
    """Verify single-extractor find assigns llm provenance."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"seller_name": ExtractedField(value=None, confidence=0.0)},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"seller_name": ExtractedField(value="Acme Corporation", confidence=0.95)},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="Vendor: Acme Corporation", document_type="POI")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["seller_name"]

    assert field.value == "Acme Corporation"
    assert field.provenance == "llm"
    assert field.conflict_value is None


def test_reconciliation_deterministic_date_resolution():
    """Verify unparseable date vs valid ISO date is resolved to valid date."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_date": ExtractedField(value="Unparseable Text Date", confidence=0.40)},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_date": ExtractedField(value="2026-03-25", confidence=0.90)},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="Date: 25th March 2026", document_type="POI")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["invoice_date"]

    assert field.value == "2026-03-25"
    assert field.provenance == "reconciled_llm_date"
    assert field.conflict_value == "Unparseable Text Date"


def test_reconciliation_table_amount_verification():
    """Verify conflicting amounts are resolved when one matches table calculation."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"subtotal_net_amount": ExtractedField(value="5000.00", confidence=0.80)},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"subtotal_net_amount": ExtractedField(value="4000.00", confidence=0.85)},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(
        full_text="Broken OCR summary text",
        document_type="POI",
        table_data={
            "line_items": [
                {"net_amount": "2000.00"},
                {"net_amount": "3000.00"},
            ]
        },
    )

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["subtotal_net_amount"]

    assert field.value == "5000.00"
    assert field.provenance == "reconciled_table_verified"
    assert field.conflict_value == "4000.00"


def test_reconciliation_unresolved_conflict_preservation():
    """Verify unresolvable conflicting values are preserved with conflict_value and unresolved_conflict provenance."""
    rule_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-RULE-111", confidence=0.85)},
    )
    llm_res = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-LLM-222", confidence=0.92)},
    )
    dual = DualExtractionResult(document_type="POI", rule_result=rule_res, llm_result=llm_res)
    ctx = ExtractionContext(full_text="Ambiguous Invoice Text", document_type="POI")

    reconciled = ReconciliationEngine.reconcile(dual, ctx)
    field = reconciled.fields["invoice_number"]

    assert field.provenance == "unresolved_conflict"
    assert field.value == "INV-LLM-222"  # Primary value for workflow continuity
    assert field.conflict_value == "INV-RULE-111"  # Competing value preserved
    assert field.confidence == 0.85  # Reduced to minimum confidence


def test_hybrid_extractor_end_to_end_reconciliation():
    """Verify HybridExtractor calls orchestrator and ReconciliationEngine to produce reconciled result."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.run_parallel.return_value = DualExtractionResult(
        document_type="POI",
        rule_result=ExtractionResultData(
            document_type="POI",
            fields={"invoice_number": ExtractedField(value="INV-MATCH-10", confidence=0.90)},
        ),
        llm_result=ExtractionResultData(
            document_type="POI",
            fields={"invoice_number": ExtractedField(value="INV-MATCH-10", confidence=0.95)},
        ),
    )

    hybrid_engine = HybridExtractor(orchestrator=mock_orchestrator)
    ctx = ExtractionContext(full_text="Invoice: INV-MATCH-10", document_type="POI")
    result = hybrid_engine.extract(ctx)

    assert result.engine_name == "hybrid"
    assert result.fields["invoice_number"].value == "INV-MATCH-10"
    assert result.fields["invoice_number"].provenance == "agreed"
