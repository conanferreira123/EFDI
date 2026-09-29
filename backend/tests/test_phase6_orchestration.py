"""Phase 6 Unit Tests: ReAct Orchestration and Stateful Duplicate Call Guard.

Tests MAX_ITERATIONS bounds and _is_duplicate_call behavior.
"""
from app.rag.global_agent import MAX_ITERATIONS, _is_duplicate_call, GlobalReActAgent


def test_max_iterations_is_eight():
    assert MAX_ITERATIONS == 8


def test_is_duplicate_call_exact_match():
    executed = [
        {"name": "database_query_tool", "args": {"query": "SELECT COUNT(*) FROM invoices"}},
        {"name": "document_rag_tool", "args": {"query": "payment terms", "document_ids": [1, 2]}},
    ]

    # Exact duplicate
    assert _is_duplicate_call(
        "database_query_tool",
        {"query": "SELECT COUNT(*) FROM invoices"},
        executed,
    ) is True

    # Same tool, different query
    assert _is_duplicate_call(
        "database_query_tool",
        {"query": "SELECT * FROM vendors"},
        executed,
    ) is False

    # Different tool, same query
    assert _is_duplicate_call(
        "financial_calculator_tool",
        {"query": "SELECT COUNT(*) FROM invoices"},
        executed,
    ) is False

    # RAG tool with different document_ids should NOT be blocked
    assert _is_duplicate_call(
        "document_rag_tool",
        {"query": "payment terms", "document_ids": [3, 4]},
        executed,
    ) is False


def test_is_duplicate_call_normalization():
    executed = [
        {"name": "database_query_tool", "args": {"query": "SELECT count(*) FROM invoices  "}},
    ]
    # Whitespace and case differences should still match
    assert _is_duplicate_call(
        "database_query_tool",
        {"query": "  select count(*) from invoices"},
        executed,
    ) is True
