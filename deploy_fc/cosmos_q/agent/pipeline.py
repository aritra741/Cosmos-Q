"""Memory update pipeline: trace → episodic write → async maintenance."""

from __future__ import annotations

from uuid import UUID

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import EmbeddingService
from cosmos_q.mechanisms.asc import ConsolidationEngine
from cosmos_q.mechanisms.episodic_buffer import EpisodicBuffer
from cosmos_q.mechanisms.iaaf import ForgettingEngine
from cosmos_q.models import TraceRecord
from cosmos_q.store.memory_store import MemoryStore


class MemoryUpdatePipeline:
    """Processes traces into new memories and runs async maintenance."""

    def __init__(
        self,
        store: MemoryStore,
        embedder: EmbeddingService,
        config: CosmosConfig | None = None,
    ):
        self.config = config or CosmosConfig()
        self.buffer = EpisodicBuffer(store, embedder, self.config)
        self.forgetting = ForgettingEngine(store, embedder, self.config)
        self.consolidation = ConsolidationEngine(store, embedder, self.config)

    def process_trace(self, trace: TraceRecord) -> None:
        """Write episodic memory from a completed agent turn."""
        self.buffer.ingest_trace(trace)

    def run_maintenance(self, user_id: UUID) -> dict:
        """
        Run IAAF forgetting and ASC consolidation.
        Should be called between sessions (or explicitly by the caller after
        a session ends).  Not called automatically inside chat() to keep
        latency predictable; callers that want automatic maintenance should
        call run_maintenance() after each session.
        """
        archived = self.forgetting.run_forgetting(user_id)
        schemas = self.consolidation.run_consolidation(user_id)
        return {
            "archived_count": len(archived),
            "archived_ids": [str(i) for i in archived],
            "schemas_created_or_updated": len(schemas),
            "iaaf_enabled": self.config.enable_iaaf,
            "asc_enabled": self.config.enable_asc,
        }
