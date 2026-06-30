"""Versioned Retrieval-Triggered Reconsolidation (RTR)."""

from __future__ import annotations

from uuid import uuid4

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import EmbeddingService, semantic_divergence
from cosmos_q.models import ContextRef, MemoryNode, MemoryStatus
from cosmos_q.store.memory_store import MemoryStore


class ReconsolidationEngine:
    """
    When a memory is retrieved in a new context, compare the memory's content
    with the current conversational context (query + response).  If semantic
    divergence exceeds τ_rtr a new versioned memory is created and the prior
    version is marked SUPERSEDED.  If divergence is low, stability is
    reinforced.

    RTR is called *after* the agent responds so the full query+response context
    is available.  During pure retrieval (no response yet) pass context_text=""
    and RTR will skip comparison rather than spuriously versioning.
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: EmbeddingService,
        config: CosmosConfig | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.config = config or CosmosConfig()

    def process_retrieved(
        self,
        memory: MemoryNode,
        query: str,
        context_text: str,
        session_id: str = "",
        turn_index: int = 0,
    ) -> MemoryNode:
        """
        Apply RTR to a retrieved memory.  Returns the active (possibly new) version.

        Parameters
        ----------
        memory       : the retrieved memory node
        query        : the user's query
        context_text : the full context to compare against — should be the
                       agent *response* (or query+response together).  Pass ""
                       to skip RTR for this memory (e.g. pre-response retrieval).
        """
        if not self.config.enable_rtr or not context_text:
            return memory

        mem_emb = self.embedder.embed(memory.content)
        ctx_emb = self.embedder.embed(context_text)
        delta = semantic_divergence(mem_emb, ctx_emb)

        if delta < self.config.tau_rtr:
            memory.stability = min(1.0, memory.stability + self.config.alpha_reinforce)
            memory.reconsolidation_count += 1
            return self.store.save_memory(memory)

        merged_content = self._merge(memory.content, context_text, query)
        new_memory = MemoryNode(
            id=uuid4(),
            user_id=memory.user_id,
            version=memory.version + 1,
            content=merged_content,
            embedding=self.embedder.embed(merged_content),
            evidence=list(memory.evidence)
            + [
                ContextRef(
                    session_id=session_id,
                    turn_index=turn_index,
                    snippet=context_text[:200],
                )
            ],
            stability=self.config.initial_stability,
            parent_id=memory.id,
            schema_id=memory.schema_id,
            status=MemoryStatus.ACTIVE,
            reconsolidation_count=memory.reconsolidation_count + 1,
        )
        memory.status = MemoryStatus.SUPERSEDED
        memory.successor_id = new_memory.id
        self.store.save_memory(memory)
        return self.store.save_memory(new_memory)

    def _merge(self, old_content: str, context: str, query: str) -> str:
        return (
            f"[Updated] {old_content} "
            f"(revised in context of '{query[:60]}': {context[:200]})"
        )
