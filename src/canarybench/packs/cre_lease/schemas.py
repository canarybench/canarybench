"""Pydantic v2 domain schemas for the `cre-lease` benchmark pack."""

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


class CreLeaseRegime(StrEnum):
    """Five CRE CAM reconciliation and CPI lease escalation regimes."""

    CAM_GROSS_UP = "cam_gross_up"
    BASE_YEAR_STOP = "base_year_stop"
    CPI_ESCALATION = "cpi_escalation"
    AMENDMENT_OVERRIDE = "amendment_override"
    MIXED_RECONCILIATION = "mixed_reconciliation"


class CreLeaseTrapVariant(StrEnum):
    """Orthogonal CAM, CPI, or document-reconciliation trap variant."""

    NONE = "none"
    GROSSUP_BELOW_95_APPLIED = "grossup_below_95_applied"
    GROSSUP_ABOVE_95_NO_OP = "grossup_above_95_no_op"
    GROSSUP_APPLIED_TO_FIXED_COST = "grossup_applied_to_fixed_cost"
    BASE_YEAR_STOP_FLOOR_ZERO = "base_year_stop_floor_zero"
    AMENDMENT_OVERRIDES_BASE_YEAR = "amendment_overrides_base_year"
    AMENDMENT_EXCLUDES_CAPEX_AND_MGMT_CAP = "amendment_excludes_capex_and_mgmt_cap"
    EMAIL_NON_AUTHORITATIVE_DISTRACTOR = "email_non_authoritative_distractor"
    CPI_ANNUAL_CAP_BINDING = "cpi_annual_cap_binding"
    CPI_CUMULATIVE_CEILING_AND_FLOOR = "cpi_cumulative_ceiling_and_floor"


def classify_cre_lease_engine(
    regime: CreLeaseRegime,
    trap_variant: CreLeaseTrapVariant,
    modality: str,
) -> EngineId:
    """Deterministically assign each CRE lease scenario to ledger-math or doc-reconcile."""
    if modality == "context_override" or trap_variant in {
        CreLeaseTrapVariant.AMENDMENT_OVERRIDES_BASE_YEAR,
        CreLeaseTrapVariant.AMENDMENT_EXCLUDES_CAPEX_AND_MGMT_CAP,
        CreLeaseTrapVariant.EMAIL_NON_AUTHORITATIVE_DISTRACTOR,
    }:
        return EngineId.DOC_RECONCILE
    if regime == CreLeaseRegime.AMENDMENT_OVERRIDE:
        return EngineId.DOC_RECONCILE
    return EngineId.LEDGER_MATH


class CamExpenseItem(BaseModel):
    """Line-level CAM operating expense classification and gross-up evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line_id: str
    category: Literal["VARIABLE", "FIXED", "CAPEX", "MGMT_FEE"]
    actual_amount: MoneyDecimal
    eligible_amount: MoneyDecimal
    grossed_up_amount: MoneyDecimal
    included: bool


class CreLeaseGroundTruth(GroundTruth):
    """Immutable CRE CAM reconciliation & CPI escalation ground truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime: CreLeaseRegime
    trap_variant: CreLeaseTrapVariant
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    tenant_rsf: StrictDecimal
    building_rsf: StrictDecimal
    pro_rata_share_pct: RateDecimal
    actual_occupancy_pct: RateDecimal
    gross_up_threshold_pct: RateDecimal = Field(default=RateDecimal("0.95"))
    gross_up_applied: bool
    initial_base_year: int
    effective_base_year: int
    base_year_stop_amount: MoneyDecimal
    eligible_variable_actual: MoneyDecimal
    grossed_up_variable_opex: MoneyDecimal
    eligible_fixed_opex: MoneyDecimal
    included_capex_total: MoneyDecimal
    mgmt_fee_allowed: MoneyDecimal
    excluded_capex_total: MoneyDecimal
    total_building_opex: MoneyDecimal
    excess_opex_over_stop: MoneyDecimal
    tenant_cam_payable: MoneyDecimal
    prior_base_rent_annual: MoneyDecimal
    escalated_base_rent_annual: MoneyDecimal
    effective_cpi_rates: tuple[RateDecimal, ...]
    total_annual_tenant_obligation: MoneyDecimal
    amendment_override_applied: bool
    line_items: tuple[CamExpenseItem, ...]
    amount_tolerance: MoneyDecimal = Field(default=MoneyDecimal("0.00"))


class CreLeasePrediction(AgentPrediction):
    """Structured prediction returned by an agent evaluated on `cre-lease`."""

    model_config = ConfigDict(extra="forbid")

    regime: CreLeaseRegime
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    pro_rata_share_pct: RateDecimal
    gross_up_applied: bool
    amendment_override_applied: bool
    effective_base_year: int
    grossed_up_variable_opex: MoneyDecimal
    eligible_fixed_opex: MoneyDecimal
    included_capex_total: MoneyDecimal
    mgmt_fee_allowed: MoneyDecimal
    excluded_capex_total: MoneyDecimal
    total_building_opex: MoneyDecimal
    base_year_stop_amount: MoneyDecimal
    excess_opex_over_stop: MoneyDecimal
    tenant_cam_payable: MoneyDecimal
    escalated_base_rent_annual: MoneyDecimal
    total_annual_tenant_obligation: MoneyDecimal
    line_items: list[CamExpenseItem]


CreLeaseScenario = Scenario[AgentInput, CreLeaseGroundTruth]
