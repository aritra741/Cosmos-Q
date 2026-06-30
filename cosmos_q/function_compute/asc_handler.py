"""Alibaba Cloud Function Compute handler for Asynchronous Schema Consolidation.

COSMOS-Q triggers ASC as a serverless function instead of a persistent worker.
This handler is invoked on session-end events via Function Compute's
event-driven runtime.

Deployment:
    fun deploy -t template.yml  # or via Alibaba Cloud Console

Runtime:    python3.10
Memory:     512 MB
Timeout:    300 s (consolidation can be slow for large memory sets)

Environment variables required:
    COSMOS_QWEN_API_KEY
    COSMOS_PG_DSN       (or COSMOS_DB_PATH for SQLite)

Event payload schema (JSON):
    {
      "user_id": "<UUID>",
      "trigger": "session_end" | "scheduled" | "manual"
    }
"""

from __future__ import annotations

import json
import logging
import os
from uuid import UUID

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: bytes, context) -> dict:
    """
    Function Compute entry point.

    Receives a session-end event, runs IAAF + ASC maintenance for the user,
    and returns a summary result.
    """
    try:
        payload = json.loads(event.decode("utf-8"))
    except Exception as exc:
        logger.error("Failed to parse event payload: %s", exc)
        return {"success": False, "error": f"Invalid payload: {exc}"}

    user_id_str = payload.get("user_id")
    trigger = payload.get("trigger", "unknown")

    if not user_id_str:
        return {"success": False, "error": "Missing required field: user_id"}

    try:
        user_id = UUID(user_id_str)
    except ValueError as exc:
        return {"success": False, "error": f"Invalid user_id: {exc}"}

    logger.info("ASC triggered by '%s' for user %s", trigger, user_id)

    # Import here so the module loads correctly in FC's cold-start environment
    from cosmos_q.config import CosmosConfig
    from cosmos_q.memory_layer import CosmosMemoryLayer

    config = CosmosConfig()  # reads from environment variables
    layer = CosmosMemoryLayer(config)

    try:
        result = layer.run_maintenance(user_id)
        logger.info("Maintenance complete: %s", result)
        return {"success": True, "user_id": user_id_str, "trigger": trigger, **result}
    except Exception as exc:
        logger.exception("Maintenance failed for user %s: %s", user_id, exc)
        return {"success": False, "user_id": user_id_str, "error": str(exc)}
