"""SQLite-backed memory and schema store with vector search."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import numpy as np

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import cosine_similarity
from cosmos_q.models import MemoryNode, MemoryStatus, Schema, SchemaType


class MemoryStore:
    """Persists MemoryNode and Schema objects with cosine-similarity retrieval."""

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self.db_path = Path(self.config.db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    stability REAL NOT NULL,
                    interference_score REAL NOT NULL DEFAULT 0,
                    schema_id TEXT,
                    parent_id TEXT,
                    successor_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reconsolidation_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_memories_user_status
                    ON memories(user_id, status);
                CREATE TABLE IF NOT EXISTS schemas (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    supporting_memories TEXT NOT NULL DEFAULT '[]',
                    contradicting_memories TEXT NOT NULL DEFAULT '[]',
                    version INTEGER NOT NULL,
                    embedding TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_schemas_user ON schemas(user_id);
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    response TEXT NOT NULL,
                    retrieved_memory_ids TEXT NOT NULL DEFAULT '[]',
                    timestamp TEXT NOT NULL
                );
                """
            )

    # --- Memory CRUD ---

    def save_memory(self, memory: MemoryNode) -> MemoryNode:
        memory.updated_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memories
                (id, user_id, version, content, embedding, evidence, stability,
                 interference_score, schema_id, parent_id, successor_id, status,
                 created_at, updated_at, reconsolidation_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(memory.id),
                    str(memory.user_id),
                    memory.version,
                    memory.content,
                    json.dumps(memory.embedding),
                    json.dumps([e.model_dump() for e in memory.evidence]),
                    memory.stability,
                    memory.interference_score,
                    str(memory.schema_id) if memory.schema_id else None,
                    str(memory.parent_id) if memory.parent_id else None,
                    str(memory.successor_id) if memory.successor_id else None,
                    memory.status.value,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                    memory.reconsolidation_count,
                ),
            )
        return memory

    def get_memory(self, memory_id: UUID) -> MemoryNode | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (str(memory_id),)
            ).fetchone()
        return self._row_to_memory(row) if row else None

    def list_memories(
        self,
        user_id: UUID,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
    ) -> list[MemoryNode]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? AND status = ? ORDER BY created_at",
                    (str(user_id), status.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE user_id = ? ORDER BY created_at",
                    (str(user_id),),
                ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def list_user_ids(self) -> list[UUID]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT user_id FROM memories WHERE status = 'ACTIVE'"
            ).fetchall()
        return [UUID(row["user_id"]) for row in rows]

    def close(self) -> None:
        pass


    def search_memories(
        self,
        user_id: UUID,
        query_embedding: list[float],
        top_k: int = 50,
        status: MemoryStatus = MemoryStatus.ACTIVE,
    ) -> list[tuple[MemoryNode, float]]:
        memories = self.list_memories(user_id, status=status)
        scored = [
            (m, cosine_similarity(query_embedding, m.embedding))
            for m in memories
            if m.embedding
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def get_recent_memories(
        self, user_id: UUID, hours: int
    ) -> list[MemoryNode]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            m
            for m in self.list_memories(user_id)
            if m.created_at >= cutoff
        ]

    def get_stable_memories(self, user_id: UUID) -> list[MemoryNode]:
        return [
            m
            for m in self.list_memories(user_id)
            if m.stability >= self.config.stable_threshold
        ]

    def get_unstable_memories(self, user_id: UUID) -> list[MemoryNode]:
        return [
            m
            for m in self.list_memories(user_id)
            if m.stability < self.config.unstable_threshold
        ]

    # --- Schema CRUD ---

    def save_schema(self, schema: Schema) -> Schema:
        schema.updated_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO schemas
                (id, user_id, type, content, confidence, supporting_memories,
                 contradicting_memories, version, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(schema.id),
                    str(schema.user_id),
                    schema.type.value,
                    schema.content,
                    schema.confidence,
                    json.dumps([str(u) for u in schema.supporting_memories]),
                    json.dumps([str(u) for u in schema.contradicting_memories]),
                    schema.version,
                    json.dumps(schema.embedding),
                    schema.created_at.isoformat(),
                    schema.updated_at.isoformat(),
                ),
            )
        return schema

    def list_schemas(self, user_id: UUID) -> list[Schema]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM schemas WHERE user_id = ? ORDER BY created_at",
                (str(user_id),),
            ).fetchall()
        return [self._row_to_schema(r) for r in rows]

    def get_schema(self, schema_id: UUID) -> Schema | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM schemas WHERE id = ?", (str(schema_id),)
            ).fetchone()
        return self._row_to_schema(row) if row else None

    # --- Traces ---

    def save_trace(self, trace: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO traces
                (user_id, session_id, turn_index, query, response,
                 retrieved_memory_ids, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace["user_id"],
                    trace["session_id"],
                    trace["turn_index"],
                    trace["query"],
                    trace["response"],
                    json.dumps(trace.get("retrieved_memory_ids", [])),
                    trace["timestamp"],
                ),
            )

    def list_traces(self, user_id: UUID, session_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM traces WHERE user_id = ? AND session_id = ? ORDER BY turn_index",
                    (str(user_id), session_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM traces WHERE user_id = ? ORDER BY timestamp",
                    (str(user_id),),
                ).fetchall()
        return [dict(r) for r in rows]

    # --- Helpers ---

    def _row_to_memory(self, row: sqlite3.Row) -> MemoryNode:
        from cosmos_q.models import ContextRef

        return MemoryNode(
            id=UUID(row["id"]),
            user_id=UUID(row["user_id"]),
            version=row["version"],
            content=row["content"],
            embedding=json.loads(row["embedding"]),
            evidence=[ContextRef(**e) for e in json.loads(row["evidence"])],
            stability=row["stability"],
            interference_score=row["interference_score"],
            schema_id=UUID(row["schema_id"]) if row["schema_id"] else None,
            parent_id=UUID(row["parent_id"]) if row["parent_id"] else None,
            successor_id=UUID(row["successor_id"]) if row["successor_id"] else None,
            status=MemoryStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            reconsolidation_count=row["reconsolidation_count"],
        )

    def _row_to_schema(self, row: sqlite3.Row) -> Schema:
        return Schema(
            id=UUID(row["id"]),
            user_id=UUID(row["user_id"]),
            type=SchemaType(row["type"]),
            content=row["content"],
            confidence=row["confidence"],
            supporting_memories=[UUID(u) for u in json.loads(row["supporting_memories"])],
            contradicting_memories=[
                UUID(u) for u in json.loads(row["contradicting_memories"])
            ],
            version=row["version"],
            embedding=json.loads(row["embedding"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def cluster_embeddings(
        self, memories: list[MemoryNode], threshold: float = 0.6
    ) -> list[list[MemoryNode]]:
        """Simple greedy clustering by embedding similarity."""
        if not memories:
            return []
        clusters: list[list[MemoryNode]] = []
        used: set[UUID] = set()
        for mem in memories:
            if mem.id in used:
                continue
            cluster = [mem]
            used.add(mem.id)
            for other in memories:
                if other.id in used:
                    continue
                sim = cosine_similarity(mem.embedding, other.embedding)
                if sim >= threshold:
                    cluster.append(other)
                    used.add(other.id)
            clusters.append(cluster)
        return clusters
