"""Interference-Aware Adaptive Forgetting (IAAF)."""

from __future__ import annotations

from uuid import UUID

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import EmbeddingService, cosine_similarity, estimate_contradiction
from cosmos_q.models import MemoryNode, MemoryStatus
from cosmos_q.store.memory_store import MemoryStore


class ForgettingEngine:
    """
    Compute interference I(mi) over nearest neighbors and archive memories
    where F(mi) = I(mi) / (1 + S(mi)) > τ_forget.

    Interference formula (paper §2.5):
        I(mi) = Σ_{mj∈N(mi)} Sim(mi,mj) · Contradict(mi,mj) · 1/(1+|ti−tj|_hours)
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

    def update_interference_scores(self, user_id: UUID) -> list[MemoryNode]:
        """Recompute interference for all active memories of a user."""
        memories = self.store.list_memories(user_id)
        for mem in memories:
            mem.interference_score = self._compute_interference(mem, memories)
            self.store.save_memory(mem)
        return memories

    def run_forgetting(self, user_id: UUID) -> list[UUID]:
        """
        Recompute interference scores, then archive memories exceeding τ_forget.
        Returns the list of archived memory IDs.
        Returns an empty list when IAAF is disabled (not indistinguishable from
        no memories needing archival — callers that need to distinguish should
        check config.enable_iaaf).
        """
        if not self.config.enable_iaaf:
            return []

        archived: list[UUID] = []
        memories = self.update_interference_scores(user_id)
        for mem in memories:
            f_score = mem.interference_score / (1.0 + mem.stability)
            if f_score > self.config.tau_forget:
                mem.status = MemoryStatus.ARCHIVED
                self.store.save_memory(mem)
                archived.append(mem.id)
        return archived

    def _compute_interference(
        self, target: MemoryNode, all_memories: list[MemoryNode]
    ) -> float:
        if not target.embedding:
            return 0.0
        neighbors = self._nearest_neighbors(target, all_memories)
        total = 0.0
        for other in neighbors:
            sim = cosine_similarity(target.embedding, other.embedding)
            # Pass the shared embedder so contradiction uses the same model
            contradict = estimate_contradiction(
                target.content, other.content, embedder=self.embedder
            )
            dt_hours = abs(
                (target.created_at - other.created_at).total_seconds()
            ) / 3600
            # Temporal proximity weight: neighbors active in same time window
            # interfere more; divide by neighbor_k to keep I in [0,1] naturally
            total += sim * contradict * (1.0 / (1.0 + dt_hours))
        # Normalise by neighbor count so I stays in [0,1]
        return min(1.0, total / max(1, self.config.neighbor_k))

    def _nearest_neighbors(
        self, target: MemoryNode, all_memories: list[MemoryNode]
    ) -> list[MemoryNode]:
        scored = [
            (m, cosine_similarity(target.embedding, m.embedding))
            for m in all_memories
            if m.id != target.id and m.embedding
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, _ in scored[: self.config.neighbor_k]]
