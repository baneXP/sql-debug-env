"""
models.py — Typed Pydantic models for sql-debug-env.
Covers Observation, Action, StepResult, and StateResponse.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Observation ────────────────────────────────────────────────────────────────

class SqlObservation(BaseModel):
    """Observation returned by reset() and step()."""
    query_id: str = Field(..., description="Unique ID for this SQL scenario")
    task_name: str = Field(..., description="classify_issue | fix_query | full_review")
    task_description: str = Field(..., description="Instructions for the agent")
    sql_query: str = Field(..., description="SQL query under review")
    schema_context: str = Field(..., description="Relevant table schema definitions")
    step: int = Field(..., description="Current step number (1-indexed)")
    max_steps: int = Field(..., description="Maximum steps allowed for this episode")
    feedback: Optional[str] = Field(None, description="Feedback from previous step; null on step 1")


# ── Action ─────────────────────────────────────────────────────────────────────

class SqlAction(BaseModel):
    """Action submitted by the agent."""
    content: str = Field(..., description=(
        "Agent's text response. "
        "For classify_issue: include the issue label. "
        "For fix_query: include the rewritten SQL. "
        "For full_review: include issue list, fixed query, and explanations."
    ))


# ── Step Result ────────────────────────────────────────────────────────────────

class StepResult(BaseModel):
    """Result returned by env.step()."""
    observation: SqlObservation
    reward: float = Field(..., ge=0.0, le=1.0)
    done: bool
    info: Dict[str, Any] = Field(default_factory=dict)


# ── Reset Result ───────────────────────────────────────────────────────────────

class ResetResult(BaseModel):
    """Result returned by env.reset()."""
    observation: SqlObservation
    done: bool = False
    reward: float = 0.0
    info: Dict[str, Any] = Field(default_factory=dict)


# ── State Response ─────────────────────────────────────────────────────────────

class StateResponse(BaseModel):
    """Current environment state (returned by /state endpoint)."""
    task_name: str
    query_id: str
    step: int
    max_steps: int
    done: bool
    best_reward: float
    session_id: str
