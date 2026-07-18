"""Trace logger for agent turns."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from cosmos_q.models import TraceRecord
from cosmos_q.store.memory_store import MemoryStore


class TraceLogger:
    """Records agent input/output per turn."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def log(self, trace: TraceRecord) -> None:
        self.store.save_trace(
            {
                "user_id": str(trace.user_id),
                "session_id": trace.session_id,
                "turn_index": trace.turn_index,
                "query": trace.query,
                "response": trace.response,
                "retrieved_memory_ids": [str(m) for m in trace.retrieved_memory_ids],
                "timestamp": trace.timestamp.isoformat(),
            }
        )

    def get_session_history(
        self, user_id: UUID, session_id: str
    ) -> list[TraceRecord]:
        rows = self.store.list_traces(user_id, session_id)
        return [
            TraceRecord(
                user_id=user_id,
                session_id=r["session_id"],
                turn_index=r["turn_index"],
                query=r["query"],
                response=r["response"],
                retrieved_memory_ids=[
                    UUID(uid)
                    for uid in json.loads(r.get("retrieved_memory_ids", "[]"))
                    if uid
                ],
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in rows
        ]
