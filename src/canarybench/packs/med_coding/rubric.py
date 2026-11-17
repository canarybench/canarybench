"""Deterministic grading rubric for `med-coding` composing rule-triage & wire-protocol."""

from __future__ import annotations

from decimal import Decimal

from canarybench.core.base import BaseEngine
from canarybench.core.schemas import CheckResult, GradeResult
from canarybench.engines import LedgerMathEngine, RuleTriageEngine, WireProtocolEngine
from canarybench.packs.med_coding.schemas import (
    MedCodingGroundTruth,
    MedCodingPrediction,
    MedCodingScenario,
)


class MedCodingGrader:
    """Zero-LLM deterministic grader for NCCI PTP, MUE, and X12-837P wire adjudication."""

    def grade(
        self,
        scenario: MedCodingScenario,
        prediction: MedCodingPrediction,
    ) -> GradeResult:
        gt: MedCodingGroundTruth = scenario.ground_truth
        tol = gt.amount_tolerance
        checks: list[CheckResult] = []
        hard_fail_reasons: list[str] = []

        def _record(res: CheckResult, *, hard_gate: bool = False) -> None:
            checks.append(res)
            if hard_gate and not res.passed:
                hard_fail_reasons.append(res.check_id)

        _record(
            RuleTriageEngine.check_enum_exact(
                "regime_exact",
                expected=gt.regime.value,
                actual=prediction.regime.value,
                weight=Decimal("0.05"),
            )
        )

        wire_ok = (
            prediction.claim_valid_wire is gt.claim_valid_wire
            and prediction.npi_valid_luhn is gt.npi_valid_luhn
        )
        _record(
            CheckResult(
                check_id="wire_and_npi_valid_exact",
                passed=wire_ok,
                weight=Decimal("0.15"),
                score=Decimal("0.15") if wire_ok else Decimal("0.00"),
                expected=f"wire={gt.claim_valid_wire},npi={gt.npi_valid_luhn}",
                actual=f"wire={prediction.claim_valid_wire},npi={prediction.npi_valid_luhn}",
            ),
            hard_gate=True,
        )

        exp_errs = ",".join(sorted(gt.validation_error_codes))
        act_errs = ",".join(sorted(prediction.validation_error_codes))
        _record(
            WireProtocolEngine.check_protocol_codes(
                "validation_error_codes_exact",
                expected_codes={"errors": exp_errs},
                actual_codes={"errors": act_errs},
                weight=Decimal("0.10"),
            )
        )

        _record(
            RuleTriageEngine.check_enum_exact(
                "claim_disposition_exact",
                expected=gt.claim_disposition,
                actual=prediction.claim_disposition,
                weight=Decimal("0.15"),
            ),
            hard_gate=True,
        )

        _record(
            LedgerMathEngine.check_decimal_exact(
                "submitted_charge_total_decimal",
                expected=gt.submitted_charge_total,
                actual=prediction.submitted_charge_total,
                weight=Decimal("0.05"),
                tolerance=tol,
            )
        )

        sum_lines = sum(
            (ln.allowed_amount for ln in prediction.line_adjudications), start=Decimal("0.00")
        )
        _record(
            LedgerMathEngine.check_totals_equation(
                "payable_total_decimal",
                expected_fields={"payable_total": gt.payable_total},
                actual_fields={"payable_total": prediction.payable_total},
                equation_ok=(prediction.payable_total == sum_lines),
                weight=Decimal("0.25"),
                tolerance=tol,
            ),
            hard_gate=True,
        )

        _record(
            LedgerMathEngine.check_line_items_exact(
                "line_adjudications_exact",
                expected={
                    str(ln.line_number): (
                        (ln.cpt_hcpcs, ln.line_status, ln.denial_reason_code, ln.payable_units),
                        (ln.allowed_amount,),
                    )
                    for ln in gt.line_adjudications
                },
                actual={
                    str(ln.line_number): (
                        (ln.cpt_hcpcs, ln.line_status, ln.denial_reason_code, ln.payable_units),
                        (ln.allowed_amount,),
                    )
                    for ln in prediction.line_adjudications
                },
                weight=Decimal("0.25"),
                tolerance=tol,
            ),
            hard_gate=True,
        )

        return BaseEngine.finalize_grade(
            scenario=scenario,
            checks=checks,
            hard_fail_reasons=hard_fail_reasons,
        )
