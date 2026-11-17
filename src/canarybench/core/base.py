"""Abstract plugin contracts for canarybench failure-archetype engines and domain packs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict

from canarybench.core.schemas import (
    AgentInput,
    AgentPrediction,
    BenchReport,
    CheckResult,
    EngineId,
    GradeResult,
    GroundTruth,
    PackId,
    Scenario,
    round_half_up,
)

if TYPE_CHECKING:
    from canarybench.core.adapters import AgentAdapter


class EngineMetadata(BaseModel):
    """Immutable metadata describing one of the four horizontal failure-archetype engines."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_id: EngineId
    version: str
    display_name: str
    description: str
    failure_archetype: str
    primitive_check_ids: tuple[str, ...] = ()


class BaseEngine(ABC):
    """Reusable horizontal evaluation-engine contract shared across domain packs."""

    metadata: ClassVar[EngineMetadata]

    @abstractmethod
    def primitive_checks(self) -> tuple[str, ...]:
        """Return canonical primitive check identifiers provided by this engine."""

    @staticmethod
    def finalize_grade(
        *,
        scenario: Scenario[Any, Any],
        checks: Sequence[CheckResult],
        hard_fail_reasons: Sequence[str],
    ) -> GradeResult:
        """Compute deterministic ROUND_HALF_UP GradeResult with hard-fail zeroing."""
        raw_score = sum((c.score for c in checks), start=Decimal("0.00"))
        hard_fail = len(hard_fail_reasons) > 0
        final_score = Decimal("0.0000") if hard_fail else round_half_up(raw_score, 4)
        passed = not hard_fail and all(c.passed for c in checks)

        return GradeResult(
            scenario_id=scenario.scenario_id,
            pack_id=scenario.pack_id,
            engine_id=scenario.engine_id,
            passed=passed,
            score=final_score,
            hard_fail=hard_fail,
            hard_fail_reason=",".join(hard_fail_reasons) if hard_fail_reasons else None,
            checks=tuple(checks),
            trap_tags=scenario.ground_truth.trap_tags,
            difficulty_tier=scenario.ground_truth.difficulty_tier,
            modality=scenario.agent_input.modality,
        )


class PackMetadata(BaseModel):
    """Immutable metadata describing a vertical compliance/extraction domain pack."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pack_id: PackId
    version: str
    display_name: str
    description: str
    supported_engines: tuple[EngineId, ...]
    supported_modalities: tuple[str, ...] = ("ubl_xml", "pdf_clean", "context_override")
    default_rubric_version: str


class BasePack[InputT: AgentInput, TruthT: GroundTruth, PredT: AgentPrediction](ABC):
    """Plugin contract that every built-in or 3rd-party domain pack must implement."""

    metadata: ClassVar[PackMetadata]

    @abstractmethod
    def prediction_schema(self) -> type[PredT]:
        """Return the concrete Pydantic v2 prediction model class."""

    @abstractmethod
    def ground_truth_schema(self) -> type[TruthT]:
        """Return the concrete Pydantic v2 ground-truth model class."""

    @abstractmethod
    def default_dataset_path(self) -> Path:
        """Return the packaged default dataset manifest path for this pack."""

    @abstractmethod
    def load_scenarios(
        self,
        dataset_path: Path | None = None,
        *,
        engine_id: EngineId | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Scenario[InputT, TruthT]]:
        """Load and strictly validate scenarios from a JSONL manifest."""

    @abstractmethod
    def grade(
        self,
        scenario: Scenario[InputT, TruthT],
        prediction: PredT,
    ) -> GradeResult:
        """Deterministically grade a single prediction against ground truth."""

    def baseline_adapter(self, name: str) -> AgentAdapter | None:
        """Return an optional deterministic offline baseline adapter for this pack."""
        return None

    def validate_ground_truth_artifact(
        self,
        scenario: Scenario[InputT, TruthT],
        dataset_root: Path,
    ) -> list[str]:
        """Validate any pack-specific ground-truth wire artifact (e.g., EN 16931 UBL XML)."""
        return []

    def aggregate(
        self,
        results: Sequence[GradeResult],
        *,
        drop_id: str,
        canary_digest: str | None = None,
    ) -> BenchReport:
        """Aggregate scenario grade results into a deterministic BenchReport."""
        from canarybench.core.metrics import build_bench_report

        seen_engines = tuple(
            sorted({r.engine_id for r in results}, key=lambda e: e.value)
        ) or self.metadata.supported_engines
        return build_bench_report(
            pack_ids=(self.metadata.pack_id,),
            engine_ids=seen_engines,
            pack_versions={self.metadata.pack_id.value: self.metadata.version},
            drop_id=drop_id,
            canary_digest=canary_digest,
            results=results,
        )


SuiteMetadata = PackMetadata
BaseSuite = BasePack
