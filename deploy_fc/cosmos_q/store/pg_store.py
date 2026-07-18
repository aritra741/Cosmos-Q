"""ApsaraDB RDS for PostgreSQL + pgvector memory store.

Drop-in replacement for MemoryStore (SQLite) when `pg_dsn` is configured.

Storage layout:
  - `memories`  table with a pgvector `embedding` column (ivfflat index).
  - `schemas`   table with a pgvector `embedding` column.
  - `traces`    table for agent turn logs.

Vector similarity is computed via the pgvector `<=>` operator (cosine distance)
so the DB handles ANN search natively, avoiding full Python-side scanning.

Requires: psycopg2-binary, pgvector (postgres extension).
Install:   pip install "cosmos-q[pg]"  (or pip install psycopg2-binary pgvector)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from cosmos_q.config import CosmosConfig
from cosmos_q.models import MemoryNode, MemoryStatus, Schema, SchemaType

logger = logging.getLogger(__name__)


def _require_psycopg2():
    try:
        import psycopg2
        import psycopg2.extras
        return psycopg2
    except ImportError as exc:
        raise ImportError(
            "psycopg2-binary is required for the PostgreSQL store. "
            "Install it with: pip install psycopg2-binary pgvector"
        ) from exc


class PgMemoryStore:
    """
    ApsaraDB RDS for PostgreSQL + pgvector memory and schema store.

    Key advantages over SQLite:
      - Native ANN search via ivfflat index on the embedding column.
      - Hybrid retrieval: combine vector similarity with SQL predicates.
      - Fully managed, Alibaba Cloud-native deployment.
      - pgvector `<=>` cosine distance avoids Python-side scoring over
        the full memory set.
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        if not self.config.pg_dsn:
            raise ValueError(
                "COSMOS_PG_DSN must be set to use the PostgreSQL store. "
                "Example: postgresql://user:pass@host:5432/cosmos_q"
            )
        self._psycopg2 = _require_psycopg2()
        self._conn = None
        self._init_schema()

    def _connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._psycopg2.connect(
                self.config.pg_dsn,
                cursor_factory=self._psycopg2.extras.RealDictCursor,
            )
            self._conn.autocommit = False
        return self._conn

    def _init_schema(self) -> None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            dim = self.config.embedding_dim
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS memories (
                    id            UUID PRIMARY KEY,
                    user_id       UUID NOT NULL,
                    version       INTEGER NOT NULL,
                    content       TEXT NOT NULL,
                    embedding     vector({dim}),
                    evidence      JSONB NOT NULL DEFAULT '[]',
                    stability     REAL NOT NULL DEFAULT 0.5,
                    interference_score REAL NOT NULL DEFAULT 0.0,
                    schema_id     UUID,
                    parent_id     UUID,
                    successor_id  UUID,
                    status        TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    reconsolidation_count INTEGER NOT NULL DEFAULT 0
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_user_status
                    ON memories(user_id, status);
            """)
            # ivfflat index for ANN vector search (cosine distance)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_memories_embedding
                    ON memories USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100);
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS schemas (
                    id                     UUID PRIMARY KEY,
                    user_id                UUID NOT NULL,
                    type                   TEXT NOT NULL DEFAULT 'FACT',
                    content                TEXT NOT NULL,
                    confidence             REAL NOT NULL DEFAULT 0.5,
                    supporting_memories    JSONB NOT NULL DEFAULT '[]',
                    contradicting_memories JSONB NOT NULL DEFAULT '[]',
                    version                INTEGER NOT NULL DEFAULT 1,
                    embedding              vector({dim}),
                    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_schemas_user ON schemas(user_id);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    id                   BIGSERIAL PRIMARY KEY,
                    user_id              UUID NOT NULL,
                    session_id           TEXT NOT NULL,
                    turn_index           INTEGER NOT NULL,
                    query                TEXT NOT NULL,
                    response             TEXT NOT NULL,
                    retrieved_memory_ids JSONB NOT NULL DEFAULT '[]',
                    timestamp            TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
        conn.commit()

    # ------------------------------------------------------------------ #
    # Memory CRUD
    # ------------------------------------------------------------------ #

    def save_memory(self, memory: MemoryNode) -> MemoryNode:
        memory.updated_at = datetime.now(timezone.utc)
        emb = f"[{','.join(str(x) for x in memory.embedding)}]" if memory.embedding else None
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories
                  (id, user_id, version, content, embedding, evidence, stability,
                   interference_score, schema_id, parent_id, successor_id, status,
                   created_at, updated_at, reconsolidation_count)
                VALUES (%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                  version=EXCLUDED.version, content=EXCLUDED.content,
                  embedding=EXCLUDED.embedding, evidence=EXCLUDED.evidence,
                  stability=EXCLUDED.stability,
                  interference_score=EXCLUDED.interference_score,
                  schema_id=EXCLUDED.schema_id, parent_id=EXCLUDED.parent_id,
                  successor_id=EXCLUDED.successor_id, status=EXCLUDED.status,
                  updated_at=EXCLUDED.updated_at,
                  reconsolidation_count=EXCLUDED.reconsolidation_count
                """,
                (
                    str(memory.id), str(memory.user_id), memory.version, memory.content,
                    emb,
                    json.dumps([e.model_dump() for e in memory.evidence]),
                    memory.stability, memory.interference_score,
                    str(memory.schema_id) if memory.schema_id else None,
                    str(memory.parent_id) if memory.parent_id else None,
                    str(memory.successor_id) if memory.successor_id else None,
                    memory.status.value,
                    memory.created_at, memory.updated_at,
                    memory.reconsolidation_count,
                ),
            )
        conn.commit()
        return memory

    def get_memory(self, memory_id: UUID) -> MemoryNode | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM memories WHERE id=%s", (str(memory_id),))
            row = cur.fetchone()
        return self._row_to_memory(dict(row)) if row else None

    def list_memories(
        self,
        user_id: UUID,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
    ) -> list[MemoryNode]:
        conn = self._connect()
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM memories WHERE user_id=%s AND status=%s ORDER BY created_at",
                    (str(user_id), status.value),
                )
            else:
                cur.execute(
                    "SELECT * FROM memories WHERE user_id=%s ORDER BY created_at",
                    (str(user_id),),
                )
            rows = cur.fetchall()
        return [self._row_to_memory(dict(r)) for r in rows]

    def list_user_ids(self) -> list[UUID]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT user_id FROM memories WHERE status = 'ACTIVE'"
            )
            rows = cur.fetchall()
        return [UUID(str(row["user_id"])) for row in rows]

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
            self._conn = None


    def search_memories(
        self,
        user_id: UUID,
        query_embedding: list[float],
        top_k: int = 50,
        status: MemoryStatus = MemoryStatus.ACTIVE,
    ) -> list[tuple[MemoryNode, float]]:
        """
        ANN search using pgvector `<=>` cosine distance operator.
        This runs natively in PostgreSQL via the ivfflat index.
        """
        if not query_embedding:
            return []
        emb_str = f"[{','.join(str(x) for x in query_embedding)}]"
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *, 1 - (embedding <=> %s::vector) AS cosine_sim
                FROM memories
                WHERE user_id=%s AND status=%s AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (emb_str, str(user_id), status.value, emb_str, top_k),
            )
            rows = cur.fetchall()
        return [(self._row_to_memory(dict(r)), float(r["cosine_sim"])) for r in rows]

    def get_recent_memories(self, user_id: UUID, hours: int) -> list[MemoryNode]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM memories
                WHERE user_id=%s AND status='ACTIVE'
                  AND created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY created_at
                """,
                (str(user_id), hours),
            )
            rows = cur.fetchall()
        return [self._row_to_memory(dict(r)) for r in rows]

    def get_stable_memories(self, user_id: UUID) -> list[MemoryNode]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM memories WHERE user_id=%s AND status='ACTIVE' AND stability>=%s",
                (str(user_id), self.config.stable_threshold),
            )
            rows = cur.fetchall()
        return [self._row_to_memory(dict(r)) for r in rows]

    def get_unstable_memories(self, user_id: UUID) -> list[MemoryNode]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM memories WHERE user_id=%s AND status='ACTIVE' AND stability<%s",
                (str(user_id), self.config.unstable_threshold),
            )
            rows = cur.fetchall()
        return [self._row_to_memory(dict(r)) for r in rows]

    # ------------------------------------------------------------------ #
    # Schema CRUD
    # ------------------------------------------------------------------ #

    def save_schema(self, schema: Schema) -> Schema:
        schema.updated_at = datetime.now(timezone.utc)
        emb = f"[{','.join(str(x) for x in schema.embedding)}]" if schema.embedding else None
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO schemas
                  (id, user_id, type, content, confidence, supporting_memories,
                   contradicting_memories, version, embedding, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                  type=EXCLUDED.type, content=EXCLUDED.content,
                  confidence=EXCLUDED.confidence,
                  supporting_memories=EXCLUDED.supporting_memories,
                  contradicting_memories=EXCLUDED.contradicting_memories,
                  version=EXCLUDED.version, embedding=EXCLUDED.embedding,
                  updated_at=EXCLUDED.updated_at
                """,
                (
                    str(schema.id), str(schema.user_id), schema.type.value,
                    schema.content, schema.confidence,
                    json.dumps([str(u) for u in schema.supporting_memories]),
                    json.dumps([str(u) for u in schema.contradicting_memories]),
                    schema.version, emb,
                    schema.created_at, schema.updated_at,
                ),
            )
        conn.commit()
        return schema

    def list_schemas(self, user_id: UUID) -> list[Schema]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM schemas WHERE user_id=%s ORDER BY created_at",
                (str(user_id),),
            )
            rows = cur.fetchall()
        return [self._row_to_schema(dict(r)) for r in rows]

    def get_schema(self, schema_id: UUID) -> Schema | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM schemas WHERE id=%s", (str(schema_id),))
            row = cur.fetchone()
        return self._row_to_schema(dict(row)) if row else None

    # ------------------------------------------------------------------ #
    # Traces
    # ------------------------------------------------------------------ #

    def save_trace(self, trace: dict) -> None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO traces
                  (user_id, session_id, turn_index, query, response,
                   retrieved_memory_ids, timestamp)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    trace["user_id"], trace["session_id"], trace["turn_index"],
                    trace["query"], trace["response"],
                    json.dumps(trace.get("retrieved_memory_ids", [])),
                    trace["timestamp"],
                ),
            )
        conn.commit()

    def list_traces(self, user_id: UUID, session_id: str | None = None) -> list[dict]:
        conn = self._connect()
        with conn.cursor() as cur:
            if session_id:
                cur.execute(
                    "SELECT * FROM traces WHERE user_id=%s AND session_id=%s ORDER BY turn_index",
                    (str(user_id), session_id),
                )
            else:
                cur.execute(
                    "SELECT * FROM traces WHERE user_id=%s ORDER BY timestamp",
                    (str(user_id),),
                )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Clustering (used by ASC)
    # ------------------------------------------------------------------ #

    def cluster_embeddings(
        self, memories: list[MemoryNode], threshold: float = 0.6
    ) -> list[list[MemoryNode]]:
        """Greedy cosine-similarity clustering (same logic as SQLite store)."""
        if not memories:
            return []
        from cosmos_q.embeddings import cosine_similarity

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
                if cosine_similarity(mem.embedding, other.embedding) >= threshold:
                    cluster.append(other)
                    used.add(other.id)
            clusters.append(cluster)
        return clusters

    # ------------------------------------------------------------------ #
    # Row conversion helpers
    # ------------------------------------------------------------------ #

    def _row_to_memory(self, row: dict) -> MemoryNode:
        from cosmos_q.models import ContextRef

        emb = row.get("embedding")
        if emb is None:
            embedding: list[float] = []
        elif isinstance(emb, str):
            embedding = [float(x) for x in emb.strip("[]").split(",") if x.strip()]
        else:
            embedding = list(emb)

        evidence_raw = row.get("evidence", [])
        if isinstance(evidence_raw, str):
            evidence_raw = json.loads(evidence_raw)

        return MemoryNode(
            id=UUID(str(row["id"])),
            user_id=UUID(str(row["user_id"])),
            version=row["version"],
            content=row["content"],
            embedding=embedding,
            evidence=[ContextRef(**e) for e in evidence_raw],
            stability=row["stability"],
            interference_score=row["interference_score"],
            schema_id=UUID(str(row["schema_id"])) if row.get("schema_id") else None,
            parent_id=UUID(str(row["parent_id"])) if row.get("parent_id") else None,
            successor_id=UUID(str(row["successor_id"])) if row.get("successor_id") else None,
            status=MemoryStatus(row["status"]),
            created_at=row["created_at"] if isinstance(row["created_at"], datetime)
                       else datetime.fromisoformat(str(row["created_at"])),
            updated_at=row["updated_at"] if isinstance(row["updated_at"], datetime)
                       else datetime.fromisoformat(str(row["updated_at"])),
            reconsolidation_count=row["reconsolidation_count"],
        )

    def _row_to_schema(self, row: dict) -> Schema:
        emb = row.get("embedding")
        if emb is None:
            embedding: list[float] = []
        elif isinstance(emb, str):
            embedding = [float(x) for x in emb.strip("[]").split(",") if x.strip()]
        else:
            embedding = list(emb)

        def _uuids(val) -> list[UUID]:
            if isinstance(val, str):
                val = json.loads(val)
            return [UUID(u) for u in val if u]

        return Schema(
            id=UUID(str(row["id"])),
            user_id=UUID(str(row["user_id"])),
            type=SchemaType(row["type"]),
            content=row["content"],
            confidence=row["confidence"],
            supporting_memories=_uuids(row.get("supporting_memories", "[]")),
            contradicting_memories=_uuids(row.get("contradicting_memories", "[]")),
            version=row["version"],
            embedding=embedding,
            created_at=row["created_at"] if isinstance(row["created_at"], datetime)
                       else datetime.fromisoformat(str(row["created_at"])),
            updated_at=row["updated_at"] if isinstance(row["updated_at"], datetime)
                       else datetime.fromisoformat(str(row["updated_at"])),
        )
