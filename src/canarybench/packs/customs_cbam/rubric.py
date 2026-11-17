"""Deterministic grading rubric for `customs-cbam` composing rule-triage & ledger-math."""

from __future__ import annotations

from decimal import Decimal

from canarybench.core.base import BaseEngine
from canarybench.core.schemas import CheckResult, GradeResult
from canarybench.engines import LedgerMathEngine, RuleTriageEngine
from canarybench.packs.customs_cbam.schemas import (
    CustomsCbamGroundTruth,
    CustomsCbamPrediction,
    CustomsCbamScenario,
)


class CustomsCbamGrader:
    """Zero-LLM deterministic grader for GRI classification, origin rules, and EU CBAM."""

    def grade(
        self,
        scenario: CustomsCbamScenario,
        prediction: CustomsCbamPrediction,
    ) -> GradeResult:
        gt: CustomsCbamGroundTruth = scenario.ground_truth
        tol = gt.amount_tolerance
        checks: list[CheckResult] = []
        hard_fail_reasons: list[str] = []

        def _record(res: CheckResult, *, hard_gate: bool = False) -> None:
            checks.append(res)
            if hard_gate and not res.passed:
                hard_fail_reasons.append(res.check_id)

        _record(
            RuleTriageEngine.check_enum_exact(
                "classified_hs6_exact",
                expected=gt.classified_hs6,
                actual=prediction.classified_hs6,
                weight=Decimal("0.15"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_enum_exact(
                "applied_gri_rule_exact",
                expected=gt.applied_gri_rule,
                actual=prediction.applied_gri_rule,
                weight=Decimal("0.10"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_bool_gate(
                "preferential_origin_exact",
                expected=gt.preferential_origin_eligible,
                actual=prediction.preferential_origin_eligible,
                weight=Decimal("0.10"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_enum_exact(
                "origin_rule_exact",
                expected=gt.origin_rule_applied,
                actual=prediction.origin_rule_applied,
                weight=Decimal("0.05"),
            )
        )

        _record(
            RuleTriageEngine.check_bool_gate(
                "cbam_de_minimis_exact",
                expected=gt.cbam_de_minimis_exempt,
                actual=prediction.cbam_de_minimis_exempt,
                weight=Decimal("0.05"),
            )
        )

        _record(
            LedgerMathEngine.check_decimal_exact(
                "non_originating_pct_exact",
                expected=gt.non_originating_pct,
                actual=prediction.non_originating_pct,
                weight=Decimal("0.05"),
                tolerance=Decimal("0.01"),
            )
        )

        _record(
            LedgerMathEngine.check_decimal_exact(
                "net_embedded_emissions_exact",
                expected=gt.net_embedded_emissions_tco2,
                actual=prediction.net_embedded_emissions_tco2,
                weight=Decimal("0.10"),
                tolerance=Decimal("0.001"),
            )
        )

        eq_ok = (
            prediction.total_border_charge_eur
            == prediction.customs_duty_eur + prediction.cbam_net_payable_eur
        )
        _record(
            LedgerMathEngine.check_totals_equation(
                "border_charges_decimal",
                expected_fields={
                    "applied_duty_rate_pct": gt.applied_duty_rate_pct,
                    "customs_duty_eur": gt.customs_duty_eur,
                    "gross_cbam_liability_eur": gt.gross_cbam_liability_eur,
                    "cbam_net_payable_eur": gt.cbam_net_payable_eur,
                    "total_border_charge_eur": gt.total_border_charge_eur,
                },
                actual_fields={
                    "applied_duty_rate_pct": prediction.applied_duty_rate_pct,
                    "customs_duty_eur": prediction.customs_duty_eur,
                    "gross_cbam_liability_eur": prediction.gross_cbam_liability_eur,
                    "cbam_net_payable_eur": prediction.cbam_net_payable_eur,
                    "total_border_charge_eur": prediction.total_border_charge_eur,
                },
                equation_ok=eq_ok,
                weight=Decimal("0.40"),
                tolerance=tol,
            ),
            hard_gate=True,
        )

        return BaseEngine.finalize_grade(
            scenario=scenario,
            checks=checks,
            hard_fail_reasons=hard_fail_reasons,
        )
