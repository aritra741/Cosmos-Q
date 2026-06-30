"""Asynchronous Schema Consolidation (ASC)."""

from __future__ import annotations

from uuid import UUID

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import EmbeddingService, cosine_similarity, estimate_contradiction
from cosmos_q.models import MemoryNode, MemoryStatus, Schema, SchemaType
from cosmos_q.store.memory_store import MemoryStore


class ConsolidationEngine:
    """
    Between sessions, cluster episodic memories and abstract them into
    higher-level schemas (paper §2.4).

    - Replay batch = recent ∪ stable ∪ unstable ∪ mid-stability (all ACTIVE).
    - For each cluster find nearest schema; refine on consistency, reduce
      confidence on contradiction, split when confidence < τ_split.
    - Both create and update paths mark memories CONSOLIDATED consistently.
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

    def run_consolidation(self, user_id: UUID) -> list[Schema]:
        if not self.config.enable_asc:
            return []

        replay = self._build_replay_batch(user_id)
        if not replay:
            return []

        clusters = self.store.cluster_embeddings(
            replay, threshold=self.config.asc_cluster_threshold
        )
        schemas = self.store.list_schemas(user_id)
        results: list[Schema] = []

        for cluster in clusters:
            schema = self._process_cluster(user_id, cluster, schemas)
            if schema:
                results.append(schema)
                # Make the new/updated schema visible to subsequent clusters
                if schema not in schemas:
                    schemas.append(schema)

        return results

    def _build_replay_batch(self, user_id: UUID) -> list[MemoryNode]:
        """All ACTIVE memories — covers recent, stable, unstable, and mid-stability."""
        return self.store.list_memories(user_id)  # status=ACTIVE by default

    def _process_cluster(
        self,
        user_id: UUID,
        cluster: list[MemoryNode],
        existing_schemas: list[Schema],
    ) -> Schema | None:
        if not cluster:
            return None

        cluster_text = " | ".join(m.content for m in cluster)
        cluster_embedding = self.embedder.embed(cluster_text)

        best_schema, best_sim = self._find_nearest_schema(
            cluster_embedding, existing_schemas
        )

        if best_schema and best_sim > 0.5:
            return self._update_schema(best_schema, cluster, cluster_embedding)

        return self._create_schema(user_id, cluster, cluster_embedding)

    def _find_nearest_schema(
        self, embedding: list[float], schemas: list[Schema]
    ) -> tuple[Schema | None, float]:
        best: Schema | None = None
        best_sim = 0.0
        for schema in schemas:
            if not schema.embedding:
                continue
            sim = cosine_similarity(embedding, schema.embedding)
            if sim > best_sim:
                best_sim = sim
                best = schema
        return best, best_sim

    def _update_schema(
        self,
        schema: Schema,
        cluster: list[MemoryNode],
        cluster_embedding: list[float],
    ) -> Schema:
        contradicts = any(
            estimate_contradiction(
                schema.content, m.content, embedder=self.embedder
            ) > 0.4
            for m in cluster
        )

        if contradicts:
            schema.confidence -= self.config.alpha_contradict
            # Deduplicated extend
            existing_contra = set(schema.contradicting_memories)
            schema.contradicting_memories.extend(
                m.id for m in cluster if m.id not in existing_contra
            )
            if schema.confidence < self.config.tau_split:
                return self._split_schema(schema, cluster)
        else:
            schema.confidence = min(1.0, schema.confidence + 0.05)
            existing_support = set(schema.supporting_memories)
            schema.supporting_memories.extend(
                m.id for m in cluster if m.id not in existing_support
            )
            schema.content = self._refine_content(schema.content, cluster)
            schema.version += 1

        schema.embedding = cluster_embedding
        saved = self.store.save_schema(schema)

        # Mark consolidated memories consistently (same as _create_schema)
        for mem in cluster:
            mem.schema_id = saved.id
            mem.status = MemoryStatus.CONSOLIDATED
            self.store.save_memory(mem)

        return saved

    def _create_schema(
        self,
        user_id: UUID,
        cluster: list[MemoryNode],
        embedding: list[float],
    ) -> Schema:
        schema_type = self._infer_type(cluster)
        schema = Schema(
            user_id=user_id,
            type=schema_type,
            content=self._summarize_cluster(cluster),
            confidence=0.6,
            supporting_memories=[m.id for m in cluster],
            embedding=embedding,
        )
        saved = self.store.save_schema(schema)
        for mem in cluster:
            mem.schema_id = saved.id
            mem.status = MemoryStatus.CONSOLIDATED
            self.store.save_memory(mem)
        return saved

    def _split_schema(
        self, schema: Schema, cluster: list[MemoryNode]
    ) -> Schema:
        """
        Split a low-confidence schema.
        - Parent schema is archived (no longer primary).
        - Sub-schemas are created from halves of the cluster.
        - Returns the first (largest) sub-schema.
        """
        schema.status = "ARCHIVED"  # type: ignore[assignment]  # string sentinel
        schema.confidence = 0.0
        self.store.save_schema(schema)

        mid = max(1, len(cluster) // 2)
        sub_clusters = [cluster[:mid], cluster[mid:]] if len(cluster) > 1 else [cluster]
        first: Schema | None = None
        for sub in sub_clusters:
            if not sub:
                continue
            sub_emb = self.embedder.embed(" | ".join(m.content for m in sub))
            new_schema = self._create_schema(schema.user_id, sub, sub_emb)
            if first is None:
                first = new_schema
        return first or schema

    def _infer_type(self, cluster: list[MemoryNode]) -> SchemaType:
        text = " ".join(m.content.lower() for m in cluster)
        if any(w in text for w in ("prefer", "like", "want")):
            return SchemaType.PREFERENCE
        if any(w in text for w in ("goal", "plan", "achieve")):
            return SchemaType.GOAL
        if any(w in text for w in ("step", "procedure", "how to")):
            return SchemaType.PROCEDURE
        if any(w in text for w in ("usually", "always", "tends to")):
            return SchemaType.BEHAVIOR
        return SchemaType.FACT

    def _summarize_cluster(self, cluster: list[MemoryNode]) -> str:
        """Summarise all cluster members, not just the first."""
        snippets = "; ".join(m.content[:80] for m in cluster[:5])
        suffix = f" (+{len(cluster) - 5} more)" if len(cluster) > 5 else ""
        return f"Pattern ({len(cluster)} memories): {snippets}{suffix}"

    def _refine_content(self, existing: str, cluster: list[MemoryNode]) -> str:
        latest = "; ".join(m.content[:60] for m in cluster[-3:])
        return f"{existing} | updated: {latest}"
