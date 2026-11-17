"""MedCodingPack plugin implementation registering `med-coding` via BasePack."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from canarybench.core.adapters import AgentAdapter
from canarybench.core.base import BasePack, PackMetadata
from canarybench.core.schemas import AgentInput, EngineId, GradeResult, PackId
from canarybench.packs.med_coding.baseline import NaiveMedCodingBaselineAdapter
from canarybench.packs.med_coding.rubric import MedCodingGrader
from canarybench.packs.med_coding.schemas import (
    MedCodingGroundTruth,
    MedCodingPrediction,
    MedCodingScenario,
)
from canarybench.packs.med_coding.wire_validator import validate_claim_wire


class MedCodingPack(BasePack[AgentInput, MedCodingGroundTruth, MedCodingPrediction]):
    """CMS NCCI PTP bundling, MUE limits, and X12-837P wire-protocol validation pack."""

    metadata: ClassVar[PackMetadata] = PackMetadata(
        pack_id=PackId.MED_CODING,
        version="0.1.0",
        display_name="Medical Coding NCCI PTP, MUE & X12-837P Wire Protocol",
        description=(
            "Deterministic medical claim adjudication covering CMS NCCI Column 1/Column 2 "
            "bundling (CCMI 0 vs 1 + -25/-59/XS/XU modifiers), MUE unit limits, CMS NPI "
            "Luhn validation, ICD-10-CM pointers, and canonical X12-837P JSON/XML schemas."
        ),
        supported_engines=(EngineId.RULE_TRIAGE, EngineId.WIRE_PROTOCOL),
        supported_modalities=("json_wire", "xml_wire", "context_override"),
        default_rubric_version="med-coding-v1",
    )

    def __init__(self) -> None:
        self._grader = MedCodingGrader()

    def prediction_schema(self) -> type[MedCodingPrediction]:
        return MedCodingPrediction

    def ground_truth_schema(self) -> type[MedCodingGroundTruth]:
        return MedCodingGroundTruth

    def default_dataset_path(self) -> Path:
        return Path(__file__).resolve().parent / "data" / "public_10.jsonl"

    def load_scenarios(
        self,
        dataset_path: Path | None = None,
        *,
        engine_id: EngineId | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MedCodingScenario]:
        path = dataset_path or self.default_dataset_path()
        if not path.exists():
            raise FileNotFoundError(f"Dataset manifest not found: {path}")

        scenarios: list[MedCodingScenario] = []
        for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped, parse_float=Decimal)
                scenario = MedCodingScenario.model_validate(payload)
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
        scenario: MedCodingScenario,
        prediction: MedCodingPrediction,
    ) -> GradeResult:
        return self._grader.grade(scenario, prediction)

    def baseline_adapter(self, name: str) -> AgentAdapter | None:
        if name == "naive":
            return NaiveMedCodingBaselineAdapter()
        return None

    def validate_ground_truth_artifact(
        self,
        scenario: MedCodingScenario,
        dataset_root: Path,
    ) -> list[str]:
        if not scenario.ground_truth.claim_valid_wire:
            return []
        art = scenario.agent_input.artifacts[0]
        raw_path = dataset_root / art.rel_path
        if not raw_path.exists():
            return [f"Missing claim wire artifact: {raw_path}"]
        _, errs = validate_claim_wire(
            raw_path.read_text(encoding="utf-8"),
            scenario.ground_truth.wire_format,
        )
        return list(errs)
