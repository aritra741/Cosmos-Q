"""Main COSMOS-Q memory layer orchestrating all six sub-modules.

Integrates:
  - ApsaraDB RDS + pgvector or SQLite (selected by config.pg_dsn).
  - Qwen Responses API with previous_response_id (intra-session multi-turn).
  - Session cache (x-dashscope-session-cache header).
  - Thinking mode for high-stakes operations (RTR reconsolidation decisions).
  - Parallel tool calls for concurrent memory operations.
  - text-embedding-v3 (1024-dim) for R(m,q), Sim(), and schema clustering.
"""

from __future__ import annotations

from uuid import UUID

from cosmos_q.agent.pipeline import MemoryUpdatePipeline
from cosmos_q.agent.prompts import build_system_prompt
from cosmos_q.agent.qwen_client import QwenClient
from cosmos_q.agent.trace_logger import TraceLogger
from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import EmbeddingService
from cosmos_q.mechanisms.asc import ConsolidationEngine
from cosmos_q.mechanisms.episodic_buffer import EpisodicBuffer
from cosmos_q.mechanisms.iaaf import ForgettingEngine
from cosmos_q.mechanisms.rtr import ReconsolidationEngine
from cosmos_q.mechanisms.uacp import ContextPacker
from cosmos_q.models import AgentState, MemoryBrief, MemoryNode, TraceRecord
from cosmos_q.store import make_store


# Tool definitions exposed to Qwen for parallel function calling.
# The model can call these concurrently in a single response.
_COSMOS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_retrieve",
            "description": "Retrieve relevant memories for a query using COSMOS-Q UACP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The user query to retrieve memories for."},
                    "top_k": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schema_query",
            "description": "Query high-level schemas (preferences, goals, facts) for a user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_type": {
                        "type": "string",
                        "enum": ["PREFERENCE", "GOAL", "FACT", "PROCEDURE", "BEHAVIOR", "ALL"],
                        "default": "ALL",
                    }
                },
            },
        },
    },
]


class CosmosMemoryLayer:
    """
    COSMOS-Q Memory Layer.

    Retrieve flow:
        query → similarity search (text-embedding-v3 / pgvector ANN)
              → UACP → Memory Brief

    Chat flow:
        query → retrieve → Qwen Responses API (previous_response_id chain)
              → RTR post-response (thinking mode for high divergence)
              → Trace Logger → Episodic Buffer

    Between sessions:
        run_maintenance() → IAAF → ASC
        (or triggered via Alibaba Cloud Function Compute)
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self.store = make_store(self.config)
        self.embedder = EmbeddingService(self.config)
        self.rtr = ReconsolidationEngine(self.store, self.embedder, self.config)
        self.packer = ContextPacker(self.store, self.config)
        self.forgetting = ForgettingEngine(self.store, self.embedder, self.config)
        self.consolidation = ConsolidationEngine(
            self.store, self.embedder, self.config
        )
        self.buffer = EpisodicBuffer(self.store, self.embedder, self.config)
        self.pipeline = MemoryUpdatePipeline(
            self.store, self.embedder, self.config
        )
        self.tracer = TraceLogger(self.store)
        self.qwen = QwenClient(self.config)

    def retrieve(
        self,
        user_id: UUID,
        query: str,
        agent_state: AgentState | None = None,
    ) -> MemoryBrief:
        """
        Retrieve and pack memories for a query.

        Uses text-embedding-v3 for R(m,q) (relevance) and pgvector ANN when
        available.  RTR is not applied here — it requires the agent response.
        """
        state = agent_state or AgentState()
        query_emb = self.embedder.embed(query)

        candidates_with_scores = self.store.search_memories(
            user_id,
            query_emb,
            top_k=self.config.candidate_pool_size,
        )
        candidates = [m for m, _ in candidates_with_scores]

        schemas = self.store.list_schemas(user_id)
        return self.packer.pack(candidates, query_emb, state, schemas)

    def chat(
        self,
        user_id: UUID,
        query: str,
        session_id: str = "default",
        turn_index: int = 0,
        use_tools: bool = False,
    ) -> dict:
        """
        End-to-end chat using the Responses API.

        - `previous_response_id` chains intra-session context natively.
        - Session cache reduces token cost 10× on repeated context.
        - `use_tools=True` enables parallel function calling for concurrent
          memory_retrieve + schema_query in a single model call.
        - Thinking mode enabled post-response for RTR reconsolidation
          decisions when semantic divergence is non-trivial.
        """
        brief = self.retrieve(user_id, query)
        system_prompt = build_system_prompt(brief.text)

        response_text: str
        if use_tools and self.qwen.is_available():
            raw = self.qwen.chat_with_tools(
                system_prompt, query,
                tool_definitions=_COSMOS_TOOLS,
                session_id=session_id,
                use_thinking=False,
            )
            response_text = self.qwen._extract_text(raw)
        else:
            response_text = self.qwen.chat(
                system_prompt, query,
                session_id=session_id,
                use_thinking=False,
            )

        # RTR: use thinking mode for high-stakes reconsolidation decisions
        self._post_response_rtr(
            user_id, brief, query, response_text, session_id, turn_index
        )

        trace = TraceRecord(
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            query=query,
            response=response_text,
            retrieved_memory_ids=[m.id for m in brief.memories],
        )
        self.tracer.log(trace)
        self.pipeline.process_trace(trace)

        return {
            "response": response_text,
            "memory_brief": brief.text,
            "retrieved_count": len(brief.memories),
            "total_tokens": brief.total_tokens,
            "session_id": session_id,
        }

    def chat_mock(
        self,
        user_id: UUID,
        query: str,
        mock_response: str,
        session_id: str = "default",
        turn_index: int = 0,
    ) -> dict:
        """Same as chat() with a mock response (for evaluation without API key)."""
        brief = self.retrieve(user_id, query)
        self._post_response_rtr(
            user_id, brief, query, mock_response, session_id, turn_index
        )
        trace = TraceRecord(
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            query=query,
            response=mock_response,
            retrieved_memory_ids=[m.id for m in brief.memories],
        )
        self.tracer.log(trace)
        self.pipeline.process_trace(trace)
        return {
            "response": mock_response,
            "memory_brief": brief.text,
            "retrieved_count": len(brief.memories),
            "total_tokens": brief.total_tokens,
            "session_id": session_id,
        }

    def _post_response_rtr(
        self,
        user_id: UUID,
        brief: MemoryBrief,
        query: str,
        response: str,
        session_id: str,
        turn_index: int,
    ) -> None:
        """
        Apply RTR to packed memories using the full query+response as context.

        Thinking mode is used here when config.enable_thinking is True:
        it produces an auditable reasoning chain for reconsolidation decisions
        (should this memory be revised?), improving the quality of versioning.
        """
        context_text = f"Q: {query}\nA: {response}"
        for mem in brief.memories:
            fresh = self.store.get_memory(mem.id)
            if fresh and fresh.status.value == "ACTIVE":
                self.rtr.process_retrieved(
                    fresh, query, context_text, session_id, turn_index
                )

    def end_session(self, user_id: UUID, session_id: str) -> None:
        """
        Close an intra-session Responses API chain and trigger maintenance.

        Call this at the end of a user session so:
          1. The previous_response_id chain is discarded.
          2. IAAF + ASC maintenance runs (or is delegated to Function Compute).
        """
        self.qwen.end_session(session_id)
        self.run_maintenance(user_id)

    def add_memory(self, user_id: UUID, content: str, **kwargs) -> MemoryNode:
        """Explicitly store a memory. Returns the created MemoryNode."""
        return self.buffer.ingest_explicit(user_id, content, **kwargs)

    def run_maintenance(self, user_id: UUID) -> dict:
        """Run IAAF forgetting + ASC consolidation between sessions."""
        return self.pipeline.run_maintenance(user_id)

    def get_active_memory_count(self, user_id: UUID) -> int:
        return len(self.store.list_memories(user_id))
