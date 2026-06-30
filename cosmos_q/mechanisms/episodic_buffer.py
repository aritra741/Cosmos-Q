"""Episodic buffer: ingests new memories after each session turn."""

from __future__ import annotations

from uuid import UUID

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import EmbeddingService
from cosmos_q.models import ContextRef, MemoryNode, MemoryStatus, TraceRecord
from cosmos_q.store.memory_store import MemoryStore


class EpisodicBuffer:
    """Writes new episodic memories from agent traces."""

    def __init__(
        self,
        store: MemoryStore,
        embedder: EmbeddingService,
        config: CosmosConfig | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.config = config or CosmosConfig()

    def ingest_trace(self, trace: TraceRecord) -> MemoryNode | None:
        """Extract and persist a memory from a conversation turn."""
        content = self._extract_memory_content(trace)
        if not content:
            return None

        embedding = self.embedder.embed(content)
        memory = MemoryNode(
            user_id=trace.user_id,
            content=content,
            embedding=embedding,
            evidence=[
                ContextRef(
                    session_id=trace.session_id,
                    turn_index=trace.turn_index,
                    snippet=trace.query[:200],
                )
            ],
            stability=self.config.initial_stability,
            status=MemoryStatus.ACTIVE,
        )
        return self.store.save_memory(memory)

    def ingest_explicit(
        self,
        user_id: UUID,
        content: str,
        session_id: str = "",
        turn_index: int = 0,
    ) -> MemoryNode:
        """Directly store a memory (e.g. from benchmark fixtures)."""
        embedding = self.embedder.embed(content)
        memory = MemoryNode(
            user_id=user_id,
            content=content,
            embedding=embedding,
            evidence=[ContextRef(session_id=session_id, turn_index=turn_index)],
            stability=self.config.initial_stability,
            status=MemoryStatus.ACTIVE,
        )
        return self.store.save_memory(memory)

    def _extract_memory_content(self, trace: TraceRecord) -> str:
        """Derive a storable memory from query + response."""
        q = trace.query.strip()
        r = trace.response.strip()
        if not q:
            return ""
        # Prefer user-stated facts/preferences as memory content
        if any(
            kw in q.lower()
            for kw in ("prefer", "like", "want", "remember", "my name", "i am", "i'm")
        ):
            return f"User said: {q}"
        if len(r) > 20:
            return f"Regarding '{q[:80]}': {r[:300]}"
        return f"User asked: {q}"
