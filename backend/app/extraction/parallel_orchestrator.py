"""
Parallel / Dual Extractor Orchestrator.

Executes RuleBasedExtractor and LLMBasedExtractor independently against the
same ExtractionContext, ensuring complete fault isolation so a failure in
one engine does not impact or corrupt the other.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from typing import Optional

from app.extraction.base import (
    ExtractedField,
    ExtractionContext,
    ExtractionEngine,
    ExtractionResultData,
)
from app.extraction.llm_extractor import LLMBasedExtractor
from app.extraction.rule_based import RuleBasedExtractor

logger = logging.getLogger(__name__)


@dataclass
class DualExtractionResult:
    """
    Container capturing the raw, independent extraction outputs of both
    Rule-Based and LLM-Based extractors for downstream reconciliation.
    """

    document_type: str
    rule_result: Optional[ExtractionResultData] = None
    llm_result: Optional[ExtractionResultData] = None
    rule_error: Optional[str] = None
    llm_error: Optional[str] = None

    @property
    def has_rule_result(self) -> bool:
        return self.rule_result is not None and bool(self.rule_result.fields)

    @property
    def has_llm_result(self) -> bool:
        return self.llm_result is not None and bool(self.llm_result.fields)


class ParallelExtractionOrchestrator:
    """
    Orchestrates concurrent or isolated execution of both extraction engines.
    """

    def __init__(
        self,
        rule_extractor: Optional[RuleBasedExtractor] = None,
        llm_extractor: Optional[LLMBasedExtractor] = None,
    ):
        self.rule_extractor = rule_extractor or RuleBasedExtractor()
        self.llm_extractor = llm_extractor or LLMBasedExtractor()

    def run_parallel(self, context: ExtractionContext) -> DualExtractionResult:
        """
        Execute Rule-Based and LLM-Based extractors concurrently with full
        exception isolation.
        """
        doc_type = context.document_type
        rule_res: Optional[ExtractionResultData] = None
        llm_res: Optional[ExtractionResultData] = None
        rule_err: Optional[str] = None
        llm_err: Optional[str] = None

        def _exec_rule():
            return self.rule_extractor.extract(context)

        def _exec_llm():
            return self.llm_extractor.extract(context)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_rule = executor.submit(_exec_rule)
            future_llm = executor.submit(_exec_llm)

            try:
                rule_res = future_rule.result()
            except Exception as exc:
                rule_err = str(exc)
                logger.error("RuleBasedExtractor failed in parallel execution: %s", exc)

            try:
                llm_res = future_llm.result()
            except Exception as exc:
                llm_err = str(exc)
                logger.error("LLMBasedExtractor failed in parallel execution: %s", exc)

        return DualExtractionResult(
            document_type=doc_type,
            rule_result=rule_res,
            llm_result=llm_res,
            rule_error=rule_err,
            llm_error=llm_err,
        )


class HybridExtractor(ExtractionEngine):
    """
    Hybrid extraction engine implementing the ExtractionEngine contract.
    Orchestrates dual execution and provides an initial consolidated
    ExtractionResultData before Phase 5 reconciliation.
    """

    name = "hybrid"

    def __init__(
        self,
        orchestrator: Optional[ParallelExtractionOrchestrator] = None,
    ):
        self.orchestrator = orchestrator or ParallelExtractionOrchestrator()

    def extract(
        self,
        context_or_text: ExtractionContext | str | None = None,
        document_type: str | None = None,
        *,
        context: ExtractionContext | None = None,
        text: str | None = None,
    ) -> ExtractionResultData:
        # Resolve ExtractionContext from context or legacy text + document_type
        if context is not None:
            ctx = context
        elif isinstance(context_or_text, ExtractionContext):
            ctx = context_or_text
        else:
            resolved_text = text if text is not None else (context_or_text or "")
        doc_type = ctx.document_type
        logger.info(
            "HYBRID EXTRACTION\n  Rule-Based: enabled\n  LLM-Based: enabled\n  LLM provider: %s\n  model: %s\n  document_type: %s",
            getattr(self.orchestrator.llm_extractor, "provider", "mistral"),
            getattr(self.orchestrator.llm_extractor, "model_name", "mistral-small-2603"),
            doc_type,
        )

        dual_result = self.orchestrator.run_parallel(ctx)

        from app.extraction.reconciliation import ReconciliationEngine

        return ReconciliationEngine.reconcile(dual_result, ctx)

