"""REST API for the COSMOS-Q memory theater frontend.

Endpoints:
  GET  /api/user              → get or create a demo user id
  GET  /api/state             → memory graph + UACP panel snapshot
  POST /api/chat              → chat turn with memory-augmented response
  POST /api/session/end       → end session (IAAF + ASC maintenance)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from cosmos_q.memory_layer import CosmosMemoryLayer
from cosmos_q.models import MemoryNode, MemoryStatus, Schema
from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import APIRouter

logger = logging.getLogger(__name__)

_USER_ID_FILE = Path.home() / ".cosmos_q_demo_user_id"


class ChatRequest(BaseModel):
    message: str
    user_id: str | None = None
    session_id: str = "default"
    turn_index: int = 0


class SessionEndRequest(BaseModel):
    user_id: str | None = None
    session_id: str = "default"


def get_or_create_user_id(explicit: str | None = None) -> UUID:
    if explicit:
        return UUID(explicit)
    if _USER_ID_FILE.exists():
        return UUID(_USER_ID_FILE.read_text().strip())
    new_id = uuid4()
    _USER_ID_FILE.write_text(str(new_id))
    return new_id


def _memory_label(content: str, max_len: int = 28) -> str:
    text = content.strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _node_payload(mem: MemoryNode) -> dict[str, Any]:
    return {
        "id": str(mem.id),
        "label": _memory_label(mem.content),
        "status": mem.status.value,
        "stability": round(mem.stability, 3),
        "parentId": str(mem.parent_id) if mem.parent_id else None,
    }


def _schema_payload(schema: Schema) -> dict[str, Any]:
    return {
        "id": str(schema.id),
        "type": schema.type.value,
        "summary": schema.content,
        "confidence": round(schema.confidence, 3),
    }


def _active_memory_scores(
    layer: CosmosMemoryLayer,
    user_id: UUID,
    query: str,
    packed_ids: set[UUID],
) -> list[dict[str, Any]]:
    """Score candidate memories for the UACP active-memories panel."""
    query_emb = layer.embedder.embed(query)
    candidates_with_scores = layer.store.search_memories(
        user_id,
        query_emb,
        top_k=layer.config.candidate_pool_size,
    )
    candidates = [m for m, _ in candidates_with_scores]
    schemas = layer.store.list_schemas(user_id)
    schema_map = {s.id: s for s in schemas}
    packer = layer.packer

    scored: list[dict[str, Any]] = []
    for mem in candidates:
        tokens = mem.token_cost()
        utility = packer._utility(mem, query_emb, schema_map)
        rho = utility / tokens if tokens > 0 else 0.0
        scored.append(
            {
                "id": str(mem.id),
                "label": _memory_label(mem.content),
                "utility": round(min(rho, 1.0), 3),
                "excluded": mem.id not in packed_ids,
            }
        )

    scored.sort(key=lambda x: x["utility"], reverse=True)
    return scored[:12]


def build_theater_state(
    layer: CosmosMemoryLayer,
    user_id: UUID,
    query: str = "",
    last_brief_tokens: int | None = None,
) -> dict[str, Any]:
    """Serialize memory graph + UACP panel for the frontend."""
    all_memories = layer.store.list_memories(user_id, status=None)
    schemas = layer.store.list_schemas(user_id)

    packed_ids: set[UUID] = set()
    budget_used = last_brief_tokens or 0
    active_memories: list[dict[str, Any]] = []

    if query:
        brief = layer.retrieve(user_id, query)
        packed_ids = {m.id for m in brief.memories}
        budget_used = brief.total_tokens
        active_memories = _active_memory_scores(layer, user_id, query, packed_ids)
    elif all_memories:
        # No query yet — show top active memories by stability.
        active = [m for m in all_memories if m.status == MemoryStatus.ACTIVE]
        active.sort(key=lambda m: m.stability, reverse=True)
        active_memories = [
            {
                "id": str(m.id),
                "label": _memory_label(m.content),
                "utility": round(m.stability, 3),
                "excluded": False,
            }
            for m in active[:8]
        ]

    return {
        "nodes": [_node_payload(m) for m in all_memories],
        "activeMemories": active_memories,
        "schemas": [_schema_payload(s) for s in schemas],
        "budgetUsed": budget_used,
        "budgetTotal": layer.config.token_budget,
    }


def create_web_router(layer: CosmosMemoryLayer) -> "APIRouter":
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api")

    @router.get("/user")
    def get_user(user_id: str | None = None):
        uid = get_or_create_user_id(user_id)
        return {"user_id": str(uid)}

    @router.get("/state")
    def get_state(user_id: str | None = None, query: str = ""):
        uid = get_or_create_user_id(user_id)
        return build_theater_state(layer, uid, query=query)

    @router.post("/chat")
    def chat(body: ChatRequest):
        uid = get_or_create_user_id(body.user_id)
        message = body.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")

        try:
            if layer.qwen.is_available():
                result = layer.chat(
                    uid,
                    message,
                    session_id=body.session_id,
                    turn_index=body.turn_index,
                )
            else:
                mock_response = (
                    f"I received your message and updated memory accordingly. "
                    f"(Set COSMOS_QWEN_API_KEY for live Qwen responses.)"
                )
                result = layer.chat_mock(
                    uid,
                    message,
                    mock_response,
                    session_id=body.session_id,
                    turn_index=body.turn_index,
                )
        except Exception as exc:
            logger.exception("Chat failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        theater = build_theater_state(
            layer,
            uid,
            query=message,
            last_brief_tokens=result["total_tokens"],
        )

        return {
            "response": result["response"],
            "memory_brief": result["memory_brief"],
            "retrieved_count": result["retrieved_count"],
            "total_tokens": result["total_tokens"],
            "session_id": body.session_id,
            "turn_index": body.turn_index,
            "user_id": str(uid),
            "theater": theater,
        }

    @router.post("/session/end")
    def end_session(body: SessionEndRequest):
        uid = get_or_create_user_id(body.user_id)

        before = {
            str(m.id): m.status
            for m in layer.store.list_memories(uid, status=None)
        }

        layer.qwen.end_session(body.session_id)
        maintenance = layer.run_maintenance(uid)

        after_memories = layer.store.list_memories(uid, status=None)
        archived_ids = [
            str(m.id)
            for m in after_memories
            if m.status == MemoryStatus.ARCHIVED
            and before.get(str(m.id)) != MemoryStatus.ARCHIVED
        ]
        consolidated_ids = [
            str(m.id)
            for m in after_memories
            if m.status == MemoryStatus.CONSOLIDATED
            and before.get(str(m.id)) != MemoryStatus.CONSOLIDATED
        ]

        schemas = layer.store.list_schemas(uid)
        consolidation_label = schemas[-1].content if schemas else "Schema"

        return {
            "user_id": str(uid),
            "session_id": body.session_id,
            "archived_ids": archived_ids,
            "consolidated_ids": consolidated_ids,
            "consolidation_label": _memory_label(consolidation_label, 32),
            "maintenance": maintenance,
            "theater": build_theater_state(layer, uid),
        }

    return router
