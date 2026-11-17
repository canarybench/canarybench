"""Hypothesis property-based tests proving penny-level EN 16931 reconciliation (1,050+ cases)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from private.factory.packs.eu_vat_2027.models import ModalityType
from private.factory.packs.eu_vat_2027.oracle import OracleValidationError, evaluate_oracle
from private.factory.packs.eu_vat_2027.sampler import _REGIME_TRAPS, _sample_candidate

from canarybench.core.schemas import round_half_up
from canarybench.packs.eu_vat_2027.schemas import EuVatRegime, TrapVariant
from canarybench.packs.eu_vat_2027.xml_validator import validate_en16931

_REGIMES = list(EuVatRegime)
_MODALITIES: list[ModalityType] = [
    "ubl_xml",
    "pdf_clean",
    "pdf_fx",
    "pdf_ocr_noise",
    "context_override",
]


@settings(max_examples=1050, deadline=None)
@given(
    regime_idx=st.integers(min_value=0, max_value=len(_REGIMES) - 1),
    trap_seed=st.integers(min_value=0, max_value=100),
    modality_idx=st.integers(min_value=0, max_value=len(_MODALITIES) - 1),
    seed=st.integers(min_value=1, max_value=10_000_000),
)
def test_oracle_penny_reconciliation_and_en16931_across_1050_cases(
    regime_idx: int,
    trap_seed: int,
    modality_idx: int,
    seed: int,
) -> None:
    regime = _REGIMES[regime_idx]
    traps = _REGIME_TRAPS[regime]
    trap: TrapVariant = traps[trap_seed % len(traps)]
    modality: ModalityType = _MODALITIES[modality_idx]

    facts = _sample_candidate(
        scenario_id=f"HYP-{seed}",
        drop_id="hypothesis",
        seed=seed,
        regime=regime,
        trap=trap,
        modality=modality,
        cosmetic_variant=seed % 4,
    )
    try:
        ev = evaluate_oracle(facts)
    except OracleValidationError as exc:
        raise AssertionError(f"Sampler produced invalid EN 16931 case: {exc}") from exc

    gt = ev.ground_truth
    # 1. Line sum == BT-106
    line_sum = sum((ln.net_amount for ln in gt.line_items), start=Decimal("0.00"))
    assert line_sum == gt.line_extension_total
    # 2. BT-109 == BT-106 - BT-107 + BT-108
    assert gt.tax_exclusive_total == gt.line_extension_total - gt.allowance_total + gt.charge_total
    # 3. Bucketed tax == round_half_up(taxable * rate / 100, 2) and sum(tax) == BT-110
    for row in gt.vat_breakdown:
        expected_tax = round_half_up(row.taxable_amount * row.vat_rate_pct / Decimal("100"), 2)
        assert row.tax_amount == expected_tax
    tax_sum = sum((b.tax_amount for b in gt.vat_breakdown), start=Decimal("0.00"))
    assert tax_sum == gt.total_vat_amount
    # 4. BT-112 == BT-109 + BT-110
    assert gt.tax_inclusive_total == gt.tax_exclusive_total + gt.total_vat_amount
    # 5. FX EUR VAT exact conversion
    if gt.document_currency == "EUR":
        assert gt.tax_currency is None
        assert gt.total_vat_amount_eur == gt.total_vat_amount
    else:
        assert gt.tax_currency == "EUR"
        assert gt.ecb_units_per_eur is not None
        assert gt.total_vat_amount_eur == round_half_up(
            gt.total_vat_amount / gt.ecb_units_per_eur, 2
        )
    # 6. Full deterministic UBL 2.1 + EN 16931 validation passes with 0 errors
    assert validate_en16931(ev.ubl_xml) == []
