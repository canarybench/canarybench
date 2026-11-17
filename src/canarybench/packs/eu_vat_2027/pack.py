"""EuVat2027Pack plugin implementation registering `eu-vat-2027` via BasePack."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from canarybench.core.adapters import AgentAdapter
from canarybench.core.base import BasePack, PackMetadata
from canarybench.core.schemas import AgentInput, EngineId, GradeResult, PackId
from canarybench.packs.eu_vat_2027.baseline import NaiveVatBaselineAdapter
from canarybench.packs.eu_vat_2027.rubric import EuVatGrader
from canarybench.packs.eu_vat_2027.schemas import (
    EuVatGroundTruth,
    EuVatPrediction,
    EuVatScenario,
)
from canarybench.packs.eu_vat_2027.xml_validator import validate_en16931


class EuVat2027Pack(BasePack[AgentInput, EuVatGroundTruth, EuVatPrediction]):
    """Contamination-free EU VAT & EN 16931 e-invoicing compliance benchmark pack."""

    metadata: ClassVar[PackMetadata] = PackMetadata(
        pack_id=PackId.EU_VAT_2027,
        version="0.1.0",
        display_name="EU VAT & EN 16931 E-Invoicing (2027 ViDA / XRechnung / KSeF)",
        description=(
            "Deterministic cross-border EU VAT compliance pack covering Art. 141 "
            "triangulation, Art. 44/196 B2B services reverse charge, Art. 138 transport "
            "proof overrides, mixed-rate partial credit notes, and Dir. 2020/285 SME schemes."
        ),
        supported_engines=(
            EngineId.LEDGER_MATH,
            EngineId.DOC_RECONCILE,
            EngineId.RULE_TRIAGE,
            EngineId.WIRE_PROTOCOL,
        ),
        supported_modalities=(
            "ubl_xml",
            "pdf_clean",
            "pdf_fx",
            "pdf_ocr_noise",
            "context_override",
        ),
        default_rubric_version="eu-vat-2027-v1",
    )

    def __init__(self) -> None:
        self._grader = EuVatGrader()

    def prediction_schema(self) -> type[EuVatPrediction]:
        return EuVatPrediction

    def ground_truth_schema(self) -> type[EuVatGroundTruth]:
        return EuVatGroundTruth

    def default_dataset_path(self) -> Path:
        return Path(__file__).resolve().parent / "data" / "public_25.jsonl"

    def load_scenarios(
        self,
        dataset_path: Path | None = None,
        *,
        engine_id: EngineId | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[EuVatScenario]:
        path = dataset_path or self.default_dataset_path()
        if not path.exists():
            raise FileNotFoundError(f"Dataset manifest not found: {path}")

        scenarios: list[EuVatScenario] = []
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        for line_num, line in enumerate(raw_lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped, parse_float=Decimal)
                scenario = EuVatScenario.model_validate(payload)
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
        scenario: EuVatScenario,
        prediction: EuVatPrediction,
    ) -> GradeResult:
        return self._grader.grade(scenario, prediction)

    def baseline_adapter(self, name: str) -> AgentAdapter | None:
        if name == "naive":
            return NaiveVatBaselineAdapter()
        return None

    def validate_ground_truth_artifact(
        self,
        scenario: EuVatScenario,
        dataset_root: Path,
    ) -> list[str]:
        rel = scenario.ground_truth.ground_truth_ubl_rel_path
        if not rel:
            return ["No ground_truth_ubl_rel_path on this scenario."]
        xml_path = dataset_root / rel
        if not xml_path.exists():
            return [f"UBL XML file missing: {xml_path}"]
        return validate_en16931(xml_path.read_text(encoding="utf-8"))


EuVatSuite = EuVat2027Pack
