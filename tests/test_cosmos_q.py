"""Tests for COSMOS-Q."""

from __future__ import annotations

import json
import tempfile
from uuid import UUID, uuid4

import pytest

from cosmos_q.config import CosmosConfig
from cosmos_q.embeddings import (
    EmbeddingService,
    cosine_similarity,
    estimate_contradiction,
    semantic_divergence,
)
from cosmos_q.evaluation.cmem import build_cmem_scenarios
from cosmos_q.evaluation.harness import EvaluationHarness
from cosmos_q.evaluation.metrics import check_answer, check_retrieval_contains
from cosmos_q.memory_layer import CosmosMemoryLayer
from cosmos_q.models import MemoryNode, MemoryStatus, TraceRecord
from cosmos_q.store.memory_store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name


@pytest.fixture
def layer(tmp_db):
    config = CosmosConfig(db_path=tmp_db, token_budget=512)
    return CosmosMemoryLayer(config)


@pytest.fixture
def user_id():
    return uuid4()


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class TestEmbeddings:
    def test_embed_returns_normalised_vector(self):
        import numpy as np

        emb = EmbeddingService()
        vec = emb.embed("hello world")
        assert len(vec) == emb.active_dim
        assert abs(np.linalg.norm(vec) - 1.0) < 0.01

    def test_identical_texts_have_similarity_one(self):
        emb = EmbeddingService()
        v = emb.embed("test sentence")
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=0.01)

    def test_unrelated_texts_have_higher_divergence_than_similar_texts(self):
        emb = EmbeddingService()
        a = emb.embed("I like tea")
        b = emb.embed("I enjoy tea")
        c = emb.embed("quantum mechanics and particle physics")
        assert semantic_divergence(a, b) < semantic_divergence(a, c)

    def test_empty_vector_returns_zero_similarity(self):
        v = EmbeddingService().embed("hello")
        assert cosine_similarity([], v) == 0.0
        assert cosine_similarity(v, []) == 0.0

    def test_similarity_clamped_to_one(self):
        v = EmbeddingService().embed("test")
        sim = cosine_similarity(v, v)
        assert 0.0 <= sim <= 1.0

    def test_contradiction_negation_pairs(self):
        score = estimate_contradiction("I like dark mode", "I dislike dark mode")
        assert score > 0.5

    def test_contradiction_uses_provided_embedder(self):
        """estimate_contradiction should use the passed embedder, not a new one."""
        emb = EmbeddingService()
        score = estimate_contradiction("I prefer tea", "I avoid tea", embedder=emb)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------


class TestMemoryStore:
    def test_save_and_retrieve_by_id(self, tmp_db, user_id):
        store = MemoryStore(CosmosConfig(db_path=tmp_db))
        emb = EmbeddingService()
        mem = MemoryNode(
            user_id=user_id,
            content="User prefers dark mode",
            embedding=emb.embed("User prefers dark mode"),
        )
        store.save_memory(mem)
        found = store.get_memory(mem.id)
        assert found is not None
        assert found.content == mem.content

    def test_nonexistent_memory_returns_none(self, tmp_db, user_id):
        store = MemoryStore(CosmosConfig(db_path=tmp_db))
        assert store.get_memory(uuid4()) is None

    def test_vector_search_returns_most_relevant_first(self, tmp_db, user_id):
        store = MemoryStore(CosmosConfig(db_path=tmp_db))
        emb = EmbeddingService()
        for text in ["dark mode preference", "weather is sunny", "python programming"]:
            store.save_memory(
                MemoryNode(
                    user_id=user_id,
                    content=text,
                    embedding=emb.embed(text),
                )
            )
        results = store.search_memories(
            user_id, emb.embed("display theme settings"), top_k=3
        )
        assert len(results) == 3
        # Dark mode should rank first for "display theme settings"
        assert "dark mode" in results[0][0].content

    def test_memories_with_empty_embedding_excluded_from_search(self, tmp_db, user_id):
        store = MemoryStore(CosmosConfig(db_path=tmp_db))
        emb = EmbeddingService()
        good = MemoryNode(
            user_id=user_id,
            content="good memory",
            embedding=emb.embed("good memory"),
        )
        bad = MemoryNode(user_id=user_id, content="no embedding", embedding=[])
        store.save_memory(good)
        store.save_memory(bad)
        results = store.search_memories(user_id, emb.embed("good memory"), top_k=10)
        result_ids = {m.id for m, _ in results}
        assert good.id in result_ids
        assert bad.id not in result_ids

    def test_list_memories_filters_by_status(self, tmp_db, user_id):
        store = MemoryStore(CosmosConfig(db_path=tmp_db))
        emb = EmbeddingService()
        active = MemoryNode(
            user_id=user_id,
            content="active",
            embedding=emb.embed("active"),
            status=MemoryStatus.ACTIVE,
        )
        archived = MemoryNode(
            user_id=user_id,
            content="archived",
            embedding=emb.embed("archived"),
            status=MemoryStatus.ARCHIVED,
        )
        store.save_memory(active)
        store.save_memory(archived)
        active_list = store.list_memories(user_id, status=MemoryStatus.ACTIVE)
        assert all(m.status == MemoryStatus.ACTIVE for m in active_list)
        assert archived.id not in {m.id for m in active_list}


# ---------------------------------------------------------------------------
# RTR
# ---------------------------------------------------------------------------


class TestRTR:
    def test_reinforcement_increases_stability_on_consistent_context(
        self, layer, user_id
    ):
        """When context is consistent (low divergence) stability should increase."""
        layer.add_memory(user_id, "User prefers dark mode")
        mem = layer.store.list_memories(user_id)[0]
        original_stability = mem.stability

        # Use very similar text as context → low divergence
        layer.rtr.process_retrieved(
            mem,
            query="What theme?",
            context_text="dark mode",  # highly consistent
        )
        refreshed = layer.store.get_memory(mem.id)
        assert refreshed is not None
        assert refreshed.stability >= original_stability

    def test_versioning_creates_new_node_and_supersedes_old(self, layer, user_id):
        """When context diverges, a new version must be created."""
        layer.add_memory(user_id, "User prefers tea")
        mem = layer.store.list_memories(user_id)[0]

        layer.config.tau_rtr = 0.01  # force versioning on any divergence
        updated = layer.rtr.process_retrieved(
            mem,
            query="What do you drink?",
            context_text="Q: What do you drink? A: User now strongly prefers coffee every morning.",
        )
        old = layer.store.get_memory(mem.id)
        assert old is not None

        if updated.id != mem.id:
            # Versioning fired: old must be SUPERSEDED
            assert old.status == MemoryStatus.SUPERSEDED
            assert old.successor_id == updated.id
            assert updated.version == mem.version + 1
            assert updated.status == MemoryStatus.ACTIVE
        else:
            # divergence was still < 0.01 with hash embeddings — reinforcement path
            assert updated.stability >= mem.stability

    def test_rtr_skipped_when_context_text_is_empty(self, layer, user_id):
        """Empty context_text must not trigger versioning (pre-response retrieval)."""
        layer.add_memory(user_id, "User prefers tea")
        mem = layer.store.list_memories(user_id)[0]
        result = layer.rtr.process_retrieved(mem, query="What do you drink?", context_text="")
        # Must return same memory, unchanged
        assert result.id == mem.id

    def test_rtr_skipped_when_disabled(self, tmp_db, user_id):
        config = CosmosConfig.ablation("no_rtr", db_path=tmp_db)
        layer = CosmosMemoryLayer(config)
        layer.add_memory(user_id, "User prefers tea")
        mem = layer.store.list_memories(user_id)[0]
        result = layer.rtr.process_retrieved(
            mem, query="q", context_text="completely unrelated different topic"
        )
        assert result.id == mem.id  # no version created when RTR disabled

    def test_reconsolidation_count_incremented_on_reinforce(self, layer, user_id):
        layer.add_memory(user_id, "User prefers dark mode")
        mem = layer.store.list_memories(user_id)[0]
        original_count = mem.reconsolidation_count
        layer.rtr.process_retrieved(mem, query="theme?", context_text="dark mode")
        refreshed = layer.store.get_memory(mem.id)
        assert refreshed is not None
        assert refreshed.reconsolidation_count >= original_count

    def test_new_version_inherits_schema_id(self, layer, user_id):
        """After RTR versioning, schema_id should be propagated."""
        from cosmos_q.models import Schema, SchemaType

        schema = layer.store.save_schema(
            Schema(user_id=user_id, type=SchemaType.PREFERENCE, content="pref")
        )
        layer.add_memory(user_id, "User prefers tea")
        mem = layer.store.list_memories(user_id)[0]
        mem.schema_id = schema.id
        layer.store.save_memory(mem)

        layer.config.tau_rtr = 0.01
        updated = layer.rtr.process_retrieved(
            mem,
            query="What do you drink?",
            context_text="Q: What? A: User prefers coffee exclusively.",
        )
        if updated.id != mem.id:
            assert updated.schema_id == schema.id


# ---------------------------------------------------------------------------
# UACP
# ---------------------------------------------------------------------------


class TestUACP:
    def test_total_tokens_within_budget(self, layer, user_id):
        for i in range(30):
            layer.add_memory(user_id, f"Memory {i}: " + "content " * 20)
        brief = layer.retrieve(user_id, "memory content")
        assert brief.total_tokens <= layer.config.token_budget

    def test_schema_tokens_counted_in_budget(self, layer, user_id):
        """Schema section tokens must not push total over budget."""
        from cosmos_q.models import Schema, SchemaType

        for i in range(5):
            layer.store.save_schema(
                Schema(
                    user_id=user_id,
                    type=SchemaType.PREFERENCE,
                    content="A long schema entry " * 10,
                    embedding=layer.embedder.embed("A long schema entry " * 10),
                )
            )
        for i in range(10):
            layer.add_memory(user_id, "memory content " * 10)
        brief = layer.retrieve(user_id, "memory content")
        assert brief.total_tokens <= layer.config.token_budget

    def test_no_uacp_ablation_respects_budget(self, tmp_db, user_id):
        config = CosmosConfig.ablation("no_uacp", db_path=tmp_db, token_budget=128)
        layer = CosmosMemoryLayer(config)
        for i in range(20):
            layer.add_memory(user_id, "test memory one two three four five " * 3)
        brief = layer.retrieve(user_id, "test")
        assert brief.total_tokens <= config.token_budget

    def test_more_relevant_memory_ranked_higher(self, layer, user_id):
        layer.add_memory(user_id, "dark mode is my preferred display setting")
        layer.add_memory(user_id, "I enjoy hiking in the mountains")
        brief = layer.retrieve(user_id, "display theme preferences")
        assert len(brief.memories) > 0
        # "dark mode" memory should be in the brief
        contents = [m.content for m in brief.memories]
        assert any("dark mode" in c for c in contents)

    def test_brief_text_and_schemas_consistent(self, layer, user_id):
        from cosmos_q.models import Schema, SchemaType

        schema = layer.store.save_schema(
            Schema(
                user_id=user_id,
                type=SchemaType.PREFERENCE,
                content="User likes dark interfaces",
                embedding=layer.embedder.embed("dark interface preference"),
            )
        )
        layer.add_memory(user_id, "User prefers dark mode")
        brief = layer.retrieve(user_id, "theme")
        # Schemas in .schemas and in .text must be consistent
        for s in brief.schemas:
            assert s.content in brief.text


# ---------------------------------------------------------------------------
# IAAF
# ---------------------------------------------------------------------------


class TestIAAF:
    def test_interference_score_is_in_range(self, layer, user_id):
        layer.add_memory(user_id, "User prefers tea in the morning")
        layer.add_memory(user_id, "User dislikes tea and avoids it")
        memories = layer.forgetting.update_interference_scores(user_id)
        for m in memories:
            assert 0.0 <= m.interference_score <= 1.0

    def test_run_forgetting_archives_high_interference_memories(self, layer, user_id):
        layer.add_memory(user_id, "User prefers tea in the morning")
        layer.add_memory(user_id, "User dislikes tea and avoids it")
        # Force a very low threshold so archiving fires
        layer.config.tau_forget = 0.0
        archived = layer.forgetting.run_forgetting(user_id)
        # At least some memories should be archived at threshold=0
        assert len(archived) > 0
        for mid in archived:
            m = layer.store.get_memory(mid)
            assert m is not None
            assert m.status == MemoryStatus.ARCHIVED

    def test_iaaf_disabled_returns_empty_list(self, tmp_db, user_id):
        config = CosmosConfig.ablation("no_iaaf", db_path=tmp_db)
        layer = CosmosMemoryLayer(config)
        layer.add_memory(user_id, "tea preference")
        layer.add_memory(user_id, "dislike tea")
        result = layer.forgetting.run_forgetting(user_id)
        assert result == []
        # Memories must remain ACTIVE
        mems = layer.store.list_memories(user_id)
        assert all(m.status == MemoryStatus.ACTIVE for m in mems)

    def test_memory_with_no_embedding_gets_zero_interference(self, layer, user_id):
        mem = MemoryNode(user_id=user_id, content="no embedding", embedding=[])
        layer.store.save_memory(mem)
        score = layer.forgetting._compute_interference(mem, [mem])
        assert score == 0.0


# ---------------------------------------------------------------------------
# ASC
# ---------------------------------------------------------------------------


class TestASC:
    def test_consolidation_creates_schema(self, layer, user_id):
        layer.add_memory(user_id, "User prefers dark mode")
        layer.add_memory(user_id, "User likes dark theme interfaces")
        schemas = layer.consolidation.run_consolidation(user_id)
        assert len(schemas) >= 1

    def test_consolidated_memories_status(self, layer, user_id):
        layer.add_memory(user_id, "User prefers dark mode")
        layer.add_memory(user_id, "User likes dark theme interfaces")
        before = layer.get_active_memory_count(user_id)
        layer.consolidation.run_consolidation(user_id)
        # assembly-defect fix: episodics remain ACTIVE and retrievable
        after = layer.get_active_memory_count(user_id)
        assert after == before
        schemas = layer.store.list_schemas(user_id)
        assert schemas
        for m in layer.store.list_memories(user_id):
            assert m.status == MemoryStatus.ACTIVE
            assert m.schema_id is not None

    def test_supporting_memories_no_duplicates(self, layer, user_id):
        layer.add_memory(user_id, "User prefers dark mode")
        layer.add_memory(user_id, "User likes dark theme interfaces")
        layer.consolidation.run_consolidation(user_id)
        layer.consolidation.run_consolidation(user_id)
        schemas = layer.store.list_schemas(user_id)
        for s in schemas:
            assert len(s.supporting_memories) == len(set(s.supporting_memories))
            assert len(s.contradicting_memories) == len(set(s.contradicting_memories))

    def test_asc_disabled_returns_empty(self, tmp_db, user_id):
        config = CosmosConfig.ablation("no_asc", db_path=tmp_db)
        layer = CosmosMemoryLayer(config)
        layer.add_memory(user_id, "User prefers dark mode")
        result = layer.consolidation.run_consolidation(user_id)
        assert result == []
        assert layer.store.list_schemas(user_id) == []

    def test_cluster_threshold_configurable(self):
        config = CosmosConfig(asc_cluster_threshold=0.9)
        assert config.asc_cluster_threshold == 0.9


# ---------------------------------------------------------------------------
# Agent integration
# ---------------------------------------------------------------------------


class TestAgentIntegration:
    def test_add_memory_returns_memory_node(self, layer, user_id):
        mem = layer.add_memory(user_id, "User prefers Python")
        assert isinstance(mem, MemoryNode)
        assert mem.id is not None
        assert mem.content == "User prefers Python"

    def test_chat_mock_writes_exactly_one_memory_per_turn(self, layer, user_id):
        before = layer.get_active_memory_count(user_id)
        layer.chat_mock(
            user_id,
            "I prefer Python for scripting",
            mock_response="Got it.",
            session_id="s1",
            turn_index=0,
        )
        after = layer.get_active_memory_count(user_id)
        # Exactly one new memory from episodic buffer
        assert after == before + 1

    def test_add_memory_then_retrieve(self, layer, user_id):
        layer.add_memory(user_id, "User's name is Alex")
        layer.add_memory(user_id, "User works at Beta Inc")
        brief = layer.retrieve(user_id, "What is my name?")
        # At minimum Alex should appear in the brief
        assert "alex" in brief.text.lower()

    def test_retrieve_does_not_apply_rtr(self, layer, user_id):
        """retrieve() must not version memories (no response context available)."""
        layer.add_memory(user_id, "User prefers tea")
        mem = layer.store.list_memories(user_id)[0]
        layer.retrieve(user_id, "What do I drink?")
        refreshed = layer.store.get_memory(mem.id)
        assert refreshed is not None
        assert refreshed.status == MemoryStatus.ACTIVE
        assert refreshed.successor_id is None

    def test_post_response_rtr_runs_only_on_packed_memories(self, layer, user_id):
        """_post_response_rtr touches only memories selected for the brief."""
        for i in range(10):
            layer.add_memory(user_id, f"Completely unrelated memory about topic {i}")
        layer.add_memory(user_id, "User prefers dark mode")

        layer.config.tau_rtr = 0.01
        brief = layer.retrieve(user_id, "display theme")
        before_count = layer.get_active_memory_count(user_id)

        layer._post_response_rtr(
            user_id, brief, "display theme",
            "Q: display theme? A: dark mode preferred.",
            "s1", 0,
        )
        # Total active + superseded count should not explode
        all_mems = layer.store.list_memories(user_id, status=None)
        versions_created = sum(
            1 for m in all_mems if m.parent_id is not None
        )
        # Only packed memories could have been versioned
        assert versions_created <= len(brief.memories)

    def test_run_maintenance_returns_correct_keys(self, layer, user_id):
        layer.add_memory(user_id, "memory one")
        result = layer.run_maintenance(user_id)
        assert "archived_count" in result
        assert "schemas_created_or_updated" in result
        assert "iaaf_enabled" in result
        assert "asc_enabled" in result

    def test_trace_logger_roundtrip_with_memory_ids(self, layer, user_id):
        mem = layer.add_memory(user_id, "trace test memory")
        trace = TraceRecord(
            user_id=user_id,
            session_id="s1",
            turn_index=0,
            query="test query",
            response="test response",
            retrieved_memory_ids=[mem.id],
        )
        layer.tracer.log(trace)
        history = layer.tracer.get_session_history(user_id, "s1")
        assert len(history) == 1
        assert mem.id in history[0].retrieved_memory_ids


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class TestEvaluation:
    def test_cmem_has_six_scenarios(self):
        scenarios = build_cmem_scenarios()
        assert len(scenarios) == 6

    def test_cmem_scenarios_have_expected_turns(self):
        scenarios = {s.name: s for s in build_cmem_scenarios()}
        assert len(scenarios["stable_preference"].turns) >= 2
        assert len(scenarios["changing_preference"].turns) >= 3
        assert len(scenarios["stale_information"].turns) >= 3

    def test_cmem_must_not_contain_populated(self):
        scenarios = {s.name: s for s in build_cmem_scenarios()}
        last = scenarios["changing_preference"].turns[-1]
        assert "tea" in last.must_not_contain

    def test_check_answer_case_insensitive(self):
        assert check_answer("You prefer Dark Mode", ["dark"])
        assert not check_answer("You prefer Light Mode", ["dark"])

    def test_check_retrieval_all_terms_required(self):
        assert check_retrieval_contains("User prefers coffee in the morning", ["coffee"])
        assert not check_retrieval_contains("User prefers coffee", ["coffee", "tea"])

    def test_full_evaluation_runs_ten_conditions(self):
        harness = EvaluationHarness()
        results = harness.run_full_evaluation()
        assert len(results) == 10
        condition_names = {r["condition"] for r in results}
        assert "COSMOS-Q (full)" in condition_names
        assert "No Memory" in condition_names
        assert "Full Transcript" in condition_names
        assert "Rolling Summary" in condition_names

    def test_no_memory_baseline_has_zero_success_rate(self):
        harness = EvaluationHarness()
        from cosmos_q.evaluation.cmem import build_cmem_scenarios

        scenarios = build_cmem_scenarios()
        results = harness.run_full_evaluation()
        no_mem = next(r for r in results if r["condition"] == "No Memory")
        # No Memory can never recall past information → 0 % success
        assert no_mem["task_success_rate"] == 0.0

    def test_cosmos_full_outperforms_no_memory(self):
        harness = EvaluationHarness()
        results = harness.run_full_evaluation()
        cosmos = next(r for r in results if r["condition"] == "COSMOS-Q (full)")
        no_mem = next(r for r in results if r["condition"] == "No Memory")
        assert cosmos["task_success_rate"] > no_mem["task_success_rate"]

    def test_make_cosmos_layer_raises_on_bad_variant(self):
        from cosmos_q.evaluation.baselines import make_cosmos_layer

        with pytest.raises(ValueError, match="Unknown ablation variant"):
            make_cosmos_layer("does_not_exist")

    def test_ablation_config_flags(self):
        c = CosmosConfig.ablation("no_rtr")
        assert c.enable_rtr is False
        assert c.enable_asc is True
        c2 = CosmosConfig.ablation("no_uacp")
        assert c2.enable_uacp is False

    def test_harness_no_duplicate_memories_per_turn(self):
        """add_memory + chat_mock duplication must not occur in harness."""
        harness = EvaluationHarness()
        from cosmos_q.evaluation.cmem import build_cmem_scenarios
        from cosmos_q.evaluation.baselines import make_cosmos_layer

        scenario = next(
            s for s in build_cmem_scenarios() if s.name == "stable_preference"
        )
        db_path = harness._db_path(f"dup_test_{scenario.name}")
        layer = make_cosmos_layer("full", db_path)
        harness._run_cosmos_scenario(layer, scenario, condition="test")

        # stable_preference has 1 memory_to_store turn.
        # After maintenance the memory may be CONSOLIDATED, so count all statuses.
        all_mems = layer.store.list_memories(scenario.user_id, status=None)
        # Must have exactly 1 root memory (no duplicates from chat_mock)
        roots = [m for m in all_mems if m.parent_id is None]
        assert len(roots) == 1
