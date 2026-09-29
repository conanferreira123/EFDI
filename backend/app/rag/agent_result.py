"""Domain Result Model for ReAct Agents.

Decouples agent execution outputs from HTTP presentation schemas.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    """Domain-level output returned by ReAct agents to service/router layers."""
    content: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    relational_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    calculation_provenance: List[Dict[str, Any]] = Field(default_factory=list)
    execution_time_ms: float = 0.0
