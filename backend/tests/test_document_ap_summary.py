"""Unit and Integration Tests for Simplified 5-Section Document-Level AP Summary."""
import re
import uuid
from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import AIMessage

from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.document_agent import (
    DOCUMENT_REACT_SYSTEM_PROMPT,
    DocumentReActAgent,
)
from app.rag.embeddings import get_embedding_service


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def doc_summary_setup(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"ap_analyst_{suffix}",
        email=f"ap_analyst_{suffix}@enterprise.com",
        full_name="AP Analyst",
        password_hash="pw",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    doc = Document(
        original_filename="Acme_Invoice_9021.pdf",
        stored_filename=f"{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=10240,
        file_hash=f"hash_{suffix}",
        status=DocumentStatus.VALIDATED.value,
        uploaded_by=user.id,
    )
    db_session.add(doc)
    db_session.flush()

    chunk_content = (
        "INVOICE INV-9021\n"
        "Date: 2026-09-15\n"
        "Vendor: Acme Supplies Ltd., 100 Industrial Road, Austin TX. Tax ID: US-987654321.\n"
        "Buyer: Global Logistics Corp, 450 Enterprise Way, Dallas TX. Tax ID: US-123456789.\n"
        "Line Items:\n"
        "1. Wireless Mouse Qty: 6 Unit Price: 8,890.00 Amount: 53,340.00\n"
        "2. GPS Tracker Qty: 7 Unit Price: 68,039.00 Amount: 476,273.00\n"
        "Financial Totals:\n"
        "Subtotal: 529,613.00 USD\n"
        "Tax (VAT 10%): 52,961.30 USD\n"
        "Total Amount Due: 582,574.30 USD\n"
        "Payment Terms: 2% early settlement discount if paid within 10 days; Net 30 days.\n"
        "Due Date: 2026-10-15\n"
        "Bank: Chase Bank, Account: 987654321, SWIFT: CHASUS33.\n"
        "Note: Purchase Order number is not referenced in this document."
    )
    embedder = get_embedding_service()
    vec = embedder.generate_embeddings([chunk_content])[0]

    chunk = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_type="SUMMARY",
        content=chunk_content,
        embedding=vec,
        metadata_json={"chunk_index": 0, "page_number": 1, "document_title": "Acme_Invoice_9021.pdf"},
    )
    db_session.add(chunk)
    db_session.commit()

    return {
        "user": user,
        "doc": doc,
        "chunk": chunk,
    }


def test_system_prompt_defines_5_section_ap_summary_directive():
    """Verify that DOCUMENT_REACT_SYSTEM_PROMPT includes the 5-section AP Summary Directive."""
    assert "ACCOUNTS PAYABLE (AP) DOCUMENT SUMMARY DIRECTIVE" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "# Invoice Summary" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "## 1. Invoice Overview" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "## 2. Payment Details" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "## 3. Amount Breakdown" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "## 4. Items / Services" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "## 5. AP Attention" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "ONE assistant response" in DOCUMENT_REACT_SYSTEM_PROMPT
    # Verify previous complex sections are explicitly forbidden
    assert 'Do NOT create separate sections for "Vendor & Buyer"' in DOCUMENT_REACT_SYSTEM_PROMPT


def test_document_agent_produces_5_section_ap_summary(db_session, doc_summary_setup):
    """Verify DocumentReActAgent produces the approved 5-section AP summary with compact table and bullets."""
    user = doc_summary_setup["user"]
    doc = doc_summary_setup["doc"]

    summary_response_text = (
        "# Invoice Summary\n\n"
        "## 1. Invoice Overview\n"
        "Vendor: Acme Supplies Ltd.\n"
        "Invoice Number: INV-9021\n"
        "Invoice Date: 2026-09-15\n"
        "Due Date: 2026-10-15\n"
        "Currency: USD\n"
        "Total Amount Due: $582,574.30\n"
        "PO Number: Not stated in the document.\n\n"
        "## 2. Payment Details\n"
        "Payment Terms: 2% early settlement discount if paid within 10 days; Net 30 days\n"
        "Payment Method: Bank Transfer (Chase Bank)\n"
        "Early Payment Discount: 2% discount if paid on or before 2026-09-25\n\n"
        "## 3. Amount Breakdown\n"
        "Subtotal: $529,613.00\n"
        "Tax: $52,961.30 (VAT 10%)\n"
        "Total: $582,574.30\n\n"
        "## 4. Items / Services\n"
        "| Description | Qty | Unit Price | Amount |\n"
        "|---|---:|---:|---:|\n"
        "| Wireless Mouse | 6 | 8,890.00 | 53,340.00 |\n"
        "| GPS Tracker | 7 | 68,039.00 | 476,273.00 |\n\n"
        "## 5. AP Attention\n"
        "- Purchase order reference is missing from this invoice.\n"
        "- 2% early payment discount expires on 2026-09-25.\n"
        "- Payment due date is 2026-10-15 (Net 30 days)."
    )

    class MockChatModel:
        def __init__(self):
            self.invocations = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.invocations += 1
            if self.invocations == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "document_rag_tool",
                        "args": {"query": "invoice overview line items totals payment terms"},
                        "id": "call_ap_summary_1",
                    }],
                )
            else:
                return AIMessage(content=summary_response_text)

    mock_llm = MockChatModel()
    agent = DocumentReActAgent(db=db_session, llm=mock_llm)
    result = agent.run(document_id=doc.id, query="Summarize this document", user=user)

    assert "# Invoice Summary" in result.content
    assert "## 1. Invoice Overview" in result.content
    assert "## 2. Payment Details" in result.content
    assert "## 3. Amount Breakdown" in result.content
    assert "## 4. Items / Services" in result.content
    assert "## 5. AP Attention" in result.content
    assert "| Description | Qty | Unit Price | Amount |" in result.content
    assert "Wireless Mouse" in result.content
    assert len(result.citations) >= 1


def test_ap_summary_missing_po_and_due_date_stated_as_not_stated(db_session, doc_summary_setup):
    """Verify missing critical fields are stated as 'Not stated in the document.' without hallucination."""
    user = doc_summary_setup["user"]
    doc = doc_summary_setup["doc"]

    summary_text = (
        "# Invoice Summary\n\n"
        "## 1. Invoice Overview\n"
        "Vendor: Acme Supplies Ltd.\n"
        "Invoice Number: INV-9021\n"
        "Invoice Date: 2026-09-15\n"
        "Due Date: Not stated in the document.\n"
        "Currency: USD\n"
        "Total Amount Due: $582,574.30\n"
        "PO Number: Not stated in the document.\n\n"
        "## 2. Payment Details\n"
        "Payment Terms: Due on Receipt\n"
        "Early Payment Discount: None stated in the document.\n\n"
        "## 3. Amount Breakdown\n"
        "Total: $582,574.30\n\n"
        "## 4. Items / Services\n"
        "Itemized details are not stated in the document.\n\n"
        "## 5. AP Attention\n"
        "- Due date is not stated in the document.\n"
        "- Purchase order reference is not stated in the document."
    )

    class MockChatModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content=summary_text)

    agent = DocumentReActAgent(db=db_session, llm=MockChatModel())
    result = agent.run(document_id=doc.id, query="Summarize this document", user=user)

    assert "Due Date: Not stated in the document." in result.content
    assert "PO Number: Not stated in the document." in result.content
    assert "Early Payment Discount: None stated in the document." in result.content


def test_ap_summary_guardrail_sanitization(db_session, doc_summary_setup):
    """Verify that chunk IDs, internal DB IDs, and tool names are removed while table and formatting are preserved."""
    user = doc_summary_setup["user"]
    doc = doc_summary_setup["doc"]

    summary_with_leaks = (
        "# Invoice Summary\n\n"
        "## 1. Invoice Overview\n"
        "Vendor: Acme Supplies Ltd. [Chunk 1112, Page 1]\n"
        "Invoice Number: INV-9021 user_id=402 document_id 881\n"
        "Total Amount Due: $500.00\n\n"
        "## 4. Items / Services\n"
        "| Description | Qty | Unit Price | Amount |\n"
        "|---|---:|---:|---:|\n"
        "| Widget | 5 | 100.00 | 500.00 |\n\n"
        "## 5. AP Attention\n"
        "- Verified using database_query_tool and document_rag_tool."
    )

    class MockChatModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content=summary_with_leaks)

    agent = DocumentReActAgent(db=db_session, llm=MockChatModel())
    result = agent.run(document_id=doc.id, query="Summarize this document", user=user)

    assert "Chunk 1112" not in result.content
    assert "user_id=402" not in result.content
    assert "881" not in result.content
    assert "database_query_tool" not in result.content
    assert "document_rag_tool" not in result.content
    # Table syntax must remain intact
    assert "| Description | Qty | Unit Price | Amount |" in result.content
    assert "| Widget | 5 | 100.00 | 500.00 |" in result.content


def test_ap_summary_synthesis_prompt_reinforces_5_sections(db_session, doc_summary_setup):
    """Verify that synthesis prompt reinforces the 5 AP summary sections when max iterations reached."""
    user = doc_summary_setup["user"]
    doc = doc_summary_setup["doc"]

    captured_messages = []

    class MockChatModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            captured_messages.append(messages)
            if len(captured_messages) < 6:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "document_rag_tool",
                        "args": {"query": f"search_{len(captured_messages)}"},
                        "id": f"tc_{len(captured_messages)}",
                    }],
                )
            return AIMessage(content="# Invoice Summary\n\nSynthesized summary.")

    agent = DocumentReActAgent(db=db_session, llm=MockChatModel())
    res = agent.run(document_id=doc.id, query="Summarize this document", user=user)

    assert "# Invoice Summary" in res.content
    last_call_messages = captured_messages[-1]
    synthesis_msg = last_call_messages[-1]
    assert "Accounts Payable Invoice Summary" in synthesis_msg.content
    assert "## 1. Invoice Overview, ## 2. Payment Details, ## 3. Amount Breakdown, ## 4. Items / Services, ## 5. AP Attention" in synthesis_msg.content


def test_system_prompt_defines_normal_question_rules():
    """Verify system prompt explicitly states Invoice Summary is exclusively for summary requests."""
    assert "QUESTION-ANSWERING SCOPE & NORMAL QUESTION RULES" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "It MUST NOT be used as the default format for normal questions" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "Answer ONLY the specific question asked" in DOCUMENT_REACT_SYSTEM_PROMPT
    assert "Do NOT regenerate or prepend the \"Invoice Summary\"" in DOCUMENT_REACT_SYSTEM_PROMPT


def test_normal_questions_do_not_produce_invoice_summary(db_session, doc_summary_setup):
    """Verify that specific inquiries receive concise, targeted answers without the 5-section summary structure."""
    user = doc_summary_setup["user"]
    doc = doc_summary_setup["doc"]

    class MockChatModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            # Model directly answers the vendor question
            return AIMessage(content="The vendor is Acme Supplies Ltd.")

    agent = DocumentReActAgent(db=db_session, llm=MockChatModel())
    res = agent.run(document_id=doc.id, query="What is the vendor name?", user=user)

    assert res.content == "The vendor is Acme Supplies Ltd."
    assert "Invoice Summary" not in res.content
    assert "Invoice Overview" not in res.content
    assert "Payment Details" not in res.content
    assert "Amount Breakdown" not in res.content
    assert "Items / Services" not in res.content
    assert "AP Attention" not in res.content

