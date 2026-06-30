"""Evaluation harness running C-MEM scenarios across baselines and ablations."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cosmos_q.config import CosmosConfig
from cosmos_q.evaluation.baselines import BaselineRetriever, make_cosmos_layer
from cosmos_q.evaluation.cmem import BenchmarkScenario, BenchmarkTurn, build_cmem_scenarios
from cosmos_q.evaluation.metrics import (
    EvalReport,
    EvalResult,
    check_retrieval_contains,
    check_stale_retrieval,
)
from cosmos_q.embeddings import EmbeddingService
from cosmos_q.memory_layer import CosmosMemoryLayer
from cosmos_q.models import MemoryBrief
from cosmos_q.store.memory_store import MemoryStore


class EvaluationHarness:
    """Runs C-MEM scenarios against COSMOS-Q and baselines."""

    def __init__(self, db_dir: str | None = None):
        self.db_dir = db_dir or tempfile.mkdtemp()

    def _db_path(self, name: str) -> str:
        return str(Path(self.db_dir) / f"{name}.db")

    # ------------------------------------------------------------------ #
    # COSMOS-Q variants

    def run_scenario_on_cosmos(
        self,
        scenario: BenchmarkScenario,
        variant: str = "full",
    ) -> EvalReport:
        db_path = self._db_path(f"cosmos_{variant}_{scenario.name}")
        layer = make_cosmos_layer(variant, db_path)
        return self._run_cosmos_scenario(layer, scenario, condition=f"COSMOS-Q ({variant})")

    def _run_cosmos_scenario(
        self,
        layer: CosmosMemoryLayer,
        scenario: BenchmarkScenario,
        condition: str,
    ) -> EvalReport:
        report = EvalReport(condition=condition)

        for turn in scenario.turns:
            # Store a memory if specified — use add_memory only (no chat_mock),
            # avoiding duplicate episodic writes.
            if turn.memory_to_store:
                layer.add_memory(
                    scenario.user_id,
                    turn.memory_to_store,
                    session_id=turn.session_id,
                    turn_index=turn.turn_index,
                )

            if turn.expected_answer_contains or turn.must_not_contain:
                brief = layer.retrieve(scenario.user_id, turn.query)
                result = self._evaluate_turn(scenario, turn, brief, layer)
                report.results.append(result)

        # Run maintenance after all turns (models inter-session behavior)
        layer.run_maintenance(scenario.user_id)
        return report

    # ------------------------------------------------------------------ #
    # Baseline variants

    def run_scenario_on_baseline(
        self,
        scenario: BenchmarkScenario,
        baseline: str,
    ) -> EvalReport:
        db_path = self._db_path(f"baseline_{baseline}_{scenario.name}")
        config = CosmosConfig(db_path=db_path)
        store = MemoryStore(config)
        embedder = EmbeddingService(config)
        retriever = BaselineRetriever(store, embedder, config)

        # Populate store directly — no chat_mock to avoid duplicate memories
        _layer = CosmosMemoryLayer(config)
        report = EvalReport(condition=baseline)

        for turn in scenario.turns:
            if turn.memory_to_store:
                _layer.add_memory(
                    scenario.user_id,
                    turn.memory_to_store,
                    session_id=turn.session_id,
                    turn_index=turn.turn_index,
                )

            if turn.expected_answer_contains or turn.must_not_contain:
                brief = self._baseline_retrieve(
                    retriever, baseline, scenario, turn
                )
                result = self._evaluate_turn(scenario, turn, brief, _layer)
                report.results.append(result)

        return report

    def _baseline_retrieve(
        self,
        retriever: BaselineRetriever,
        baseline: str,
        scenario: BenchmarkScenario,
        turn: BenchmarkTurn,
    ) -> MemoryBrief:
        uid = scenario.user_id
        q = turn.query
        if baseline == "no_memory":
            return retriever.no_memory(q)
        if baseline == "full_transcript":
            return retriever.full_transcript(uid, turn.session_id, q)
        if baseline == "rolling_summary":
            return retriever.rolling_summary(uid, q)
        if baseline == "naive_rag":
            return retriever.naive_rag(uid, q)
        if baseline == "recency":
            return retriever.recency_retrieval(uid, q)
        raise ValueError(f"Unknown baseline: {baseline!r}")

    # ------------------------------------------------------------------ #
    # Shared evaluation logic

    def _evaluate_turn(
        self,
        scenario: BenchmarkScenario,
        turn: BenchmarkTurn,
        brief: MemoryBrief,
        layer: CosmosMemoryLayer,
    ) -> EvalResult:
        brief_lower = brief.text.lower()

        contains_ok = check_retrieval_contains(
            brief_lower, turn.expected_answer_contains
        )
        must_not_ok = not check_stale_retrieval(
            brief_lower, turn.must_not_contain
        )
        success = contains_ok and must_not_ok

        stale_terms = self._stale_terms(scenario)
        stale = check_stale_retrieval(brief_lower, stale_terms) if stale_terms else False

        return EvalResult(
            scenario=scenario.name,
            category=turn.category,
            success=success,
            retrieved_tokens=brief.total_tokens,
            active_memories=layer.get_active_memory_count(scenario.user_id),
            stale_retrieved=stale,
            details=brief.text[:200],
        )

    def _stale_terms(self, scenario: BenchmarkScenario) -> list[str]:
        mapping = {
            "changing_preference": ["tea"],
            "stale_information": ["acme"],
            "contradictory_update": ["march"],
        }
        return mapping.get(scenario.name, [])

    # ------------------------------------------------------------------ #
    # Full evaluation

    def run_full_evaluation(self) -> list[dict]:
        scenarios = build_cmem_scenarios()
        summaries: list[dict] = []

        conditions: list[tuple[str, object]] = [
            ("COSMOS-Q (full)",  lambda s: self.run_scenario_on_cosmos(s, "full")),
            ("COSMOS-Q (-RTR)",  lambda s: self.run_scenario_on_cosmos(s, "no_rtr")),
            ("COSMOS-Q (-ASC)",  lambda s: self.run_scenario_on_cosmos(s, "no_asc")),
            ("COSMOS-Q (-IAAF)", lambda s: self.run_scenario_on_cosmos(s, "no_iaaf")),
            ("COSMOS-Q (-UACP)", lambda s: self.run_scenario_on_cosmos(s, "no_uacp")),
            ("No Memory",        lambda s: self.run_scenario_on_baseline(s, "no_memory")),
            ("Naive RAG",        lambda s: self.run_scenario_on_baseline(s, "naive_rag")),
            ("Recency",          lambda s: self.run_scenario_on_baseline(s, "recency")),
            ("Full Transcript",  lambda s: self.run_scenario_on_baseline(s, "full_transcript")),
            ("Rolling Summary",  lambda s: self.run_scenario_on_baseline(s, "rolling_summary")),
        ]

        for condition_name, runner in conditions:
            merged = EvalReport(condition=condition_name)
            for scenario in scenarios:
                report = runner(scenario)
                merged.results.extend(report.results)
            summaries.append(merged.summary())

        return summaries
