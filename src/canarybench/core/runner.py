"""Deterministic single-pack and multi-pack benchmark execution engine."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from canarybench.core.adapters import AgentAdapter
from canarybench.core.base import BasePack
from canarybench.core.metrics import build_bench_report
from canarybench.core.schemas import (
    AgentInput,
    AgentPrediction,
    BenchReport,
    EngineId,
    GradeResult,
    GroundTruth,
    Scenario,
)


class BenchmarkRunner:
    """Runs one or more BasePacks against an AgentAdapter (or per-pack resolver)."""

    def __init__(
        self,
        packs: BasePack[Any, Any, Any] | Sequence[BasePack[Any, Any, Any]],
        adapter: AgentAdapter | None = None,
        *,
        adapter_resolver: Callable[[BasePack[Any, Any, Any]], AgentAdapter] | None = None,
    ) -> None:
        self.packs: tuple[BasePack[Any, Any, Any], ...] = (
            (packs,) if isinstance(packs, BasePack) else tuple(packs)
        )
        if not self.packs:
            raise ValueError("BenchmarkRunner requires at least one BasePack")
        if (adapter is None) == (adapter_resolver is None):
            raise ValueError("Specify exactly one of 'adapter' or 'adapter_resolver'")
        self.adapter = adapter
        self.adapter_resolver = adapter_resolver

    def _resolve_adapter(self, pack: BasePack[Any, Any, Any]) -> AgentAdapter:
        if self.adapter is not None:
            return self.adapter
        assert self.adapter_resolver is not None
        return self.adapter_resolver(pack)

    def run(
        self,
        *,
        engine_id: EngineId | None = None,
        dataset_path: Path | None = None,
        limit: int | None = None,
        offset: int = 0,
        save_predictions_path: Path | None = None,
        progress_callback: Callable[[int, int, GradeResult], None] | None = None,
    ) -> BenchReport:
        if len(self.packs) > 1 and dataset_path is not None:
            raise ValueError("--dataset cannot be combined with a multi-pack run")

        work_items: list[
            tuple[BasePack[Any, Any, Any], AgentAdapter, type[AgentPrediction], Scenario[Any, Any]]
        ] = []
        drop_ids: list[str] = []

        if len(self.packs) == 1:
            pack = self.packs[0]
            resolved_path = dataset_path or pack.default_dataset_path()
            scenarios = pack.load_scenarios(
                resolved_path,
                engine_id=engine_id,
                limit=limit,
                offset=offset,
            )
            pack_adapter = self._resolve_adapter(pack)
            pred_schema = pack.prediction_schema()
            for sc in scenarios:
                work_items.append((pack, pack_adapter, pred_schema, sc))
                drop_ids.append(sc.drop_id)
        else:
            combined: list[
                tuple[
                    BasePack[Any, Any, Any],
                    AgentAdapter,
                    type[AgentPrediction],
                    Scenario[Any, Any],
                ]
            ] = []
            for pack in self.packs:
                resolved_path = pack.default_dataset_path()
                scenarios = pack.load_scenarios(resolved_path, engine_id=engine_id)
                pack_adapter = self._resolve_adapter(pack)
                pred_schema = pack.prediction_schema()
                for sc in scenarios:
                    combined.append((pack, pack_adapter, pred_schema, sc))
            sliced = combined[offset:]
            if limit is not None:
                sliced = sliced[:limit]
            work_items.extend(sliced)
            drop_ids.extend(item[3].drop_id for item in sliced)

        results: list[GradeResult] = []
        saved_records: list[str] = []
        total = len(work_items)

        for idx, (pack, pack_adapter, pred_schema, scenario) in enumerate(work_items, start=1):
            grade_result, prediction = self._evaluate_one(
                pack=pack,
                adapter=pack_adapter,
                scenario=scenario,
                pred_schema=pred_schema,
            )
            results.append(grade_result)
            if prediction is not None and save_predictions_path is not None:
                saved_records.append(prediction.model_dump_json())
            if progress_callback is not None:
                progress_callback(idx, total, grade_result)

        if save_predictions_path is not None:
            save_predictions_path.parent.mkdir(parents=True, exist_ok=True)
            save_predictions_path.write_text(
                "\n".join(saved_records) + ("\n" if saved_records else ""),
                encoding="utf-8",
            )

        unique_drops = list(dict.fromkeys(drop_ids))
        if not unique_drops:
            drop_id = "empty"
        elif len(unique_drops) == 1:
            drop_id = unique_drops[0]
        else:
            drop_id = "multi-drop"

        pack_ids = tuple(p.metadata.pack_id for p in self.packs)
        pack_versions = {p.metadata.pack_id.value: p.metadata.version for p in self.packs}
        if engine_id is not None:
            engine_ids: tuple[EngineId, ...] = (engine_id,)
        else:
            seen_engines = {r.engine_id for r in results}
            if seen_engines:
                engine_ids = tuple(sorted(seen_engines, key=lambda e: e.value))
            else:
                all_supported = {
                    e for p in self.packs for e in p.metadata.supported_engines
                }
                engine_ids = tuple(sorted(all_supported, key=lambda e: e.value))

        return build_bench_report(
            pack_ids=pack_ids,
            engine_ids=engine_ids,
            pack_versions=pack_versions,
            drop_id=drop_id,
            canary_digest=None,
            results=results,
        )

    @staticmethod
    def _evaluate_one(
        *,
        pack: BasePack[Any, Any, Any],
        adapter: AgentAdapter,
        scenario: Scenario[AgentInput, GroundTruth],
        pred_schema: type[AgentPrediction],
    ) -> tuple[GradeResult, AgentPrediction | None]:
        try:
            prediction = adapter.predict(scenario.agent_input, pred_schema)
            validated = pred_schema.model_validate(
                json.loads(prediction.model_dump_json(), parse_float=Decimal)
            )
        except (ValidationError, Exception) as exc:
            return (
                GradeResult(
                    scenario_id=scenario.scenario_id,
                    pack_id=scenario.pack_id,
                    engine_id=scenario.engine_id,
                    passed=False,
                    score=Decimal("0.0000"),
                    hard_fail=True,
                    hard_fail_reason=f"prediction_error: {type(exc).__name__}",
                    trap_tags=scenario.ground_truth.trap_tags,
                    difficulty_tier=scenario.ground_truth.difficulty_tier,
                    modality=scenario.agent_input.modality,
                    error=str(exc),
                ),
                None,
            )

        grade_result = pack.grade(scenario, validated)
        return grade_result, validated
