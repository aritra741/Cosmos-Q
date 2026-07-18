"""Utility-Aware Context Packing (UACP)."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import cosine_similarity
from cosmos_q.models import AgentState, MemoryBrief, MemoryNode, MemoryStatus, Schema
from cosmos_q.store.memory_store import MemoryStore


class ContextPacker:
    """
    Select memories under a token budget B using utility-per-token ranking.

    U(mi|q,s) = R(mi,q)·S(mi)·(1-I(mi)) + B_schema(mi) + B_recency(mi) - λ·T(mi)
    ρ(mi) = U(mi|q,s) / T(mi)

    Greedy selection by ρ descending until Σ T(mi) ≤ B.
    Schema text is also counted against the budget.
    """

    def __init__(
        self,
        store: MemoryStore,
        config: CosmosConfig | None = None,
    ):
        self.store = store
        self.config = config or CosmosConfig()

    def pack(
        self,
        candidates: list[MemoryNode],
        query_embedding: list[float],
        agent_state: AgentState,
        schemas: list[Schema] | None = None,
    ) -> MemoryBrief:
        schemas = schemas or []
        # schema_id → schema for O(1) bonus lookup
        schema_map = {s.id: s for s in schemas}

        if not self.config.enable_uacp:
            return self._naive_top_k(candidates, schemas)

        # Score and rank
        scored: list[tuple[MemoryNode, float]] = []
        for mem in candidates:
            utility = self._utility(mem, query_embedding, schema_map)
            tokens = mem.token_cost()
            rho = utility / tokens if tokens > 0 else 0.0
            scored.append((mem, rho))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Reserve tokens for the schema section header + entries
        schema_tokens = self._schema_token_cost(schemas)
        remaining = self.config.token_budget - schema_tokens

        selected: list[MemoryNode] = []
        total_tokens = schema_tokens
        for mem, _ in scored:
            cost = mem.token_cost()
            if remaining >= cost:
                selected.append(mem)
                total_tokens += cost
                remaining -= cost

        # Clamp schemas to what fits; use same list for text and metadata
        packed_schemas = self._clamp_schemas(schemas, self.config.token_budget)
        text = self._compose_brief(selected, packed_schemas)
        return MemoryBrief(
            memories=selected,
            schemas=packed_schemas,
            text=text,
            total_tokens=total_tokens,
        )

    def _utility(
        self,
        mem: MemoryNode,
        query_embedding: list[float],
        schema_map: dict,
    ) -> float:
        relevance = cosine_similarity(query_embedding, mem.embedding)
        stability = mem.stability
        interference = mem.interference_score
        schema_bonus = self.config.schema_bonus if mem.schema_id in schema_map else 0.0
        recency_bonus = self._recency_bonus(mem)
        token_penalty = self.config.lambda_token_cost * mem.token_cost()
        return (
            relevance * stability * (1.0 - interference)
            + schema_bonus
            + recency_bonus
            - token_penalty
        )

    def _recency_bonus(self, mem: MemoryNode) -> float:
        # Use updated_at so refreshed/reconsolidated memories score better
        reference = max(mem.updated_at, mem.created_at)
        age_hours = (
            datetime.now(timezone.utc) - reference
        ).total_seconds() / 3600
        return self.config.recency_bonus_scale * math.exp(-age_hours / 168)

    def _schema_token_cost(self, schemas: list[Schema]) -> int:
        if not schemas:
            return 0
        total = len("## Known Patterns\n")
        for s in schemas:
            line = f"- [{s.type.value}] {s.content} (conf={s.confidence:.2f})\n"
            total += max(1, len(line) // 4)
        return total

    def _clamp_schemas(self, schemas: list[Schema], budget: int) -> list[Schema]:
        selected: list[Schema] = []
        tokens = len("## Known Patterns\n")
        for s in schemas:
            cost = max(1, len(f"- [{s.type.value}] {s.content} (conf={s.confidence:.2f})\n") // 4)
            if tokens + cost > budget:
                break
            selected.append(s)
            tokens += cost
        return selected

    def _naive_top_k(
        self, candidates: list[MemoryNode], schemas: list[Schema]
    ) -> MemoryBrief:
        """Ablation fallback: pack by relevance insertion order up to budget."""
        schema_tokens = self._schema_token_cost(schemas)
        remaining = self.config.token_budget - schema_tokens
        selected: list[MemoryNode] = []
        total = schema_tokens
        for mem in candidates:
            cost = mem.token_cost()
            if remaining >= cost:
                selected.append(mem)
                total += cost
                remaining -= cost
        packed_schemas = self._clamp_schemas(schemas, self.config.token_budget)
        return MemoryBrief(
            memories=selected,
            schemas=packed_schemas,
            text=self._compose_brief(selected, packed_schemas),
            total_tokens=total,
        )

    def _compose_brief(
        self, memories: list[MemoryNode], schemas: list[Schema]
    ) -> str:
        # assembly-defect fix, probe re-run: when RTR is on, strip any
        # SUPERSEDED/ARCHIVED version content spans from the assembled string.
        if self.config.enable_rtr and memories:
            memories = self._drop_superseded_spans(memories)

        parts: list[str] = []
        if schemas:
            parts.append("## Known Patterns")
            for s in schemas:
                parts.append(
                    f"- [{s.type.value}] {s.content} (conf={s.confidence:.2f})"
                )
        if memories:
            parts.append("## Relevant Memories")
            for m in memories:
                parts.append(f"- {m.content}")
        return "\n".join(parts)

    def _drop_superseded_spans(self, memories: list[MemoryNode]) -> list[MemoryNode]:
        """
        Smallest reliable rule: collect SUPERSEDED + ARCHIVED contents for the
        user; remove those exact spans from ACTIVE packed contents; drop a
        memory if nothing remains. Baseline (enable_rtr=False) never calls this.
        """
        if not memories:
            return memories
        user_id: UUID = memories[0].user_id
        blocked: list[str] = []
        for status in (MemoryStatus.SUPERSEDED, MemoryStatus.ARCHIVED):
            for m in self.store.list_memories(user_id, status=status):
                text = (m.content or "").strip()
                if text:
                    blocked.append(text)
        if not blocked:
            return memories

        # Longer spans first so nested replacements are stable.
        blocked.sort(key=len, reverse=True)
        cleaned: list[MemoryNode] = []
        for mem in memories:
            content = mem.content or ""
            for span in blocked:
                if span and span in content:
                    content = content.replace(span, "")
            content = " ".join(content.split()).strip()
            if not content:
                continue
            if content != mem.content:
                cleaned.append(mem.model_copy(update={"content": content}))
            else:
                cleaned.append(mem)
        return cleaned
