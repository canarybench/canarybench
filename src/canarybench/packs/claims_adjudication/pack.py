"""ClaimsAdjudicationPack plugin implementation registering `claims-adjudication` via BasePack."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from canarybench.core.adapters import AgentAdapter
from canarybench.core.base import BasePack, PackMetadata
from canarybench.core.schemas import AgentInput, EngineId, GradeResult, PackId
from canarybench.packs.claims_adjudication.baseline import NaiveClaimsBaselineAdapter
from canarybench.packs.claims_adjudication.rubric import ClaimsAdjudicationGrader
from canarybench.packs.claims_adjudication.schemas import (
    ClaimsAdjudicationGroundTruth,
    ClaimsAdjudicationPrediction,
    ClaimsAdjudicationScenario,
)


class ClaimsAdjudicationPack(
    BasePack[AgentInput, ClaimsAdjudicationGroundTruth, ClaimsAdjudicationPrediction]
):
    """P&C multi-tier claims adjudication waterfall benchmark pack."""

    metadata: ClassVar[PackMetadata] = PackMetadata(
        pack_id=PackId.CLAIMS_ADJUDICATION,
        version="0.1.0",
        display_name="P&C Claims Adjudication Waterfall",
        description=(
            "Deterministic Property & Casualty claim waterfall covering policy-period and "
            "retroactive cutoffs, excluded perils, overlapping peril sub-limits, fixed and "
            "% TIV deductibles, co-insurance penalties, and ACV vs RCV holdbacks."
        ),
        supported_engines=(EngineId.LEDGER_MATH, EngineId.RULE_TRIAGE),
        supported_modalities=("pdf_clean", "pdf_ocr_noise", "context_override"),
        default_rubric_version="claims-adjudication-v1",
    )

    def __init__(self) -> None:
        self._grader = ClaimsAdjudicationGrader()

    def prediction_schema(self) -> type[ClaimsAdjudicationPrediction]:
        return ClaimsAdjudicationPrediction

    def ground_truth_schema(self) -> type[ClaimsAdjudicationGroundTruth]:
        return ClaimsAdjudicationGroundTruth

    def default_dataset_path(self) -> Path:
        return Path(__file__).resolve().parent / "data" / "public_10.jsonl"

    def load_scenarios(
        self,
        dataset_path: Path | None = None,
        *,
        engine_id: EngineId | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ClaimsAdjudicationScenario]:
        path = dataset_path or self.default_dataset_path()
        if not path.exists():
            raise FileNotFoundError(f"Dataset manifest not found: {path}")

        scenarios: list[ClaimsAdjudicationScenario] = []
        for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped, parse_float=Decimal)
                scenario = ClaimsAdjudicationScenario.model_validate(payload)
            except Exception as exc:
                raise ValueError(f"{path}:{line_num}: invalid scenario JSON: {exc}") from exc
            if engine_id is not None and scenario.engine_id != engine_id:
                continue
            scenarios.append(scenario)

        sliced = scenarios[offset:]
        if limit is not None:
            sliced = sliced[:limit]
        return sliced

    def grade(
        self,
        scenario: ClaimsAdjudicationScenario,
        prediction: ClaimsAdjudicationPrediction,
    ) -> GradeResult:
        return self._grader.grade(scenario, prediction)

    def baseline_adapter(self, name: str) -> AgentAdapter | None:
        if name == "naive":
            return NaiveClaimsBaselineAdapter()
        return None
