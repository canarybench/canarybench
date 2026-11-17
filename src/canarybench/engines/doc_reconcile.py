"""Doc-Reconcile engine: multi-source contradiction and OCR normalization primitives."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import ClassVar

from canarybench.core.base import BaseEngine, EngineMetadata
from canarybench.core.schemas import CheckResult, EngineId


class DocReconcileEngine(BaseEngine):
    """Deterministic checks for evidence precedence and OCR/formatting noise resilience."""

    metadata: ClassVar[EngineMetadata] = EngineMetadata(
        engine_id=EngineId.DOC_RECONCILE,
        version="0.1.0",
        display_name="Document Reconciliation Engine",
        description=(
            "Multi-source contradiction resolution verifying authoritative attachments "
            "supersede draft headers, plus zero-width/NBSP OCR-normalized identifier matching."
        ),
        failure_archetype="Multi-Source Contradiction Traps",
        primitive_check_ids=(
            "authoritative_field",
            "evidence_precedence",
            "ocr_normalized_id",
        ),
    )

    def primitive_checks(self) -> tuple[str, ...]:
        return self.metadata.primitive_check_ids

    @staticmethod
    def normalize_ocr_token(value: str | None) -> str | None:
        if value is None:
            return None
        return (
            value.replace("\u200b", "")
            .replace("\u00ad", "")
            .replace("\u00a0", " ")
            .strip()
        )

    @staticmethod
    def check_authoritative_field(
        check_id: str,
        *,
        expected: str,
        actual: str,
        weight: Decimal,
        distractor_values: Sequence[str] = (),
    ) -> CheckResult:
        passed = actual == expected
        msg: str | None = None
        if not passed and actual in distractor_values:
            msg = f"Fell for non-authoritative distractor value {actual!r}"
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=expected,
            actual=actual,
            message=msg,
        )

    @staticmethod
    def check_evidence_precedence(
        check_id: str,
        *,
        expected: str,
        actual: str,
        weight: Decimal,
        message: str | None = None,
    ) -> CheckResult:
        passed = actual == expected
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=expected,
            actual=actual,
            message=message,
        )

    @classmethod
    def check_ocr_normalized_id(
        cls,
        check_id: str,
        *,
        expected_id: str | None,
        actual_id: str | None,
        weight: Decimal,
        message: str | None = None,
    ) -> CheckResult:
        exp_norm = cls.normalize_ocr_token(expected_id)
        act_norm = cls.normalize_ocr_token(actual_id)
        passed = exp_norm == act_norm
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=exp_norm,
            actual=act_norm,
            message=message,
        )
