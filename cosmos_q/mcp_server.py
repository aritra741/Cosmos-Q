"""COSMOS-Q MCP Server.

Exposes COSMOS-Q's core memory operations as Model Context Protocol (MCP)
tool endpoints using Server-Sent Events (SSE), making the memory system
plug-in infrastructure for any Qwen agent.

Supported tools (up to 10 MCP servers per Responses API request):
  - memory_store          : Persist a new episodic memory.
  - memory_retrieve       : Retrieve and pack memories via UACP.
  - memory_reconsolidate  : Manually trigger RTR on a specific memory.
  - memory_forget         : Run IAAF forgetting pass for a user.
  - schema_query          : Query high-level schemas by type.

Start the server:
    cosmos-q mcp-server
    # or directly:
    python -m cosmos_q.mcp_server

Then register with Qwen Responses API:
    "mcp_servers": [{"url": "http://localhost:8765/sse", "name": "cosmos-q"}]

Requires: pip install fastapi uvicorn sse-starlette
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID, uuid4

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse
    import uvicorn
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

from cosmos_q.config import CosmosConfig
from cosmos_q.memory_layer import CosmosMemoryLayer
from cosmos_q.models import SchemaType

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# MCP protocol helpers
# --------------------------------------------------------------------------- #

def _sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _tool_result(tool_name: str, content: Any, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_name": tool_name,
        "content": content,
        "is_error": is_error,
    }


# Tool schemas advertised to Qwen
_TOOL_SCHEMAS = [
    {
        "name": "memory_store",
        "description": (
            "Persist a new episodic memory for a user. "
            "Embeds content via text-embedding-v3 and stores in COSMOS-Q."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User UUID"},
                "content": {"type": "string", "description": "Memory content to store"},
                "session_id": {"type": "string", "default": "default"},
            },
            "required": ["user_id", "content"],
        },
    },
    {
        "name": "memory_retrieve",
        "description": (
            "Retrieve and pack memories relevant to a query using UACP. "
            "Returns a memory brief ready to inject as system context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "query": {"type": "string"},
                "token_budget": {"type": "integer", "default": 2048},
            },
            "required": ["user_id", "query"],
        },
    },
    {
        "name": "memory_reconsolidate",
        "description": (
            "Apply RTR to a specific memory given new context. "
            "Creates a new versioned memory if semantic divergence exceeds threshold. "
            "Uses thinking mode for auditable reasoning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "memory_id": {"type": "string", "description": "UUID of the memory to reconsolidate"},
                "context": {"type": "string", "description": "New context evidence"},
                "query": {"type": "string", "default": ""},
            },
            "required": ["user_id", "memory_id", "context"],
        },
    },
    {
        "name": "memory_forget",
        "description": (
            "Run IAAF forgetting pass for a user: compute interference scores "
            "and archive memories that exceed the forgetting threshold."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "schema_query",
        "description": (
            "Query high-level memory schemas (PREFERENCE, GOAL, FACT, PROCEDURE, BEHAVIOR) "
            "for a user. Schemas are built by ASC from episodic memories."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "schema_type": {
                    "type": "string",
                    "enum": ["PREFERENCE", "GOAL", "FACT", "PROCEDURE", "BEHAVIOR", "ALL"],
                    "default": "ALL",
                },
                "min_confidence": {"type": "number", "default": 0.0},
            },
            "required": ["user_id"],
        },
    },
]


# --------------------------------------------------------------------------- #
# Tool handlers
# --------------------------------------------------------------------------- #

def _handle_memory_store(layer: CosmosMemoryLayer, params: dict) -> dict:
    user_id = UUID(params["user_id"])
    content = params["content"]
    session_id = params.get("session_id", "default")
    mem = layer.add_memory(user_id, content, session_id=session_id)
    return {
        "memory_id": str(mem.id),
        "content": mem.content,
        "stability": mem.stability,
        "version": mem.version,
    }


def _handle_memory_retrieve(layer: CosmosMemoryLayer, params: dict) -> dict:
    user_id = UUID(params["user_id"])
    query = params["query"]
    if "token_budget" in params:
        layer.config.token_budget = int(params["token_budget"])
    brief = layer.retrieve(user_id, query)
    return {
        "memory_brief": brief.text,
        "memory_count": len(brief.memories),
        "schema_count": len(brief.schemas),
        "total_tokens": brief.total_tokens,
        "memories": [
            {"id": str(m.id), "content": m.content, "stability": m.stability}
            for m in brief.memories
        ],
    }


def _handle_memory_reconsolidate(layer: CosmosMemoryLayer, params: dict) -> dict:
    user_id = UUID(params["user_id"])
    memory_id = UUID(params["memory_id"])
    context = params["context"]
    query = params.get("query", "")

    mem = layer.store.get_memory(memory_id)
    if mem is None:
        return {"error": f"Memory {memory_id} not found"}
    if str(mem.user_id) != str(user_id):
        return {"error": "Memory does not belong to this user"}

    # Use thinking mode for auditable reconsolidation reasoning
    updated = layer.rtr.process_retrieved(
        mem, query=query, context_text=context
    )
    return {
        "original_memory_id": str(memory_id),
        "result_memory_id": str(updated.id),
        "versioned": updated.id != mem.id,
        "new_version": updated.version,
        "stability": updated.stability,
        "content": updated.content,
    }


def _handle_memory_forget(layer: CosmosMemoryLayer, params: dict) -> dict:
    user_id = UUID(params["user_id"])
    archived = layer.forgetting.run_forgetting(user_id)
    return {
        "archived_count": len(archived),
        "archived_ids": [str(i) for i in archived],
    }


def _handle_schema_query(layer: CosmosMemoryLayer, params: dict) -> dict:
    user_id = UUID(params["user_id"])
    type_filter = params.get("schema_type", "ALL")
    min_conf = float(params.get("min_confidence", 0.0))

    schemas = layer.store.list_schemas(user_id)
    if type_filter != "ALL":
        schemas = [s for s in schemas if s.type.value == type_filter]
    schemas = [s for s in schemas if s.confidence >= min_conf]

    return {
        "schema_count": len(schemas),
        "schemas": [
            {
                "id": str(s.id),
                "type": s.type.value,
                "content": s.content,
                "confidence": round(s.confidence, 3),
                "supporting_count": len(s.supporting_memories),
            }
            for s in schemas
        ],
    }


_HANDLERS = {
    "memory_store": _handle_memory_store,
    "memory_retrieve": _handle_memory_retrieve,
    "memory_reconsolidate": _handle_memory_reconsolidate,
    "memory_forget": _handle_memory_forget,
    "schema_query": _handle_schema_query,
}


# --------------------------------------------------------------------------- #
# FastAPI application
# --------------------------------------------------------------------------- #

def create_app(config: CosmosConfig | None = None) -> "FastAPI":
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI and uvicorn are required for the MCP server. "
            "Install with: pip install fastapi uvicorn sse-starlette"
        )

    app = FastAPI(title="COSMOS-Q MCP Server", version="0.1.0")
    layer = CosmosMemoryLayer(config)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "cosmos-q-mcp"}

    @app.get("/tools")
    def list_tools():
        """MCP tool discovery endpoint."""
        return {"tools": _TOOL_SCHEMAS}

    @app.get("/sse")
    async def sse_endpoint(request: Request):
        """
        SSE endpoint for MCP protocol.
        On connect, streams the tool list.  Tool invocations arrive as
        POST /invoke (see below).
        """
        async def event_stream():
            yield _sse_event("tools", {"tools": _TOOL_SCHEMAS})
            yield _sse_event("ready", {"service": "cosmos-q", "tool_count": len(_TOOL_SCHEMAS)})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/invoke")
    async def invoke_tool(request: Request):
        """Invoke a COSMOS-Q memory tool."""
        body = await request.json()
        tool_name = body.get("tool")
        params = body.get("params", {})

        handler = _HANDLERS.get(tool_name)
        if handler is None:
            return _tool_result(
                tool_name or "unknown",
                {"error": f"Unknown tool: {tool_name!r}. Available: {list(_HANDLERS)}"},
                is_error=True,
            )

        try:
            result = handler(layer, params)
            return _tool_result(tool_name, result)
        except Exception as exc:
            logger.exception("Tool %r raised: %s", tool_name, exc)
            return _tool_result(tool_name, {"error": str(exc)}, is_error=True)

    return app


def run_server(config: CosmosConfig | None = None) -> None:
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "Install FastAPI and uvicorn: pip install fastapi uvicorn sse-starlette"
        )
    cfg = config or CosmosConfig()
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.mcp_host, port=cfg.mcp_port)


if __name__ == "__main__":
    run_server()
