"""Memory retrieval baselines for evaluation."""

from __future__ import annotations

from uuid import UUID

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import EmbeddingService
from cosmos_q.memory_layer import CosmosMemoryLayer
from cosmos_q.models import MemoryBrief
from cosmos_q.store.memory_store import MemoryStore


class BaselineRetriever:
    """Implements the five standard baselines from the paper."""

    def __init__(
        self,
        store: MemoryStore,
        embedder: EmbeddingService,
        config: CosmosConfig | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.config = config or CosmosConfig()

    def no_memory(self, query: str) -> MemoryBrief:
        return MemoryBrief(text="", memories=[], total_tokens=0)

    def full_transcript(
        self, user_id: UUID, session_id: str, query: str
    ) -> MemoryBrief:
        traces = self.store.list_traces(user_id, session_id)
        parts = [f"Q: {t['query']}\nA: {t['response']}" for t in traces]
        text = "\n\n".join(parts)
        tokens = max(0, len(text) // 4)
        if tokens > self.config.token_budget:
            # Truncate to budget
            text = text[: self.config.token_budget * 4]
            tokens = self.config.token_budget
        return MemoryBrief(text=text, total_tokens=tokens)

    def rolling_summary(
        self, user_id: UUID, query: str
    ) -> MemoryBrief:
        memories = self.store.list_memories(user_id)
        if not memories:
            return MemoryBrief()
        summary = "Summary: " + "; ".join(m.content[:60] for m in memories[-10:])
        return MemoryBrief(text=summary, total_tokens=max(1, len(summary) // 4))

    def naive_rag(self, user_id: UUID, query: str, k: int = 10) -> MemoryBrief:
        emb = self.embedder.embed(query)
        results = self.store.search_memories(user_id, emb, top_k=k)
        memories = [m for m, _ in results]
        text = "\n".join(f"- {m.content}" for m in memories)
        return MemoryBrief(
            memories=memories,
            text=text,
            total_tokens=sum(m.token_cost() for m in memories),
        )

    def recency_retrieval(
        self, user_id: UUID, query: str, k: int = 10
    ) -> MemoryBrief:
        memories = self.store.list_memories(user_id)
        memories.sort(key=lambda m: m.created_at, reverse=True)
        selected = memories[:k]
        text = "\n".join(f"- {m.content}" for m in selected)
        return MemoryBrief(
            memories=selected,
            text=text,
            total_tokens=sum(m.token_cost() for m in selected),
        )


ABLATION_VARIANTS = {
    "full": "full",
    "no_rtr": "no_rtr",
    "no_asc": "no_asc",
    "no_iaaf": "no_iaaf",
    "no_uacp": "no_uacp",
}


def make_cosmos_layer(variant: str, db_path: str = ":memory:") -> CosmosMemoryLayer:
    if variant not in ABLATION_VARIANTS:
        raise ValueError(
            f"Unknown ablation variant '{variant}'. Valid: {list(ABLATION_VARIANTS)}"
        )
    config = CosmosConfig.ablation(ABLATION_VARIANTS[variant])
    config.db_path = db_path
    return CosmosMemoryLayer(config)
