"""Deterministic grading rubric for the `eu-vat-2027` pack using horizontal engines."""

from __future__ import annotations

from decimal import Decimal

from canarybench.core.base import BaseEngine
from canarybench.core.schemas import CheckResult, GradeResult
from canarybench.engines import (
    DocReconcileEngine,
    LedgerMathEngine,
    RuleTriageEngine,
    WireProtocolEngine,
)
from canarybench.packs.eu_vat_2027.schemas import (
    EuVatGroundTruth,
    EuVatPrediction,
    EuVatScenario,
)


class EuVatGrader:
    """Zero-LLM deterministic grader composing the 4 horizontal engine primitives."""

    def grade(
        self,
        scenario: EuVatScenario,
        prediction: EuVatPrediction,
    ) -> GradeResult:
        gt: EuVatGroundTruth = scenario.ground_truth
        tol = gt.amount_tolerance
        checks: list[CheckResult] = []
        hard_fail_reasons: list[str] = []

        def _record(res: CheckResult, *, hard_gate: bool = False) -> None:
            checks.append(res)
            if hard_gate and not res.passed:
                hard_fail_reasons.append(res.check_id)

        _record(
            WireProtocolEngine.check_protocol_codes(
                "document_type_exact",
                expected_codes={"document_type_code": gt.document_type_code},
                actual_codes={"document_type_code": prediction.document_type_code},
                weight=Decimal("0.05"),
            ),
            hard_gate=True,
        )

        _record(
            LedgerMathEngine.check_fx_conversion(
                "currency_and_fx_exact",
                doc_ccy=gt.document_currency,
                actual_doc_ccy=prediction.document_currency,
                tax_ccy=gt.tax_currency,
                actual_tax_ccy=prediction.tax_currency,
                expected_rate=gt.ecb_units_per_eur,
                actual_rate=prediction.ecb_units_per_eur,
                weight=Decimal("0.05"),
                rate_tolerance=Decimal("0.0001"),
            )
        )

        _record(
            RuleTriageEngine.check_enum_exact(
                "regime_exact",
                expected=gt.regime.value,
                actual=prediction.regime.value,
                weight=Decimal("0.10"),
            ),
            hard_gate=True,
        )

        _record(
            DocReconcileEngine.check_authoritative_field(
                "taxing_member_state_exact",
                expected=gt.taxing_member_state,
                actual=prediction.taxing_member_state,
                weight=Decimal("0.10"),
                distractor_values=(
                    (gt.issuer_country,) if gt.taxing_member_state != gt.issuer_country else ()
                ),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_enum_exact(
                "vat_category_exact",
                expected=gt.vat_category_code.value,
                actual=prediction.vat_category_code.value,
                weight=Decimal("0.15"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_bool_gate(
                "reverse_charge_exact",
                expected=gt.reverse_charge,
                actual=prediction.reverse_charge,
                weight=Decimal("0.10"),
            ),
            hard_gate=True,
        )

        _record(
            RuleTriageEngine.check_legal_basis_exact(
                "legal_basis_exact",
                expected=gt.legal_basis_code.value,
                actual=prediction.legal_basis_code.value,
                weight=Decimal("0.10"),
            )
        )

        _record(
            LedgerMathEngine.check_totals_equation(
                "doc_totals_decimal",
                expected_fields={
                    "line_extension_total": gt.line_extension_total,
                    "tax_exclusive_total": gt.tax_exclusive_total,
                    "total_vat_amount": gt.total_vat_amount,
                    "total_vat_amount_eur": gt.total_vat_amount_eur,
                    "tax_inclusive_total": gt.tax_inclusive_total,
                    "payable_amount": gt.payable_amount,
                },
                actual_fields={
                    "line_extension_total": prediction.line_extension_total,
                    "tax_exclusive_total": prediction.tax_exclusive_total,
                    "total_vat_amount": prediction.total_vat_amount,
                    "total_vat_amount_eur": prediction.total_vat_amount_eur,
                    "tax_inclusive_total": prediction.tax_inclusive_total,
                    "payable_amount": prediction.payable_amount,
                },
                equation_ok=(
                    prediction.tax_inclusive_total
                    == prediction.tax_exclusive_total + prediction.total_vat_amount
                ),
                weight=Decimal("0.15"),
                tolerance=tol,
            ),
            hard_gate=True,
        )

        _record(
            LedgerMathEngine.check_bucket_reconciliation(
                "vat_breakdown_match",
                expected=[
                    (
                        (b.vat_category_code.value, b.vat_rate_pct),
                        (b.taxable_amount, b.tax_amount),
                    )
                    for b in gt.vat_breakdown
                ],
                actual=[
                    (
                        (b.vat_category_code.value, b.vat_rate_pct),
                        (b.taxable_amount, b.tax_amount),
                    )
                    for b in prediction.vat_breakdown
                ],
                weight=Decimal("0.10"),
                tolerance=tol,
            )
        )

        _record(
            LedgerMathEngine.check_line_items_exact(
                "line_items_match",
                expected={
                    ln.line_id: (
                        (ln.vat_category_code.value, ln.vat_rate_pct),
                        (ln.net_amount,),
                    )
                    for ln in gt.line_items
                },
                actual={
                    ln.line_id: (
                        (ln.vat_category_code.value, ln.vat_rate_pct),
                        (ln.net_amount,),
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
