"""Main COSMOS-Q memory layer orchestrating all six sub-modules."""

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
from cosmos_q.store.memory_store import MemoryStore


class CosmosMemoryLayer:
    """
    COSMOS-Q Memory Layer — the central orchestrator.

    Retrieve flow:
        query → similarity search → UACP → Memory Brief

    Chat flow:
        query → retrieve (UACP) → Qwen → RTR on retrieved memories (post-response)
             → Trace Logger → Episodic Buffer (write new memory)

    Between sessions (explicit):
        run_maintenance() → IAAF forgetting → ASC consolidation
    """

    def __init__(self, config: CosmosConfig | None = None):
        self.config = config or CosmosConfig()
        self.store = MemoryStore(self.config)
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

        RTR is intentionally *not* applied here — it requires the agent
        response to be meaningful.  Call chat() for the full RTR-enabled path.
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
    ) -> dict:
        """
        End-to-end: retrieve memories → call Qwen → RTR (post-response) →
        log trace → write episodic memory.
        """
        brief = self.retrieve(user_id, query)
        system_prompt = build_system_prompt(brief.text)
        response = self.qwen.chat(system_prompt, query)

        self._post_response_rtr(
            user_id, brief, query, response, session_id, turn_index
        )

        trace = TraceRecord(
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            query=query,
            response=response,
            retrieved_memory_ids=[m.id for m in brief.memories],
        )
        self.tracer.log(trace)
        self.pipeline.process_trace(trace)

        return {
            "response": response,
            "memory_brief": brief.text,
            "retrieved_count": len(brief.memories),
            "total_tokens": brief.total_tokens,
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
        Apply RTR only to memories that were actually packed into the brief,
        using the agent response as context.  This matches the paper: RTR fires
        when a retrieved memory's implication diverges from the new evidence.
        """
        context_text = f"Q: {query}\nA: {response}"
        for mem in brief.memories:
            fresh = self.store.get_memory(mem.id)
            if fresh and fresh.status.value == "ACTIVE":
                self.rtr.process_retrieved(
                    fresh, query, context_text, session_id, turn_index
                )

    def add_memory(self, user_id: UUID, content: str, **kwargs) -> MemoryNode:
        """Explicitly store a memory. Returns the created MemoryNode."""
        return self.buffer.ingest_explicit(user_id, content, **kwargs)

    def run_maintenance(self, user_id: UUID) -> dict:
        """Run IAAF forgetting + ASC consolidation between sessions."""
        return self.pipeline.run_maintenance(user_id)

    def get_active_memory_count(self, user_id: UUID) -> int:
        return len(self.store.list_memories(user_id))
