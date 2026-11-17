"""CustomsCbamPack plugin implementation registering `customs-cbam` via BasePack."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from canarybench.core.adapters import AgentAdapter
from canarybench.core.base import BasePack, PackMetadata
from canarybench.core.schemas import AgentInput, EngineId, GradeResult, PackId
from canarybench.packs.customs_cbam.baseline import NaiveCustomsCbamBaselineAdapter
from canarybench.packs.customs_cbam.rubric import CustomsCbamGrader
from canarybench.packs.customs_cbam.schemas import (
    CustomsCbamGroundTruth,
    CustomsCbamPrediction,
    CustomsCbamScenario,
)


class CustomsCbamPack(BasePack[AgentInput, CustomsCbamGroundTruth, CustomsCbamPrediction]):
    """GRI 1-6 classification, FTA preferential origin, and EU CBAM compliance pack."""

    metadata: ClassVar[PackMetadata] = PackMetadata(
        pack_id=PackId.CUSTOMS_CBAM,
        version="0.1.0",
        display_name="Customs GRI Classification, FTA Origin & EU CBAM",
        description=(
            "Deterministic trade compliance pack covering GRI 1-6 / 3(b) / 3(c) BOM "
            "classification, CTH/MaxNOM preferential origin rules, and EU CBAM embedded "
            "emissions, free allocation benchmarks, foreign carbon credits, and thresholds."
        ),
        supported_engines=(EngineId.RULE_TRIAGE, EngineId.LEDGER_MATH),
        supported_modalities=("pdf_clean", "pdf_ocr_noise", "json_wire", "context_override"),
        default_rubric_version="customs-cbam-v1",
    )

    def __init__(self) -> None:
        self._grader = CustomsCbamGrader()

    def prediction_schema(self) -> type[CustomsCbamPrediction]:
        return CustomsCbamPrediction

    def ground_truth_schema(self) -> type[CustomsCbamGroundTruth]:
        return CustomsCbamGroundTruth

    def default_dataset_path(self) -> Path:
        return Path(__file__).resolve().parent / "data" / "public_10.jsonl"

    def load_scenarios(
        self,
        dataset_path: Path | None = None,
        *,
        engine_id: EngineId | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CustomsCbamScenario]:
        path = dataset_path or self.default_dataset_path()
        if not path.exists():
            raise FileNotFoundError(f"Dataset manifest not found: {path}")

        scenarios: list[CustomsCbamScenario] = []
        for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped, parse_float=Decimal)
                scenario = CustomsCbamScenario.model_validate(payload)
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
        scenario: CustomsCbamScenario,
        prediction: CustomsCbamPrediction,
    ) -> GradeResult:
        return self._grader.grade(scenario, prediction)

    def baseline_adapter(self, name: str) -> AgentAdapter | None:
        if name == "naive":
            return NaiveCustomsCbamBaselineAdapter()
        return None
