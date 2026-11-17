"""Pydantic v2 domain schemas for the `customs-cbam` benchmark pack."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from canarybench.core.schemas import (
    AgentInput,
    AgentPrediction,
    EngineId,
    GroundTruth,
    MoneyDecimal,
    RateDecimal,
    Scenario,
    StrictDecimal,
)


class CustomsCbamRegime(StrEnum):
    """Four customs GRI classification, FTA origin, and EU CBAM regimes."""

    GRI_CLASSIFICATION = "gri_classification"
    PREFERENTIAL_ORIGIN = "preferential_origin"
    CBAM_LIABILITY = "cbam_liability"
    INTEGRATED_IMPORT = "integrated_import"


class CustomsTrapVariant(StrEnum):
    """Orthogonal GRI, preferential origin, and CBAM trap variants."""

    NONE = "none"
    GRI_3B_VALUE_ESSENTIAL_CHAR = "gri_3b_value_essential_char"
    GRI_3B_WEIGHT_ESSENTIAL_CHAR = "gri_3b_weight_essential_char"
    GRI_3C_NUMERICAL_TIE_BREAK = "gri_3c_numerical_tie_break"
    ORIGIN_CTH_FAILED_SAME_4DIGIT = "origin_cth_failed_same_4digit"
    ORIGIN_MAXNOM_EXCEEDED = "origin_maxnom_exceeded"
    ORIGIN_CUMULATION_NON_PARTY_DISTRACTOR = "origin_cumulation_non_party_distractor"
    CBAM_FREE_ALLOC_EXCEEDS_SEE = "cbam_free_alloc_exceeds_see"
    CBAM_FOREIGN_CARBON_CREDIT = "cbam_foreign_carbon_credit"
    CBAM_DE_MINIMIS_EXEMPT = "cbam_de_minimis_exempt"


def classify_customs_cbam_engine(
    regime: CustomsCbamRegime,
    trap_variant: CustomsTrapVariant,
) -> EngineId:
    """Deterministically assign each customs-cbam scenario to rule-triage or ledger-math."""
    if regime == CustomsCbamRegime.CBAM_LIABILITY or trap_variant in {
        CustomsTrapVariant.ORIGIN_MAXNOM_EXCEEDED,
        CustomsTrapVariant.CBAM_FREE_ALLOC_EXCEEDS_SEE,
        CustomsTrapVariant.CBAM_FOREIGN_CARBON_CREDIT,
    }:
        return EngineId.LEDGER_MATH
    return EngineId.RULE_TRIAGE


class BomComponentEval(BaseModel):
    """BOM component weight, value, HS6, and FTA origin status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: str
    hs6: str = Field(pattern=r"^\d{6}$")
    origin_country: str = Field(pattern=r"^[A-Z]{2}$")
    originating: bool
    weight_kg: StrictDecimal
    value_eur: MoneyDecimal


class CustomsCbamGroundTruth(GroundTruth):
    """Immutable customs GRI classification, FTA origin, and EU CBAM ground truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime: CustomsCbamRegime
    trap_variant: CustomsTrapVariant
    classified_hs6: str = Field(pattern=r"^\d{6}$")
    applied_gri_rule: Literal["GRI_1", "GRI_3a", "GRI_3b", "GRI_3c", "GRI_6"]
    preferential_origin_eligible: bool
    origin_rule_applied: Literal["WO", "CTH", "MAXNOM", "NONE"]
    non_originating_pct: RateDecimal
    mfn_duty_rate_pct: RateDecimal
    applied_duty_rate_pct: RateDecimal
    customs_value_eur: MoneyDecimal
    customs_duty_eur: MoneyDecimal
    cbam_in_scope: bool
    cbam_de_minimis_exempt: bool
    import_mass_tonnes: StrictDecimal
    specific_embedded_emissions: StrictDecimal
    free_allocation_benchmark: StrictDecimal
    net_embedded_emissions_tco2: StrictDecimal
    ets_price_eur: MoneyDecimal
    gross_cbam_liability_eur: MoneyDecimal
    foreign_carbon_paid_eur: MoneyDecimal
    cbam_net_payable_eur: MoneyDecimal
    total_border_charge_eur: MoneyDecimal
    components: tuple[BomComponentEval, ...]
    amount_tolerance: MoneyDecimal = Field(default=MoneyDecimal("0.00"))


class CustomsCbamPrediction(AgentPrediction):
    """Structured prediction returned by an agent evaluated on `customs-cbam`."""

    model_config = ConfigDict(extra="forbid")

    regime: CustomsCbamRegime
    classified_hs6: str = Field(pattern=r"^\d{6}$")
    applied_gri_rule: Literal["GRI_1", "GRI_3a", "GRI_3b", "GRI_3c", "GRI_6"]
    preferential_origin_eligible: bool
    origin_rule_applied: Literal["WO", "CTH", "MAXNOM", "NONE"]
    non_originating_pct: RateDecimal
    applied_duty_rate_pct: RateDecimal
    customs_duty_eur: MoneyDecimal
    cbam_in_scope: bool
    cbam_de_minimis_exempt: bool
    net_embedded_emissions_tco2: StrictDecimal
    gross_cbam_liability_eur: MoneyDecimal
    cbam_net_payable_eur: MoneyDecimal
    total_border_charge_eur: MoneyDecimal


CustomsCbamScenario = Scenario[AgentInput, CustomsCbamGroundTruth]
