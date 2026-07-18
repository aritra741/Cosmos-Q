"""Data models for COSMOS-Q memory nodes and schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CONSOLIDATED = "CONSOLIDATED"
    ARCHIVED = "ARCHIVED"


class SchemaType(str, Enum):
    PREFERENCE = "PREFERENCE"
    GOAL = "GOAL"
    FACT = "FACT"
    PROCEDURE = "PROCEDURE"
    BEHAVIOR = "BEHAVIOR"


class ContextRef(BaseModel):
    """Reference to source context that produced a memory."""

    session_id: str | None = None
    turn_index: int | None = None
    snippet: str = ""


class MemoryNode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    version: int = 1
    content: str
    embedding: list[float] = Field(default_factory=list)
    evidence: list[ContextRef] = Field(default_factory=list)
    stability: float = 0.5
    interference_score: float = 0.0
    schema_id: UUID | None = None
    parent_id: UUID | None = None
    successor_id: UUID | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    reconsolidation_count: int = 0

    def token_cost(self) -> int:
        """Rough token estimate: ~4 chars per token."""
        return max(1, len(self.content) // 4)


class Schema(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    type: SchemaType = SchemaType.FACT
    content: str
    confidence: float = 0.5
    supporting_memories: list[UUID] = Field(default_factory=list)
    contradicting_memories: list[UUID] = Field(default_factory=list)
    version: int = 1
    embedding: list[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentState(BaseModel):
    """Lightweight agent state passed into utility scoring."""

    session_id: str = ""
    turn_index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceRecord(BaseModel):
    """One agent turn for the memory update pipeline."""

    user_id: UUID
    session_id: str
    turn_index: int
    query: str
    response: str
    retrieved_memory_ids: list[UUID] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utcnow)


class MemoryBrief(BaseModel):
    """Packed context passed to the Qwen agent."""

    memories: list[MemoryNode] = Field(default_factory=list)
    schemas: list[Schema] = Field(default_factory=list)
    text: str = ""
    total_tokens: int = 0
