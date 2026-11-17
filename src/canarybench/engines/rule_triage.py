"""Rule-Triage engine: hierarchical classification, threshold gates, and exclusions."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from canarybench.core.base import BaseEngine, EngineMetadata
from canarybench.core.schemas import CheckResult, EngineId


class RuleTriageEngine(BaseEngine):
    """Deterministic checks for statutory rule trees, eligibility thresholds, and fallbacks."""

    metadata: ClassVar[EngineMetadata] = EngineMetadata(
        engine_id=EngineId.RULE_TRIAGE,
        version="0.1.0",
        display_name="Rule Triage Engine",
        description=(
            "Hierarchical regulatory classification, threshold boundary gating, and "
            "exclusion-cascade verification with hard-fail anti-gaming guards."
        ),
        failure_archetype="Hierarchical Classification & Exclusions",
        primitive_check_ids=(
            "enum_exact",
            "bool_gate",
            "legal_basis_exact",
            "exclusion_cascade",
        ),
    )

    def primitive_checks(self) -> tuple[str, ...]:
        return self.metadata.primitive_check_ids

    @staticmethod
    def check_enum_exact(
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

    @staticmethod
    def check_bool_gate(
        check_id: str,
        *,
        expected: bool,
        actual: bool,
        weight: Decimal,
        message: str | None = None,
    ) -> CheckResult:
        passed = actual is expected
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=str(expected),
            actual=str(actual),
            message=message,
        )

    @staticmethod
    def check_legal_basis_exact(
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

    @staticmethod
    def check_exclusion_cascade(
        check_id: str,
        *,
        primary_eligible: bool,
        expected_code: str,
        actual_code: str,
        weight: Decimal,
    ) -> CheckResult:
        passed = actual_code == expected_code
        msg: str | None = None
        if not passed and not primary_eligible:
            msg = f"Failed exclusion fallback to {expected_code!r}; got {actual_code!r}"
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=expected_code,
            actual=actual_code,
            message=msg,
        )
