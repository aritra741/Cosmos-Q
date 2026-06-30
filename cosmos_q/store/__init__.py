"""Store factory — returns SQLite or PostgreSQL + pgvector store based on config."""

from __future__ import annotations

from cosmos_q.config import CosmosConfig


def make_store(config: CosmosConfig | None = None):
    """
    Return the appropriate store implementation.

    - If `config.pg_dsn` is set → ApsaraDB RDS + pgvector (PgMemoryStore).
    - Otherwise → SQLite (MemoryStore).
    """
    cfg = config or CosmosConfig()
    if cfg.pg_dsn:
        from cosmos_q.store.pg_store import PgMemoryStore
        return PgMemoryStore(cfg)
    from cosmos_q.store.memory_store import MemoryStore
    return MemoryStore(cfg)
