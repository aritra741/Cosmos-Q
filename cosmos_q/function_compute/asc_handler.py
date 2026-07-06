"""
Alibaba Cloud Function Compute entry point for COSMOS-Q maintenance.

Runs the between-session cognitive maintenance pipeline:
  1. IAAF — update interference scores, then archive high-interference memories
  2. ASC  — consolidate active episodic memories into schemas

Triggered by:
  - Timer trigger (daily 03:00 UTC) → runs maintenance for ALL users
  - Manual/session-end invoke with {"user_id": "<uuid>"} → runs for one user

Environment variables (set in s.yaml):
  COSMOS_PG_DSN         PostgreSQL DSN for ApsaraDB RDS (pgvector)
  COSMOS_QWEN_API_KEY   DashScope API key (ASC schema summarisation uses Qwen)

Contract:
  handler(event, context) -> dict   # FC's standard Python signature
"""

import json
import logging
import os
from typing import Any
from uuid import UUID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cosmos_q.fc.asc_handler")


def _parse_event(event: Any) -> dict:
    """FC passes `event` as bytes | str | dict depending on trigger type.

    Timer triggers deliver a JSON payload describing the trigger; manual
    invokes deliver whatever the caller sent. Normalise all of these to a dict.
    """
    if event is None:
        return {}
    if isinstance(event, (bytes, bytearray)):
        event = event.decode("utf-8")
    if isinstance(event, str):
        event = event.strip()
        if not event:
            return {}
        try:
            return json.loads(event)
        except json.JSONDecodeError:
            # Timer trigger sometimes sends a non-JSON string; treat as "run all"
            logger.info("Non-JSON event payload; defaulting to all-users run.")
            return {}
    if isinstance(event, dict):
        return event
    return {}


def _run_maintenance_for_user(memory_layer, user_id: UUID) -> dict:
    """Run the full IAAF -> ASC pipeline for a single user."""
    # Mapping to real attributes of CosmosMemoryLayer:
    # memory_layer.forgetting -> ForgettingEngine (IAAF)
    # memory_layer.consolidation -> ConsolidationEngine (ASC)
    iaaf = memory_layer.forgetting
    asc = memory_layer.consolidation

    iaaf.update_interference_scores(user_id)
    forgotten = iaaf.run_forgetting(user_id)          # returns count or list
    consolidation = asc.run_consolidation(user_id)    # returns list of Schema objects

    archived_count = len(forgotten) if hasattr(forgotten, "__len__") else int(forgotten or 0)
    
    # Custom helper to serialize Schema objects to dicts if needed
    consolidation_dicts = []
    if consolidation:
        for schema in consolidation:
            if hasattr(schema, "model_dump"):
                consolidation_dicts.append(schema.model_dump())
            elif hasattr(schema, "to_dict"):
                consolidation_dicts.append(schema.to_dict())
            else:
                consolidation_dicts.append(str(schema))

    return {
        "user_id": str(user_id),
        "memories_archived": archived_count,
        "consolidation": consolidation_dicts,
    }


def handler(event, context):
    """Function Compute HTTP/event handler.

    Returns a JSON-serialisable dict summarising the maintenance run.
    Never raises to FC for expected conditions — always returns a status dict,
    so timer runs don't spam FC's error metrics. Unexpected errors are logged
    and re-raised so they surface in `s logs`.
    """
    # Import inside handler so cold-start import errors are captured in logs,
    # and so the module is importable in unit tests without FC runtime.
    from cosmos_q.config import CosmosConfig
    from cosmos_q.memory_layer import CosmosMemoryLayer

    payload = _parse_event(event)
    logger.info("ASC handler invoked. payload=%s", payload)

    dsn = os.environ.get("COSMOS_PG_DSN")
    if not dsn:
        msg = "COSMOS_PG_DSN not set; refusing to run against SQLite in FC."
        logger.error(msg)
        return {"status": "error", "error": msg}

    config = CosmosConfig()  # reads COSMOS_* env vars
    memory_layer = CosmosMemoryLayer(config=config)

    results = []
    try:
        target_user_str = payload.get("user_id")

        if target_user_str:
            # Single-user run (session-end trigger)
            try:
                target_user = UUID(target_user_str)
                results.append(_run_maintenance_for_user(memory_layer, target_user))
            except ValueError as exc:
                msg = f"Invalid user_id: {target_user_str}"
                logger.error(msg)
                return {"status": "error", "error": msg}
        else:
            # All-users run (daily timer)
            user_ids = memory_layer.store.list_user_ids()
            logger.info("Running maintenance for %d users.", len(user_ids))
            for uid in user_ids:
                try:
                    results.append(_run_maintenance_for_user(memory_layer, uid))
                except Exception as exc:  # isolate per-user failures
                    logger.exception("Maintenance failed for user %s", uid)
                    results.append({"user_id": str(uid), "status": "error", "error": str(exc)})

        summary = {
            "status": "ok",
            "trigger": payload.get("trigger", "timer"),
            "users_processed": len(results),
            "results": results,
        }
        logger.info("ASC handler complete: %s", json.dumps(summary))
        return summary

    finally:
        # Close DB connections so FC doesn't leak pooled connections across
        # warm invocations. Implement close() on the store if not present.
        close = getattr(memory_layer.store, "close", None)
        if callable(close):
            close()
