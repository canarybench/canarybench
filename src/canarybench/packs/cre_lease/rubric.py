"""Deterministic grading rubric for `cre-lease` composing ledger-math & doc-reconcile."""

from __future__ import annotations

from decimal import Decimal

from canarybench.core.base import BaseEngine
from canarybench.core.schemas import CheckResult, GradeResult
from canarybench.engines import DocReconcileEngine, LedgerMathEngine, RuleTriageEngine
from canarybench.packs.cre_lease.schemas import (
    CreLeaseGroundTruth,
    CreLeasePrediction,
    CreLeaseScenario,
)


class CreLeaseGrader:
    """Zero-LLM deterministic grader for CRE CAM reconciliation & CPI escalation."""

    def grade(
        self,
        scenario: CreLeaseScenario,
        prediction: CreLeasePrediction,
    ) -> GradeResult:
        gt: CreLeaseGroundTruth = scenario.ground_truth
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

        _record(
            RuleTriageEngine.check_bool_gate(
                "gross_up_applied_exact",
                expected=gt.gross_up_applied,
                actual=prediction.gross_up_applied,
                weight=Decimal("0.10"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_bool_gate(
                "amendment_override_exact",
                expected=gt.amendment_override_applied,
                actual=prediction.amendment_override_applied,
                weight=Decimal("0.10"),
            ),
            hard_gate=True,
        )

        _record(
            DocReconcileEngine.check_authoritative_field(
                "effective_base_year_exact",
                expected=str(gt.effective_base_year),
                actual=str(prediction.effective_base_year),
                weight=Decimal("0.05"),
                distractor_values=(
                    (str(gt.initial_base_year),)
                    if gt.effective_base_year != gt.initial_base_year
                    else ()
                ),
            )
        )

        _record(
            LedgerMathEngine.check_decimal_exact(
                "pro_rata_share_exact",
                expected=gt.pro_rata_share_pct,
                actual=prediction.pro_rata_share_pct,
                weight=Decimal("0.10"),
                tolerance=Decimal("0.0001"),
            )
        )

        cam_eq_ok = (
            prediction.total_building_opex
            == prediction.grossed_up_variable_opex
            + prediction.eligible_fixed_opex
            + prediction.included_capex_total
            + prediction.mgmt_fee_allowed
        ) and (
            prediction.excess_opex_over_stop
            == max(
                Decimal("0.00"), prediction.total_building_opex - prediction.base_year_stop_amount
            )
        )
        _record(
            LedgerMathEngine.check_totals_equation(
                "cam_totals_decimal",
                expected_fields={
                    "grossed_up_variable_opex": gt.grossed_up_variable_opex,
                    "eligible_fixed_opex": gt.eligible_fixed_opex,
                    "included_capex_total": gt.included_capex_total,
                    "mgmt_fee_allowed": gt.mgmt_fee_allowed,
                    "excluded_capex_total": gt.excluded_capex_total,
                    "total_building_opex": gt.total_building_opex,
                    "base_year_stop_amount": gt.base_year_stop_amount,
                    "excess_opex_over_stop": gt.excess_opex_over_stop,
                    "tenant_cam_payable": gt.tenant_cam_payable,
                },
                actual_fields={
                    "grossed_up_variable_opex": prediction.grossed_up_variable_opex,
                    "eligible_fixed_opex": prediction.eligible_fixed_opex,
                    "included_capex_total": prediction.included_capex_total,
                    "mgmt_fee_allowed": prediction.mgmt_fee_allowed,
                    "excluded_capex_total": prediction.excluded_capex_total,
                    "total_building_opex": prediction.total_building_opex,
                    "base_year_stop_amount": prediction.base_year_stop_amount,
                    "excess_opex_over_stop": prediction.excess_opex_over_stop,
                    "tenant_cam_payable": prediction.tenant_cam_payable,
                },
                equation_ok=cam_eq_ok,
                weight=Decimal("0.25"),
                tolerance=tol,
            ),
            hard_gate=True,
        )

        rent_eq_ok = (
            prediction.total_annual_tenant_obligation
            == prediction.tenant_cam_payable + prediction.escalated_base_rent_annual
        )
        _record(
            LedgerMathEngine.check_totals_equation(
                "cpi_and_obligation_decimal",
                expected_fields={
                    "escalated_base_rent_annual": gt.escalated_base_rent_annual,
                    "total_annual_tenant_obligation": gt.total_annual_tenant_obligation,
                },
                actual_fields={
                    "escalated_base_rent_annual": prediction.escalated_base_rent_annual,
                    "total_annual_tenant_obligation": prediction.total_annual_tenant_obligation,
                },
                equation_ok=rent_eq_ok,
                weight=Decimal("0.25"),
                tolerance=tol,
            ),
            hard_gate=True,
        )

        _record(
            LedgerMathEngine.check_line_items_exact(
                "line_items_match",
                expected={
                    ln.line_id: (
                        (ln.category, ln.included),
                        (ln.actual_amount, ln.eligible_amount, ln.grossed_up_amount),
                    )
                    for ln in gt.line_items
                },
                actual={
                    ln.line_id: (
                        (ln.category, ln.included),
                        (ln.actual_amount, ln.eligible_amount, ln.grossed_up_amount),
                    )
                    for ln in prediction.line_items
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
