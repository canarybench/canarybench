"""Ledger-Math engine: stateful financial, multi-rate bucket, and FX arithmetic primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, ClassVar

from canarybench.core.base import BaseEngine, EngineMetadata
from canarybench.core.schemas import CheckResult, EngineId


class LedgerMathEngine(BaseEngine):
    """Deterministic exact-Decimal arithmetic and ledger reconciliation checks."""

    metadata: ClassVar[EngineMetadata] = EngineMetadata(
        engine_id=EngineId.LEDGER_MATH,
        version="0.1.0",
        display_name="Ledger Math Engine",
        description=(
            "Stateful financial, tax-bucket, carry-forward, penny-rounding, and FX "
            "arithmetic verification using strict Decimal ROUND_HALF_UP semantics."
        ),
        failure_archetype="Stateful Financial & Tax Arithmetic",
        primitive_check_ids=(
            "decimal_exact",
            "totals_equation",
            "bucket_reconciliation",
            "line_items_exact",
            "fx_conversion",
        ),
    )

    def primitive_checks(self) -> tuple[str, ...]:
        return self.metadata.primitive_check_ids

    @staticmethod
    def within_tolerance(expected: Decimal, actual: Decimal, tolerance: Decimal) -> bool:
        return abs(expected - actual) <= tolerance

    @classmethod
    def check_decimal_exact(
        cls,
        check_id: str,
        *,
        expected: Decimal,
        actual: Decimal,
        weight: Decimal,
        tolerance: Decimal = Decimal("0.00"),
        message: str | None = None,
    ) -> CheckResult:
        passed = cls.within_tolerance(expected, actual, tolerance)
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=str(expected),
            actual=str(actual),
            message=message,
        )

    @classmethod
    def check_totals_equation(
        cls,
        check_id: str,
        *,
        expected_fields: Mapping[str, Decimal],
        actual_fields: Mapping[str, Decimal],
        equation_ok: bool,
        weight: Decimal,
        tolerance: Decimal = Decimal("0.00"),
        message: str | None = None,
    ) -> CheckResult:
        fields_match = set(expected_fields.keys()) == set(actual_fields.keys()) and all(
            cls.within_tolerance(expected_fields[k], actual_fields[k], tolerance)
            for k in expected_fields
        )
        passed = fields_match and equation_ok
        exp_str = ",".join(f"{k}={v}" for k, v in expected_fields.items())
        act_str = ",".join(f"{k}={v}" for k, v in actual_fields.items())
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=exp_str,
            actual=act_str,
            message=message,
        )

    @classmethod
    def check_bucket_reconciliation(
        cls,
        check_id: str,
        *,
        expected: Sequence[tuple[tuple[Any, ...], tuple[Decimal, ...]]],
        actual: Sequence[tuple[tuple[Any, ...], tuple[Decimal, ...]]],
        weight: Decimal,
        tolerance: Decimal = Decimal("0.00"),
        message: str | None = None,
    ) -> CheckResult:
        exp_sorted = sorted(expected, key=lambda item: item[0])
        act_sorted = sorted(actual, key=lambda item: item[0])
        passed = len(exp_sorted) == len(act_sorted) and all(
            exp_key == act_key
            and len(exp_vals) == len(act_vals)
            and all(
                cls.within_tolerance(ev, av, tolerance)
                for ev, av in zip(exp_vals, act_vals, strict=True)
            )
            for (exp_key, exp_vals), (act_key, act_vals) in zip(
                exp_sorted, act_sorted, strict=True
            )
        )
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=f"{len(exp_sorted)} buckets",
            actual=f"{len(act_sorted)} buckets",
            message=message,
        )

    @classmethod
    def check_line_items_exact(
        cls,
        check_id: str,
        *,
        expected: Mapping[str, tuple[tuple[Any, ...], tuple[Decimal, ...]]],
        actual: Mapping[str, tuple[tuple[Any, ...], tuple[Decimal, ...]]],
        weight: Decimal,
        tolerance: Decimal = Decimal("0.00"),
        message: str | None = None,
    ) -> CheckResult:
        passed = set(expected.keys()) == set(actual.keys()) and all(
            expected[lid][0] == actual[lid][0]
            and len(expected[lid][1]) == len(actual[lid][1])
            and all(
                cls.within_tolerance(ev, av, tolerance)
                for ev, av in zip(expected[lid][1], actual[lid][1], strict=True)
            )
            for lid in expected
        )
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=f"{len(expected)} lines",
            actual=f"{len(actual)} lines",
            message=message,
        )

    @classmethod
    def check_fx_conversion(
        cls,
        check_id: str,
        *,
        doc_ccy: str,
        actual_doc_ccy: str,
        tax_ccy: str | None,
        actual_tax_ccy: str | None,
        expected_rate: Decimal | None,
        actual_rate: Decimal | None,
        weight: Decimal,
        rate_tolerance: Decimal = Decimal("0.0001"),
        message: str | None = None,
    ) -> CheckResult:
        rate_ok = (expected_rate is None and actual_rate is None) or (
            expected_rate is not None
            and actual_rate is not None
            and cls.within_tolerance(expected_rate, actual_rate, rate_tolerance)
        )
        passed = doc_ccy == actual_doc_ccy and tax_ccy == actual_tax_ccy and rate_ok
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=f"{doc_ccy}/{tax_ccy}/{expected_rate}",
            actual=f"{actual_doc_ccy}/{actual_tax_ccy}/{actual_rate}",
            message=message,
        )
