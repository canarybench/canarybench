"""Deterministic unit & Hypothesis property-based tests for all 4 new domain packs."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from private.factory.packs.claims_adjudication.models import (
    ClaimsRawFacts,
    LossBucketFact,
    PolicyEndorsementFact,
)
from private.factory.packs.claims_adjudication.oracle import evaluate_oracle as eval_claims_oracle
from private.factory.packs.claims_adjudication.sampler import (
    _CANONICAL_BLUEPRINT as CLAIMS_BLUEPRINT,
)
from private.factory.packs.claims_adjudication.sampler import (
    _sample_candidate as sample_claims_candidate,
)
from private.factory.packs.cre_lease.models import (
    CamExpenseFact,
    CreLeaseRawFacts,
    LeaseAmendmentFact,
)
from private.factory.packs.cre_lease.oracle import (
    CreOracleEvaluation,
    CreOracleValidationError,
)
from private.factory.packs.cre_lease.oracle import (
    evaluate_oracle as eval_cre_oracle,
)
from private.factory.packs.cre_lease.sampler import (
    _CANONICAL_BLUEPRINT as CRE_BLUEPRINT,
)
from private.factory.packs.cre_lease.sampler import (
    _sample_candidate as sample_cre_candidate,
)
from private.factory.packs.customs_cbam.models import BomComponentFact, CustomsCbamRawFacts
from private.factory.packs.customs_cbam.oracle import evaluate_oracle as eval_customs_oracle
from private.factory.packs.customs_cbam.sampler import (
    _CANONICAL_BLUEPRINT as CUSTOMS_BLUEPRINT,
)
from private.factory.packs.customs_cbam.sampler import (
    _sample_candidate as sample_customs_candidate,
)
from private.factory.packs.med_coding.models import MedCodingRawFacts, RawClaimLineFact
from private.factory.packs.med_coding.oracle import (
    build_wire_payload_text,
)
from private.factory.packs.med_coding.oracle import (
    evaluate_oracle as eval_med_oracle,
)
from private.factory.packs.med_coding.sampler import (
    _CANONICAL_BLUEPRINT as MED_BLUEPRINT,
)
from private.factory.packs.med_coding.sampler import (
    _sample_candidate as sample_med_candidate,
)

from canarybench.core.schemas import EngineId, round_half_up
from canarybench.packs.claims_adjudication.schemas import ClaimsRegime, ClaimsTrapVariant
from canarybench.packs.cre_lease.schemas import CreLeaseRegime, CreLeaseTrapVariant
from canarybench.packs.customs_cbam.schemas import CustomsCbamRegime, CustomsTrapVariant
from canarybench.packs.med_coding.pack import MedCodingPack
from canarybench.packs.med_coding.schemas import MedCodingRegime, MedCodingTrapVariant
from canarybench.packs.med_coding.wire_validator import (
    is_valid_npi,
    make_valid_npi,
    validate_claim_wire,
)

# ---------------------------------------------------------------------------
# 1. CRE-LEASE: Deterministic Unit & Hypothesis Property Tests
# ---------------------------------------------------------------------------


def test_cre_lease_amendment_vs_email_capex_grossup_and_cpi_caps() -> None:
    facts = CreLeaseRawFacts(
        scenario_id="CRE-UNIT-1",
        drop_id="unit",
        seed=1,
        engine_id=EngineId.DOC_RECONCILE,
        regime=CreLeaseRegime.MIXED_RECONCILIATION,
        trap_variant=CreLeaseTrapVariant.AMENDMENT_EXCLUDES_CAPEX_AND_MGMT_CAP,
        modality="context_override",
        difficulty_tier="edge",
        property_name="Meridian Tower",
        landlord_name="Landlord LLC",
        tenant_name="Tenant Corp",
        suite_label="Suite 100",
        reconciliation_year=2026,
        currency="USD",
        tenant_rsf=Decimal("20000"),
        building_rsf=Decimal("100000"),
        actual_occupancy_pct=Decimal("0.76"),
        initial_base_year=2022,
        initial_base_year_stop=Decimal("50000.00"),
        initial_capex_excluded=False,
        initial_mgmt_fee_cap_pct=None,
        prior_base_rent_annual=Decimal("500000.00"),
        annual_cpi_rates=(Decimal("0.0600"), Decimal("0.0100"), Decimal("0.0600")),
        initial_cpi_annual_cap=Decimal("0.0400"),
        initial_cpi_annual_floor=Decimal("0.0150"),
        initial_cpi_cumulative_ceiling=Decimal("0.1000"),
        initial_cpi_cumulative_floor=None,
        expense_lines=(
            CamExpenseFact("1", "Janitorial", "VARIABLE", Decimal("40000.00")),
            CamExpenseFact("2", "Taxes", "FIXED", Decimal("30000.00")),
            CamExpenseFact("3", "Roof CAPEX", "CAPEX", Decimal("50000.00")),
            CamExpenseFact("4", "Mgmt Fee", "MGMT_FEE", Decimal("15000.00")),
        ),
        amendments=(
            LeaseAmendmentFact(
                doc_id="AMD-1",
                amendment_number=1,
                executed=True,
                effective_date="2024-01-01",
                title="Executed First Amendment",
                narrative="Excludes CAPEX and caps management fee at 4%.",
                override_capex_excluded=True,
                override_mgmt_fee_cap_pct=Decimal("0.04"),
            ),
            LeaseAmendmentFact(
                doc_id="EMAIL-99",
                amendment_number=99,
                executed=False,
                effective_date="2026-01-01",
                title="Unsigned Broker Email",
                narrative="Proposes $200,000 stop.",
                override_base_year_stop=Decimal("200000.00"),
            ),
        ),
    )
    ev = eval_cre_oracle(facts)
    gt = ev.ground_truth
    # Executed amendment overrides CAPEX exclusion & 4% mgmt cap; unsigned email is ignored
    assert gt.amendment_override_applied is True
    assert gt.base_year_stop_amount == Decimal("50000.00")
    assert gt.excluded_capex_total == Decimal("50000.00")
    assert gt.included_capex_total == Decimal("0.00")
    # 40000 * (0.95 / 0.76) = 50000.00; FIXED stays 30000.00
    assert gt.gross_up_applied is True
    assert gt.grossed_up_variable_opex == Decimal("50000.00")
    assert gt.eligible_fixed_opex == Decimal("30000.00")
    # Mgmt cap = 4% * (50000 + 30000) = 3200.00
    assert gt.mgmt_fee_allowed == Decimal("3200.00")
    assert gt.total_building_opex == Decimal("83200.00")
    assert gt.excess_opex_over_stop == Decimal("33200.00")
    # Pro-rata = 20000 / 100000 = 20% -> 6640.00
    assert gt.pro_rata_share_pct == Decimal("20.0000")
    assert gt.tenant_cam_payable == Decimal("6640.00")
    # CPI rates: [0.0400, 0.0150, 0.0400] -> compounded 1.04*1.015*1.04 = 1.097824 < 1.1000
    assert gt.effective_cpi_rates == (Decimal("0.0400"), Decimal("0.0150"), Decimal("0.0400"))
    assert gt.escalated_base_rent_annual == round_half_up(
        Decimal("500000.00") * Decimal("1.04") * Decimal("1.015") * Decimal("1.04"), 2
    )
    assert gt.total_annual_tenant_obligation == (
        gt.tenant_cam_payable + gt.escalated_base_rent_annual
    )


@settings(max_examples=200, deadline=None)
@given(
    bp_idx=st.integers(min_value=0, max_value=len(CRE_BLUEPRINT) - 1),
    seed=st.integers(min_value=1, max_value=10_000_000),
)
def test_cre_lease_property_invariants(bp_idx: int, seed: int) -> None:
    regime, trap, modality = CRE_BLUEPRINT[bp_idx]
    ev: CreOracleEvaluation | None = None
    for attempt in range(25):
        facts = sample_cre_candidate(
            scenario_id=f"CRE-HYP-{seed}",
            drop_id="hyp",
            seed=seed + attempt,
            regime=regime,
            trap=trap,
            modality=modality,
            cosmetic_variant=seed % 4,
        )
        try:
            ev = eval_cre_oracle(facts)
            break
        except CreOracleValidationError:
            continue
    assert ev is not None
    gt = ev.ground_truth

    assert gt.gross_up_applied is (gt.actual_occupancy_pct < Decimal("0.95"))
    if not gt.gross_up_applied:
        assert gt.grossed_up_variable_opex == gt.eligible_variable_actual
    else:
        assert gt.grossed_up_variable_opex == round_half_up(
            gt.eligible_variable_actual * (Decimal("0.95") / gt.actual_occupancy_pct), 2
        )
    # Fixed expenses never grossed up
    fixed_lines = [ln for ln in gt.line_items if ln.category == "FIXED"]
    assert all(ln.grossed_up_amount == ln.actual_amount for ln in fixed_lines)
    assert (
        gt.total_building_opex
        == gt.grossed_up_variable_opex
        + gt.eligible_fixed_opex
        + gt.included_capex_total
        + gt.mgmt_fee_allowed
    )
    assert gt.excess_opex_over_stop == max(
        Decimal("0.00"), gt.total_building_opex - gt.base_year_stop_amount
    )
    assert gt.tenant_cam_payable == round_half_up(
        gt.excess_opex_over_stop * (gt.tenant_rsf / gt.building_rsf), 2
    )
    assert gt.total_annual_tenant_obligation == (
        gt.tenant_cam_payable + gt.escalated_base_rent_annual
    )
    # JSON round-trip preserves exact Decimals with zero float
    parsed = json.loads(gt.model_dump_json(), parse_float=Decimal)
    assert type(parsed["total_annual_tenant_obligation"]) is str


# ---------------------------------------------------------------------------
# 2. CUSTOMS-CBAM: Deterministic Unit & Hypothesis Property Tests
# ---------------------------------------------------------------------------


def test_customs_cbam_gri_tie_break_origin_and_exemptions() -> None:
    # GRI 3(c) numerical tie break + CTH failure + CBAM de minimis (< 50t annual)
    facts = CustomsCbamRawFacts(
        scenario_id="CBAM-UNIT-1",
        drop_id="unit",
        seed=1,
        engine_id=EngineId.RULE_TRIAGE,
        regime=CustomsCbamRegime.INTEGRATED_IMPORT,
        trap_variant=CustomsTrapVariant.CBAM_DE_MINIMIS_EXEMPT,
        modality="pdf_clean",
        difficulty_tier="edge",
        declaration_id="IM4-1",
        importer_name="Rhein GmbH",
        exporter_name="Anatolia A.S.",
        export_country="TR",
        fta_partner_export=True,
        goods_description="Composite sample",
        gri_mode="COMPOSITE_TIE_3C",
        essential_threshold=Decimal("0.60"),
        components=(
            BomComponentFact(
                "C1", "Steel Screw", "731815", "TR", True, True, Decimal("10"), Decimal("400")
            ),
            BomComponentFact(
                "C2", "Alum Sheet", "760612", "TR", True, True, Decimal("10"), Decimal("400")
            ),
        ),
        ex_works_price_eur=Decimal("800.00"),
        customs_value_eur=Decimal("900.00"),
        valid_supplier_origin_decl=True,
        origin_distractor_note=None,
        import_mass_tonnes=Decimal("0.020"),
        annual_importer_cbam_mass_tonnes=Decimal("49.999"),
        specific_embedded_emissions=Decimal("2.500"),
        ets_price_eur=Decimal("80.00"),
        foreign_carbon_paid_eur=Decimal("0.00"),
        foreign_carbon_verified=False,
    )
    ev = eval_customs_oracle(facts)
    gt = ev.ground_truth
    # 760612 > 731815 -> GRI_3c picks 760612
    assert gt.applied_gri_rule == "GRI_3c"
    assert gt.classified_hs6 == "760612"
    assert gt.cbam_in_scope is True
    assert gt.cbam_de_minimis_exempt is True
    assert gt.net_embedded_emissions_tco2 == Decimal("0.000")
    assert gt.cbam_net_payable_eur == Decimal("0.00")

    # CTH failure when non-originating input shares 4-digit heading 7318
    cth_fail = CustomsCbamRawFacts(
        scenario_id="CBAM-UNIT-2",
        drop_id="unit",
        seed=2,
        engine_id=EngineId.RULE_TRIAGE,
        regime=CustomsCbamRegime.PREFERENTIAL_ORIGIN,
        trap_variant=CustomsTrapVariant.ORIGIN_CTH_FAILED_SAME_4DIGIT,
        modality="context_override",
        difficulty_tier="adversarial",
        declaration_id="IM4-2",
        importer_name="Rhein GmbH",
        exporter_name="Anatolia A.S.",
        export_country="TR",
        fta_partner_export=True,
        goods_description="Screws from blanks",
        gri_mode="COMPOSITE_ESSENTIAL_VALUE",
        essential_threshold=Decimal("0.60"),
        components=(
            BomComponentFact(
                "C1", "Blank", "731814", "IN", False, False, Decimal("50"), Decimal("1000")
            ),
            BomComponentFact(
                "C2", "Threading", "731815", "TR", True, True, Decimal("50"), Decimal("3000")
            ),
        ),
        ex_works_price_eur=Decimal("4000.00"),
        customs_value_eur=Decimal("4200.00"),
        valid_supplier_origin_decl=True,
        origin_distractor_note=None,
        import_mass_tonnes=Decimal("60.000"),
        annual_importer_cbam_mass_tonnes=Decimal("60.000"),
        specific_embedded_emissions=Decimal("2.000"),
        ets_price_eur=Decimal("75.00"),
        foreign_carbon_paid_eur=Decimal("500.00"),
        foreign_carbon_verified=True,
    )
    ev2 = eval_customs_oracle(cth_fail)
    gt2 = ev2.ground_truth
    assert gt2.classified_hs6 == "731815"
    assert gt2.origin_rule_applied == "CTH"
    assert gt2.preferential_origin_eligible is False  # 731814[:4] == 731815[:4]
    assert gt2.applied_duty_rate_pct == gt2.mfn_duty_rate_pct
    # Net emissions = 60.000 * (2.000 - 1.370) = 37.800; gross = 2835.00; net = 2335.00
    assert gt2.net_embedded_emissions_tco2 == Decimal("37.800")
    assert gt2.gross_cbam_liability_eur == Decimal("2835.00")
    assert gt2.cbam_net_payable_eur == Decimal("2335.00")
    assert gt2.total_border_charge_eur == gt2.customs_duty_eur + gt2.cbam_net_payable_eur


@settings(max_examples=200, deadline=None)
@given(
    bp_idx=st.integers(min_value=0, max_value=len(CUSTOMS_BLUEPRINT) - 1),
    seed=st.integers(min_value=1, max_value=10_000_000),
)
def test_customs_cbam_property_invariants(bp_idx: int, seed: int) -> None:
    regime, trap, modality = CUSTOMS_BLUEPRINT[bp_idx]
    facts = sample_customs_candidate(
        scenario_id=f"CBAM-HYP-{seed}",
        drop_id="hyp",
        seed=seed,
        regime=regime,
        trap=trap,
        modality=modality,
        cosmetic_variant=seed % 4,
    )
    ev = eval_customs_oracle(facts)
    gt = ev.ground_truth

    assert gt.customs_duty_eur == round_half_up(
        gt.customs_value_eur * gt.applied_duty_rate_pct / Decimal("100"), 2
    )
    if not gt.cbam_in_scope or gt.cbam_de_minimis_exempt:
        assert gt.net_embedded_emissions_tco2 == Decimal("0.000")
        assert gt.gross_cbam_liability_eur == Decimal("0.00")
        assert gt.cbam_net_payable_eur == Decimal("0.00")
    else:
        expected_net_see = max(
            Decimal("0.000"), gt.specific_embedded_emissions - gt.free_allocation_benchmark
        )
        assert gt.net_embedded_emissions_tco2 == round_half_up(
            gt.import_mass_tonnes * expected_net_see, 3
        )
        assert gt.gross_cbam_liability_eur == round_half_up(
            gt.net_embedded_emissions_tco2 * gt.ets_price_eur, 2
        )
        assert gt.cbam_net_payable_eur == max(
            Decimal("0.00"), gt.gross_cbam_liability_eur - gt.foreign_carbon_paid_eur
        )
    assert gt.total_border_charge_eur == gt.customs_duty_eur + gt.cbam_net_payable_eur


# ---------------------------------------------------------------------------
# 3. MED-CODING: NPI Luhn, X12-837P Wire, NCCI PTP & MUE Tests
# ---------------------------------------------------------------------------


def test_med_coding_npi_luhn_wire_errors_ncci_ccmi_and_mue() -> None:
    valid_npi = make_valid_npi("123456789")
    assert is_valid_npi(valid_npi) is True
    corrupted = valid_npi[:-1] + str((int(valid_npi[-1]) + 1) % 10)
    assert is_valid_npi(corrupted) is False
    assert is_valid_npi("12345") is False

    # Validate all 10 public scenarios via MedCodingPack.validate_ground_truth_artifact
    med_pack = MedCodingPack()
    data_root = med_pack.default_dataset_path().parent
    for sc in med_pack.load_scenarios():
        assert med_pack.validate_ground_truth_artifact(sc, data_root) == []

    # Test all 5 wire error codes explicitly
    base_facts = MedCodingRawFacts(
        scenario_id="MED-WIRE",
        drop_id="unit",
        seed=1,
        engine_id=EngineId.WIRE_PROTOCOL,
        regime=MedCodingRegime.WIRE_VALIDATION,
        trap_variant=MedCodingTrapVariant.NONE,
        modality="json_wire",
        difficulty_tier="adversarial",
        wire_format="X12_837P_JSON",
        claim_id="CLM-1",
        service_date="2026-05-01",
        billing_provider_npi=valid_npi,
        rendering_provider_npi=corrupted,
        subscriber_id="SUB-1",
        diagnoses=("BAD_ICD",),
        lines=(RawClaimLineFact(1, "27130", (), "11", 1, Decimal("500.00"), (1, 3)),),
        clinical_note_supports_distinct=True,
        clinical_note_text="Note",
        inject_malformed_wire=False,
    )
    payload_text = build_wire_payload_text(base_facts)
    _, errs = validate_claim_wire(payload_text, "X12_837P_JSON")
    assert set(errs) == {"ERR_NPI_LUHN", "ERR_ICD10_SYNTAX", "ERR_DX_POINTER", "ERR_POS_MISMATCH"}

    malformed = replace(
        base_facts,
        rendering_provider_npi=valid_npi,
        diagnoses=("I10",),
        lines=(RawClaimLineFact(1, "99213", (), "11", 1, Decimal("100.00"), (1,)),),
        inject_malformed_wire=True,
    )
    _, mal_errs = validate_claim_wire(build_wire_payload_text(malformed), "X12_837P_JSON")
    assert mal_errs == ("ERR_WIRE_SCHEMA",)

    # CCMI=0 unbypassable even with -59 vs CCMI=1 bypassable with XS + clinical support vs MUE cap
    ccmi0 = eval_med_oracle(
        MedCodingRawFacts(
            scenario_id="MED-CCMI0",
            drop_id="unit",
            seed=2,
            engine_id=EngineId.RULE_TRIAGE,
            regime=MedCodingRegime.NCCI_PTP_BUNDLING,
            trap_variant=MedCodingTrapVariant.PTP_CCMI_0_UNBYPASSABLE,
            modality="json_wire",
            difficulty_tier="adversarial",
            wire_format="X12_837P_JSON",
            claim_id="CLM-2",
            service_date="2026-05-01",
            billing_provider_npi=valid_npi,
            rendering_provider_npi=valid_npi,
            subscriber_id="SUB-2",
            diagnoses=("K63.5",),
            lines=(
                RawClaimLineFact(1, "45385", (), "24", 1, Decimal("600.00"), (1,)),
                RawClaimLineFact(2, "45378", ("59",), "24", 1, Decimal("400.00"), (1,)),
            ),
            clinical_note_supports_distinct=True,
            clinical_note_text="Supports distinct",
        )
    )
    assert ccmi0.ground_truth.claim_disposition == "PARTIAL_PAY"
    assert ccmi0.ground_truth.payable_total == Decimal("600.00")
    assert ccmi0.ground_truth.line_adjudications[1].line_status == "DENIED_NCCI_PTP"


@settings(max_examples=200, deadline=None)
@given(
    bp_idx=st.integers(min_value=0, max_value=len(MED_BLUEPRINT) - 1),
    seed=st.integers(min_value=1, max_value=10_000_000),
)
def test_med_coding_property_invariants(bp_idx: int, seed: int) -> None:
    regime, trap, modality = MED_BLUEPRINT[bp_idx]
    facts = sample_med_candidate(
        scenario_id=f"MED-HYP-{seed}",
        drop_id="hyp",
        seed=seed,
        regime=regime,
        trap=trap,
        modality=modality,
        cosmetic_variant=seed % 4,
    )
    ev = eval_med_oracle(facts)
    gt = ev.ground_truth

    assert gt.submitted_charge_total == sum(
        (ln.charge_amount for ln in facts.lines), start=Decimal("0.00")
    )
    assert gt.payable_total == sum(
        (ln.allowed_amount for ln in gt.line_adjudications), start=Decimal("0.00")
    )
    if not gt.claim_valid_wire:
        assert gt.claim_disposition == "DENIED"
        assert gt.payable_total == Decimal("0.00")
        assert all(ln.line_status == "DENIED_SCHEMA" for ln in gt.line_adjudications)


# ---------------------------------------------------------------------------
# 4. CLAIMS-ADJUDICATION: 5-Tier Waterfall Unit & Hypothesis Tests
# ---------------------------------------------------------------------------


def test_claims_adjudication_waterfall_endorsement_coinsurance_and_rcv() -> None:
    facts = ClaimsRawFacts(
        scenario_id="CLM-UNIT-1",
        drop_id="unit",
        seed=1,
        engine_id=EngineId.LEDGER_MATH,
        regime=ClaimsRegime.FULL_WATERFALL,
        trap_variant=ClaimsTrapVariant.NONE,
        modality="context_override",
        difficulty_tier="edge",
        policy_number="CP-1",
        claim_number="CLM-1",
        insured_name="Test Corp",
        currency="USD",
        effective_date="2026-01-01",
        expiration_date="2026-12-31",
        retroactive_date="2024-01-01",
        loss_date="2026-06-15",
        building_rcv_total=Decimal("1000000.00"),
        policy_limit=Decimal("600000.00"),  # required 80% = 800k -> ratio = 0.75
        coinsurance_req_pct=Decimal("0.80"),
        deductible_type="PCT_TIV",
        deductible_amount=Decimal("5000.00"),
        deductible_pct=Decimal("0.01"),  # 1% of 1M = 10,000
        min_deductible=Decimal("1000.00"),
        excluded_perils=("FLOOD",),
        peril_sublimits={"WATER_DAMAGE": Decimal("50000.00"), "MOLD": Decimal("15000.00")},
        rcv_endorsement_active=True,
        repair_completed=False,
        repair_invoice_amount=None,
        loss_buckets=(
            LossBucketFact(
                "B1",
                "WATER_MOLD",
                ("WATER_DAMAGE", "MOLD"),
                "Water & Mold",
                Decimal("40000.00"),
                Decimal("30000.00"),
            ),
            LossBucketFact(
                "B2",
                "FIRE",
                ("FIRE",),
                "Fire",
                Decimal("100000.00"),
                Decimal("60000.00"),
            ),
        ),
        endorsements=(
            PolicyEndorsementFact(
                doc_id="END-1",
                title="Mold Sublimit Increase",
                narrative="Raises MOLD sublimit to $25,000.",
                override_sublimits={"MOLD": Decimal("25000.00")},
            ),
        ),
    )
    ev = eval_claims_oracle(facts)
    gt = ev.ground_truth
    # B1 overlapping (50k vs endorsed 25k) -> min = 25k; B2 = 100k -> post_sublimit = 125,000.00
    assert gt.endorsement_override_applied is True
    assert gt.post_sublimit_loss == Decimal("125000.00")
    assert gt.deductible_applied == Decimal("10000.00")
    assert gt.post_deductible_loss == Decimal("115000.00")
    # Coinsurance 600k / 800k = 0.75 -> 115,000 * 0.75 = 86,250.00
    assert gt.coinsurance_penalty_applied is True
    assert gt.coinsurance_ratio == Decimal("0.750000")
    assert gt.post_coinsurance_loss == Decimal("86250.00")
    # Covered ACV = min(25k, 30k) + min(100k, 60k) = 85,000.00
    # initial_acv = min(86250, 85000) = 85000.00; holdback = 1250.00; repair_completed=False
    assert gt.initial_acv_payout == Decimal("85000.00")
    assert gt.recoverable_depreciation_holdback == Decimal("1250.00")
    assert gt.final_total_payable == Decimal("85000.00")


@settings(max_examples=200, deadline=None)
@given(
    bp_idx=st.integers(min_value=0, max_value=len(CLAIMS_BLUEPRINT) - 1),
    seed=st.integers(min_value=1, max_value=10_000_000),
)
def test_claims_adjudication_property_invariants(bp_idx: int, seed: int) -> None:
    regime, trap, modality = CLAIMS_BLUEPRINT[bp_idx]
    facts = sample_claims_candidate(
        scenario_id=f"CLM-HYP-{seed}",
        drop_id="hyp",
        seed=seed,
        regime=regime,
        trap=trap,
        modality=modality,
        cosmetic_variant=seed % 4,
    )
    ev = eval_claims_oracle(facts)
    gt = ev.ground_truth

    assert gt.total_gross_rcv_loss == sum(
        (b.gross_rcv_loss for b in gt.peril_buckets), start=Decimal("0.00")
    )
    assert gt.total_gross_acv_loss == sum(
        (b.gross_acv_loss for b in gt.peril_buckets), start=Decimal("0.00")
    )
    if gt.claim_status != "COVERED_PAYABLE":
        assert gt.final_total_payable == Decimal("0.00")
    else:
        assert gt.post_sublimit_loss == sum(
            (b.capped_loss for b in gt.peril_buckets if b.covered), start=Decimal("0.00")
        )
        assert gt.post_deductible_loss == max(
            Decimal("0.00"), gt.post_sublimit_loss - gt.deductible_applied
        )
        assert gt.policy_limit_capped_payout == min(facts.policy_limit, gt.post_coinsurance_loss)
        expected_final = (
            gt.initial_acv_payout + gt.recoverable_depreciation_holdback
            if (gt.rcv_endorsement_active and gt.repair_completed)
            else gt.initial_acv_payout
        )
        assert gt.final_total_payable == expected_final
