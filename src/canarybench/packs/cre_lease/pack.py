"""CreLeasePack plugin implementation registering `cre-lease` via BasePack."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from canarybench.core.adapters import AgentAdapter
from canarybench.core.base import BasePack, PackMetadata
from canarybench.core.schemas import AgentInput, EngineId, GradeResult, PackId
from canarybench.packs.cre_lease.baseline import NaiveCreLeaseBaselineAdapter
from canarybench.packs.cre_lease.rubric import CreLeaseGrader
from canarybench.packs.cre_lease.schemas import (
    CreLeaseGroundTruth,
    CreLeasePrediction,
    CreLeaseScenario,
)


class CreLeasePack(BasePack[AgentInput, CreLeaseGroundTruth, CreLeasePrediction]):
    """Commercial Real Estate CAM reconciliation, gross-up, CPI cap & amendment pack."""

    metadata: ClassVar[PackMetadata] = PackMetadata(
        pack_id=PackId.CRE_LEASE,
        version="0.1.0",
        display_name="CRE Lease CAM Reconciliation & CPI Escalation",
        description=(
            "Deterministic commercial real estate lease reconciliation covering 95% occupancy "
            "variable-expense gross-up, base-year expense stops, pro-rata RSF shares, "
            "compounding CPI escalation caps, and executed lease-amendment overrides."
        ),
        supported_engines=(EngineId.LEDGER_MATH, EngineId.DOC_RECONCILE),
        supported_modalities=("pdf_clean", "pdf_ocr_noise", "context_override"),
        default_rubric_version="cre-lease-v1",
    )

    def __init__(self) -> None:
        self._grader = CreLeaseGrader()

    def prediction_schema(self) -> type[CreLeasePrediction]:
        return CreLeasePrediction

    def ground_truth_schema(self) -> type[CreLeaseGroundTruth]:
        return CreLeaseGroundTruth

    def default_dataset_path(self) -> Path:
        return Path(__file__).resolve().parent / "data" / "public_10.jsonl"

    def load_scenarios(
        self,
        dataset_path: Path | None = None,
        *,
        engine_id: EngineId | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CreLeaseScenario]:
        path = dataset_path or self.default_dataset_path()
        if not path.exists():
            raise FileNotFoundError(f"Dataset manifest not found: {path}")

        scenarios: list[CreLeaseScenario] = []
        for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped, parse_float=Decimal)
                scenario = CreLeaseScenario.model_validate(payload)
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
        scenario: CreLeaseScenario,
        prediction: CreLeasePrediction,
    ) -> GradeResult:
        return self._grader.grade(scenario, prediction)

    def baseline_adapter(self, name: str) -> AgentAdapter | None:
        if name == "naive":
            return NaiveCreLeaseBaselineAdapter()
        return None
