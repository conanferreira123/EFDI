"""
Unit and integration tests for Phase 4: Rule + LLM Parallel Execution & Orchestration.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.extraction.base import (
    ExtractedField,
    ExtractionContext,
    ExtractionEngine,
    ExtractionResultData,
)
from app.extraction.factory import get_extraction_engine
from app.extraction.parallel_orchestrator import (
    DualExtractionResult,
    HybridExtractor,
    ParallelExtractionOrchestrator,
)


def test_parallel_orchestrator_both_succeed():
    """Verify dual extraction when both Rule and LLM extractors succeed."""
    mock_rule = MagicMock()
    mock_rule.extract.return_value = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-RULE-101", confidence=0.90)},
        engine_name="rule_based",
    )

    mock_llm = MagicMock()
    mock_llm.extract.return_value = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-LLM-101", confidence=0.95)},
        engine_name="llm_based",
    )

    orchestrator = ParallelExtractionOrchestrator(
        rule_extractor=mock_rule,
        llm_extractor=mock_llm,
    )

    ctx = ExtractionContext(full_text="Invoice Number: INV-101", document_type="POI")
    dual_res = orchestrator.run_parallel(ctx)

    assert isinstance(dual_res, DualExtractionResult)
    assert dual_res.has_rule_result is True
    assert dual_res.has_llm_result is True
    assert dual_res.rule_result.fields["invoice_number"].value == "INV-RULE-101"
    assert dual_res.llm_result.fields["invoice_number"].value == "INV-LLM-101"
    assert dual_res.rule_error is None
    assert dual_res.llm_error is None


def test_parallel_orchestrator_rule_succeeds_llm_fails():
    """Verify fault isolation when LLM fails: Rule result is preserved and LLM error recorded."""
    mock_rule = MagicMock()
    mock_rule.extract.return_value = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-RULE-202", confidence=0.88)},
        engine_name="rule_based",
    )

    mock_llm = MagicMock()
    mock_llm.extract.side_effect = RuntimeError("OpenAI API connection timeout")

    orchestrator = ParallelExtractionOrchestrator(
        rule_extractor=mock_rule,
        llm_extractor=mock_llm,
    )

    ctx = ExtractionContext(full_text="Invoice Number: INV-202", document_type="POI")
    dual_res = orchestrator.run_parallel(ctx)

    assert dual_res.has_rule_result is True
    assert dual_res.has_llm_result is False
    assert dual_res.rule_result.fields["invoice_number"].value == "INV-RULE-202"
    assert "OpenAI API connection timeout" in dual_res.llm_error
    assert dual_res.rule_error is None


def test_parallel_orchestrator_llm_succeeds_rule_fails():
    """Verify fault isolation when Rule fails: LLM result is preserved and Rule error recorded."""
    mock_rule = MagicMock()
    mock_rule.extract.side_effect = ValueError("Rule regex engine memory error")

    mock_llm = MagicMock()
    mock_llm.extract.return_value = ExtractionResultData(
        document_type="POI",
        fields={"invoice_number": ExtractedField(value="INV-LLM-303", confidence=0.96)},
        engine_name="llm_based",
    )

    orchestrator = ParallelExtractionOrchestrator(
        rule_extractor=mock_rule,
        llm_extractor=mock_llm,
    )

    ctx = ExtractionContext(full_text="Invoice Number: INV-303", document_type="POI")
    dual_res = orchestrator.run_parallel(ctx)

    assert dual_res.has_rule_result is False
    assert dual_res.has_llm_result is True
    assert dual_res.llm_result.fields["invoice_number"].value == "INV-LLM-303"
    assert "Rule regex engine memory error" in dual_res.rule_error
    assert dual_res.llm_error is None


def test_parallel_orchestrator_both_fail():
    """Verify safe error containment when both extractors raise exceptions."""
    mock_rule = MagicMock()
    mock_rule.extract.side_effect = RuntimeError("Rule crash")

    mock_llm = MagicMock()
    mock_llm.extract.side_effect = RuntimeError("LLM crash")

    orchestrator = ParallelExtractionOrchestrator(
        rule_extractor=mock_rule,
        llm_extractor=mock_llm,
    )

    ctx = ExtractionContext(full_text="Corrupted Doc", document_type="POI")
    dual_res = orchestrator.run_parallel(ctx)

    assert dual_res.has_rule_result is False
    assert dual_res.has_llm_result is False
    assert "Rule crash" in dual_res.rule_error
    assert "LLM crash" in dual_res.llm_error


def test_hybrid_extractor_delegates_to_orchestrator():
    """Verify HybridExtractor implements ExtractionEngine contract and wraps dual execution."""
    mock_orchestrator = MagicMock()
    mock_orchestrator.run_parallel.return_value = DualExtractionResult(
        document_type="POI",
        rule_result=ExtractionResultData(
            document_type="POI",
            fields={"invoice_number": ExtractedField(value="INV-123", confidence=0.90)},
        ),
        llm_result=ExtractionResultData(
            document_type="POI",
            fields={"invoice_number": ExtractedField(value="INV-123", confidence=0.95)},
        ),
    )

    hybrid_engine = HybridExtractor(orchestrator=mock_orchestrator)
    ctx = ExtractionContext(full_text="Invoice: INV-123", document_type="POI")
    res = hybrid_engine.extract(ctx)

    assert isinstance(res, ExtractionResultData)
    assert res.engine_name == "hybrid"
    assert res.fields["invoice_number"].value == "INV-123"


def test_factory_returns_hybrid_engine():
    """Verify get_extraction_engine('hybrid') returns a HybridExtractor instance."""
    engine = get_extraction_engine("hybrid")
    assert isinstance(engine, HybridExtractor)
    assert engine.name == "hybrid"
