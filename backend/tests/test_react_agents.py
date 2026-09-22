"""Unit and Integration Tests for ReAct Agents (GlobalReActAgent & DocumentReActAgent).

Tests:
- Global Agent:
  - Database query tool execution
  - Document RAG tool execution
  - Financial Calculator tool execution
  - Multi-hop tool sequence: Database -> Calculator
  - Multi-hop tool sequence: RAG -> Calculator
  - Max-iteration termination (5 iterations)
  - Zero Chain-of-Thought leakage in final content
- Document Agent:
  - Document RAG query
  - RAG -> Calculator multi-hop
  - Database query tool is strictly NOT registered
  - Document scoping strictly backend-controlled
"""
import uuid
import pytest
from sqlalchemy.orm import Session
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.database.session import get_db_context
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_enums import DocumentStatus
from app.models.user import User, UserRole
from app.rag.embeddings import get_embedding_service
from app.rag.global_agent import GlobalReActAgent
from app.rag.document_agent import DocumentReActAgent


class MockToolCallingChatModel(FakeMessagesListChatModel):
    """Mock Chat Model capable of simulating multi-step ReAct tool calling turns."""
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def db_session():
    with get_db_context() as session:
        yield session


@pytest.fixture
def agent_test_setup(db_session: Session):
    suffix = uuid.uuid4().hex[:8]
    manager = User(
        username=f"mgr_agent_{suffix}",
        email=f"mgr_agent_{suffix}@example.com",
        full_name="Agent Manager",
        password_hash="pwm",
        role=UserRole.FINANCE_MANAGER.value,
        is_active=True,
    )
    analyst = User(
        username=f"analyst_agent_{suffix}",
        email=f"analyst_agent_{suffix}@example.com",
        full_name="Agent Analyst",
        password_hash="pwa",
        role=UserRole.FINANCE_ANALYST.value,
        is_active=True,
    )
    db_session.add_all([manager, analyst])
    db_session.flush()

    doc = Document(
        original_filename=f"contract_{suffix}.pdf",
        stored_filename=f"cont_{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=4096,
        file_hash=f"hash_{suffix}",
        status=DocumentStatus.VALIDATED.value,
        uploaded_by=analyst.id,
    )
    db_session.add(doc)
    db_session.flush()

    chunk_text = "Standard Payment Terms: 3% early settlement discount if paid within 15 days on total 10000.00."
    embedder = get_embedding_service()
    vec = embedder.generate_embeddings([chunk_text])[0]

    chunk = DocumentChunk(
        document_id=doc.id,
        page_number=1,
        chunk_type="TERMS",
        content=chunk_text,
        embedding=vec,
        metadata_json={"chunk_index": 0, "page_number": 1},
    )
    db_session.add(chunk)
    db_session.commit()

    return {
        "manager": manager,
        "analyst": analyst,
        "doc": doc,
    }


def test_global_agent_sql_single_step(db_session, agent_test_setup):
    """Verify Global Agent handles single-step SQL query."""
    manager = agent_test_setup["manager"]
    step1 = AIMessage(
        content="",
        tool_calls=[{
            "name": "database_query_tool",
            "args": {"query": "How many documents exist?"},
            "id": "call_sql_1",
        }],
    )
    step2 = AIMessage(content="There is 1 validated document in the database.")
    mock_llm = MockToolCallingChatModel(responses=[step1, step2])
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="How many documents are there?", user=manager)
    assert result.content == "There is 1 validated document in the database."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool"] == "database_query_tool"
    assert "thought" not in result.content.lower()


def test_global_agent_rag_single_step(db_session, agent_test_setup):
    """Verify Global Agent handles single-step RAG retrieval with citations."""
    manager = agent_test_setup["manager"]
    step1 = AIMessage(
        content="",
        tool_calls=[{
            "name": "document_rag_tool",
            "args": {"query": "early settlement discount"},
            "id": "call_rag_1",
        }],
    )
    step2 = AIMessage(content="The early settlement discount is 3% within 15 days.")
    mock_llm = MockToolCallingChatModel(responses=[step1, step2])
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="What are the discount terms in our documents?", user=manager)
    assert result.content == "The early settlement discount is 3% within 15 days."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool"] == "document_rag_tool"
    assert len(result.citations) > 0


def test_global_agent_calculator_single_step(db_session, agent_test_setup):
    """Verify Global Agent handles single-step financial calculation."""
    manager = agent_test_setup["manager"]
    step1 = AIMessage(
        content="",
        tool_calls=[{
            "name": "financial_calculator_tool",
            "args": {"action": "calculate_expression", "expression": "1000 * 0.03"},
            "id": "call_calc_1",
        }],
    )
    step2 = AIMessage(content="3% of 1000 is 30.00.")
    mock_llm = MockToolCallingChatModel(responses=[step1, step2])
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="What is 3% of 1000?", user=manager)
    assert result.content == "3% of 1000 is 30.00."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool"] == "financial_calculator_tool"


def test_global_agent_sql_to_calculator_multihop(db_session, agent_test_setup):
    """Verify Global Agent coordinates multi-hop execution: SQL -> Calculator -> Answer."""
    manager = agent_test_setup["manager"]
    # Hop 1: Call SQL to get total
    hop1 = AIMessage(
        content="",
        tool_calls=[{
            "name": "database_query_tool",
            "args": {"query": "Get total amount of documents"},
            "id": "call_sql_hop1",
        }],
    )
    # Hop 2: Call Calculator using observed total
    hop2 = AIMessage(
        content="",
        tool_calls=[{
            "name": "financial_calculator_tool",
            "args": {
                "action": "calculate_discount",
                "gross_amount": "10000.00",
                "discount_percentage": "3%",
                "days_offset": 15,
            },
            "id": "call_calc_hop2",
        }],
    )
    # Final answer
    hop3 = AIMessage(content="The gross total is $10,000.00. With a 3% early discount, the payable total is $9,700.00.")
    mock_llm = MockToolCallingChatModel(responses=[hop1, hop2, hop3])
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="Find the total invoice sum and compute a 3% early discount on it.", user=manager)
    assert "9,700.00" in result.content
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["tool"] == "database_query_tool"
    assert result.tool_calls[1]["tool"] == "financial_calculator_tool"


def test_global_agent_rag_to_calculator_multihop(db_session, agent_test_setup):
    """Verify Global Agent coordinates multi-hop execution: RAG -> Calculator -> Answer."""
    manager = agent_test_setup["manager"]
    hop1 = AIMessage(
        content="",
        tool_calls=[{
            "name": "document_rag_tool",
            "args": {"query": "discount percentage and gross"},
            "id": "call_rag_hop1",
        }],
    )
    hop2 = AIMessage(
        content="",
        tool_calls=[{
            "name": "financial_calculator_tool",
            "args": {
                "action": "calculate_discount",
                "gross_amount": "10000.00",
                "discount_percentage": "3%",
                "days_offset": 15,
            },
            "id": "call_calc_hop2",
        }],
    )
    hop3 = AIMessage(content="From the contract terms, the 3% discount reduces the 10000.00 total to 9700.00.")
    mock_llm = MockToolCallingChatModel(responses=[hop1, hop2, hop3])
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="What is the discounted total based on the contract terms?", user=manager)
    assert "9700.00" in result.content
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["tool"] == "document_rag_tool"
    assert result.tool_calls[1]["tool"] == "financial_calculator_tool"
    assert len(result.citations) > 0


def test_global_agent_max_iterations_safeguard(db_session, agent_test_setup):
    """Verify Global Agent cleanly terminates when exceeding MAX_ITERATIONS (5)."""
    manager = agent_test_setup["manager"]
    looping_responses = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "financial_calculator_tool",
                "args": {"action": "calculate_expression", "expression": f"1 + {i}"},
                "id": f"call_loop_{i}",
            }],
        )
        for i in range(10)
    ]
    mock_llm = MockToolCallingChatModel(responses=looping_responses)
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="Loop indefinitely", user=manager)
    assert "maximum iteration limit" in result.content.lower()
    assert len(result.tool_calls) == 5  # capped at MAX_ITERATIONS


def test_global_agent_no_chain_of_thought_leakage(db_session, agent_test_setup):
    """Verify internal reasoning does not leak into the final user-facing content."""
    manager = agent_test_setup["manager"]
    step = AIMessage(
        content="Final Answer: The requested financial summary is ready.",
    )
    mock_llm = MockToolCallingChatModel(responses=[step])
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="Summarize financial records", user=manager)
    assert "Final Answer: The requested financial summary is ready." in result.content
    assert "we need to" not in result.content.lower()
    assert "i should analyze" not in result.content.lower()


def test_document_agent_tools_registration(db_session, agent_test_setup):
    """Verify DocumentReActAgent registers ONLY RAG and Calculator, strictly no Database tool."""
    analyst = agent_test_setup["analyst"]
    doc = agent_test_setup["doc"]
    
    # We can inspect tool calls to ensure DB tool cannot be found/called
    step1 = AIMessage(
        content="",
        tool_calls=[{
            "name": "database_query_tool",
            "args": {"query": "SELECT * FROM users;"},
            "id": "bad_db_call",
        }],
    )
    step2 = AIMessage(content="Database tool is not available.")
    mock_llm = MockToolCallingChatModel(responses=[step1, step2])
    agent = DocumentReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(document_id=doc.id, query="Query database", user=analyst)
    # The tool call for database_query_tool should return error "Unknown tool 'database_query_tool'"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].get("status") == "error"


def test_document_agent_rag_to_calculator(db_session, agent_test_setup):
    """Verify DocumentReActAgent coordinates RAG -> Calculator multi-step flow."""
    analyst = agent_test_setup["analyst"]
    doc = agent_test_setup["doc"]

    hop1 = AIMessage(
        content="",
        tool_calls=[{
            "name": "document_rag_tool",
            "args": {"query": "payment discount terms"},
            "id": "doc_call_1",
        }],
    )
    hop2 = AIMessage(
        content="",
        tool_calls=[{
            "name": "financial_calculator_tool",
            "args": {
                "action": "calculate_discount",
                "gross_amount": "10000.00",
                "discount_percentage": "3%",
                "days_offset": 15,
            },
            "id": "doc_call_2",
        }],
    )
    hop3 = AIMessage(content="This document specifies a 3% early payment discount, leaving $9,700.00 payable.")
    mock_llm = MockToolCallingChatModel(responses=[hop1, hop2, hop3])
    agent = DocumentReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(
        document_id=doc.id,
        query="What is the discounted total payable according to this document?",
        user=analyst,
    )
    assert "9,700.00" in result.content
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["tool"] == "document_rag_tool"
    assert result.tool_calls[1]["tool"] == "financial_calculator_tool"
    assert len(result.citations) > 0
    assert result.citations[0]["document_id"] == doc.id


def test_strict_max_5_tool_steps_and_no_sixth_execution(db_session, agent_test_setup):
    """TASK 3: Verify strict maximum 5 tool executions limit in GlobalReActAgent.

    Even if the model emits parallel tool calls across iterations (e.g. 3 in step 1, 3 in step 2),
    exactly 5 tool executions are performed, a 6th tool is NEVER executed, and the agent loop exits.
    """
    manager = agent_test_setup["manager"]

    # Step 1: 3 tool calls
    step1 = AIMessage(
        content="",
        tool_calls=[
            {"name": "financial_calculator_tool", "args": {"action": "calculate_expression", "expression": f"{i} + 1"}, "id": f"tc_s1_{i}"}
            for i in range(3)
        ],
    )
    # Step 2: 3 tool calls (total attempted = 6)
    step2 = AIMessage(
        content="",
        tool_calls=[
            {"name": "financial_calculator_tool", "args": {"action": "calculate_expression", "expression": f"{i} + 10"}, "id": f"tc_s2_{i}"}
            for i in range(3)
        ],
    )
    # Synthesis response
    synthesis = AIMessage(content="Final synthesis completed without invoking tools.")

    mock_llm = MockToolCallingChatModel(responses=[step1, step2, synthesis])
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="Perform 6 calculations", user=manager)
    # Must have stopped at exactly 5 tool steps
    assert len(result.tool_calls) == 5
    # Synthesis produces final answer without tools
    assert "synthesis completed" in result.content


def test_synthesis_does_not_invoke_tools_or_reenter_loop(db_session, agent_test_setup):
    """TASK 3: Verify synthesis cannot invoke tools, produce tool calls, or recursively re-enter.

    Synthesis uses raw `llm.invoke` without bound tools. Even if the LLM output in synthesis attempts
    to specify tool_calls, they are never executed because the agent loop has already terminated.
    """
    manager = agent_test_setup["manager"]

    # 5 tool calls across 5 single steps
    responses = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "financial_calculator_tool",
                "args": {"action": "calculate_expression", "expression": f"2 * {i}"},
                "id": f"step_call_{i}",
            }],
        )
        for i in range(5)
    ]
    # Synthesis response that maliciously includes a tool_call attempt
    responses.append(
        AIMessage(
            content="Final bounded synthesis answer.",
            tool_calls=[{
                "name": "financial_calculator_tool",
                "args": {"action": "calculate_expression", "expression": "999 + 999"},
                "id": "unwanted_6th_tool_call",
            }],
        )
    )

    mock_llm = MockToolCallingChatModel(responses=responses)
    agent = GlobalReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(query="Test synthesis isolation", user=manager)
    # Exactly 5 tool executions were recorded; the 6th in synthesis was completely ignored
    assert len(result.tool_calls) == 5
    assert result.content == "Final bounded synthesis answer."


def test_document_agent_obeys_strict_max_5_tool_steps(db_session, agent_test_setup):
    """TASK 3: Verify DocumentReActAgent strictly obeys the MAX_ITERATIONS = 5 limit."""
    analyst = agent_test_setup["analyst"]
    doc = agent_test_setup["doc"]

    responses = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "financial_calculator_tool",
                "args": {"action": "calculate_expression", "expression": f"10 + {i}"},
                "id": f"doc_step_{i}",
            }],
        )
        for i in range(8)
    ]
    mock_llm = MockToolCallingChatModel(responses=responses)
    agent = DocumentReActAgent(db=db_session, llm=mock_llm)

    result = agent.run(document_id=doc.id, query="Loop document agent", user=analyst)
    assert len(result.tool_calls) == 5
    assert "maximum iteration limit" in result.content.lower()

