"""Deterministic grading rubric for `claims-adjudication` (ledger-math & rule-triage)."""

from __future__ import annotations

from decimal import Decimal

from canarybench.core.base import BaseEngine
from canarybench.core.schemas import CheckResult, GradeResult
from canarybench.engines import LedgerMathEngine, RuleTriageEngine
from canarybench.packs.claims_adjudication.schemas import (
    ClaimsAdjudicationGroundTruth,
    ClaimsAdjudicationPrediction,
    ClaimsAdjudicationScenario,
)


class ClaimsAdjudicationGrader:
    """Zero-LLM deterministic grader for P&C 5-tier claims payout waterfalls."""

    def grade(
        self,
        scenario: ClaimsAdjudicationScenario,
        prediction: ClaimsAdjudicationPrediction,
    ) -> GradeResult:
        gt: ClaimsAdjudicationGroundTruth = scenario.ground_truth
        tol = gt.amount_tolerance
        checks: list[CheckResult] = []
        hard_fail_reasons: list[str] = []

        def _record(res: CheckResult, *, hard_gate: bool = False) -> None:
            checks.append(res)
            if hard_gate and not res.passed:
                hard_fail_reasons.append(res.check_id)

        _record(
            RuleTriageEngine.check_enum_exact(
                "claim_status_exact",
                expected=gt.claim_status,
                actual=prediction.claim_status,
                weight=Decimal("0.15"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_bool_gate(
                "within_policy_period_exact",
                expected=gt.within_policy_period,
                actual=prediction.within_policy_period,
                weight=Decimal("0.10"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_bool_gate(
                "coinsurance_penalty_exact",
                expected=gt.coinsurance_penalty_applied,
                actual=prediction.coinsurance_penalty_applied,
                weight=Decimal("0.05"),
            )
        )

        _record(
            LedgerMathEngine.check_decimal_exact(
                "coinsurance_ratio_exact",
                expected=gt.coinsurance_ratio,
                actual=prediction.coinsurance_ratio,
                weight=Decimal("0.05"),
                tolerance=Decimal("0.000001"),
            )
        )

        _record(
            RuleTriageEngine.check_bool_gate(
                "endorsement_override_exact",
                expected=gt.endorsement_override_applied,
                actual=prediction.endorsement_override_applied,
                weight=Decimal("0.05"),
            )
        )

        waterfall_eq_ok = (
            prediction.post_deductible_loss
            == max(Decimal("0.00"), prediction.post_sublimit_loss - prediction.deductible_applied)
            or prediction.claim_status != "COVERED_PAYABLE"
        )
        _record(
            LedgerMathEngine.check_totals_equation(
                "waterfall_payout_decimal",
                expected_fields={
                    "post_sublimit_loss": gt.post_sublimit_loss,
                    "deductible_applied": gt.deductible_applied,
                    "post_deductible_loss": gt.post_deductible_loss,
                    "post_coinsurance_loss": gt.post_coinsurance_loss,
                    "initial_acv_payout": gt.initial_acv_payout,
                    "recoverable_depreciation_holdback": gt.recoverable_depreciation_holdback,
                    "final_total_payable": gt.final_total_payable,
                },
                actual_fields={
                    "post_sublimit_loss": prediction.post_sublimit_loss,
                    "deductible_applied": prediction.deductible_applied,
                    "post_deductible_loss": prediction.post_deductible_loss,
                    "post_coinsurance_loss": prediction.post_coinsurance_loss,
                    "initial_acv_payout": prediction.initial_acv_payout,
                    "recoverable_depreciation_holdback": (
                        prediction.recoverable_depreciation_holdback
                    ),
                    "final_total_payable": prediction.final_total_payable,
                },
                equation_ok=waterfall_eq_ok,
                weight=Decimal("0.50"),
                tolerance=tol,
            ),
            hard_gate=True,
        )

        _record(
            LedgerMathEngine.check_line_items_exact(
                "peril_buckets_match",
                expected={
                    b.bucket_id: (
                        (b.peril_code, b.covered),
                        (b.gross_rcv_loss, b.gross_acv_loss, b.capped_loss),
                    )
                    for b in gt.peril_buckets
                },
                actual={
                    b.bucket_id: (
                        (b.peril_code, b.covered),
                        (b.gross_rcv_loss, b.gross_acv_loss, b.capped_loss),
                    )
                    for b in prediction.peril_buckets
                },
                weight=Decimal("0.10"),
                tolerance=tol,
            )
        )

        return BaseEngine.finalize_grade(
            scenario=scenario,
            checks=checks,
            hard_fail_reasons=hard_fail_reasons,
        )
