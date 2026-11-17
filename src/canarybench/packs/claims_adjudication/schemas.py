"""Pydantic v2 domain schemas for the `claims-adjudication` benchmark pack."""

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
)


class ClaimsRegime(StrEnum):
    """Five P&C multi-tier policy adjudication regimes."""

    PERIOD_AND_PERIL = "period_and_peril"
    SUBLIMIT_AND_DEDUCTIBLE = "sublimit_and_deductible"
    COINSURANCE_PENALTY = "coinsurance_penalty"
    ACV_RCV_HOLDBACK = "acv_rcv_holdback"
    FULL_WATERFALL = "full_waterfall"


class ClaimsTrapVariant(StrEnum):
    """Orthogonal P&C coverage, sub-limit, deductible, coinsurance, and RCV traps."""

    NONE = "none"
    OUTSIDE_POLICY_PERIOD = "outside_policy_period"
    EXCLUDED_PERIL_ENDORSEMENT = "excluded_peril_endorsement"
    OVERLAPPING_SUBLIMIT_LOWEST_WINS = "overlapping_sublimit_lowest_wins"
    PERCENTAGE_TIV_DEDUCTIBLE = "percentage_tiv_deductible"
    COINSURANCE_UNDERINSURED_PENALTY = "coinsurance_underinsured_penalty"
    COINSURANCE_SATISFIED_NO_PENALTY = "coinsurance_satisfied_no_penalty"
    RCV_HOLDBACK_REPAIR_INCOMPLETE = "rcv_holdback_repair_incomplete"
    RCV_RELEASE_REPAIR_COMPLETED = "rcv_release_repair_completed"
    ENDORSEMENT_OVERRIDES_POLICY_SUBLIMIT = "endorsement_overrides_policy_sublimit"


def classify_claims_engine(
    regime: ClaimsRegime,
    trap_variant: ClaimsTrapVariant,
) -> EngineId:
    """Deterministically assign each claims-adjudication scenario to rule-triage or ledger-math."""
    if regime == ClaimsRegime.PERIOD_AND_PERIL or trap_variant in {
        ClaimsTrapVariant.OUTSIDE_POLICY_PERIOD,
        ClaimsTrapVariant.EXCLUDED_PERIL_ENDORSEMENT,
        ClaimsTrapVariant.OVERLAPPING_SUBLIMIT_LOWEST_WINS,
        ClaimsTrapVariant.ENDORSEMENT_OVERRIDES_POLICY_SUBLIMIT,
    }:
        return EngineId.RULE_TRIAGE
    return EngineId.LEDGER_MATH


class PerilBucketOutcome(BaseModel):
    """Per-bucket peril coverage and overlapping sub-limit evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket_id: str
    peril_code: str
    covered: bool
    gross_rcv_loss: MoneyDecimal
    gross_acv_loss: MoneyDecimal
    sublimit_applied: MoneyDecimal | None = None
    capped_loss: MoneyDecimal


class ClaimsAdjudicationGroundTruth(GroundTruth):
    """Immutable P&C 5-tier claims adjudication waterfall ground truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime: ClaimsRegime
    trap_variant: ClaimsTrapVariant
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    claim_status: Literal[
        "COVERED_PAYABLE",
        "DENIED_OUTSIDE_PERIOD",
        "DENIED_EXCLUDED_PERIL",
        "DENIED_BELOW_DEDUCTIBLE",
    ]
    within_policy_period: bool
    coinsurance_penalty_applied: bool
    coinsurance_ratio: RateDecimal
    endorsement_override_applied: bool
    rcv_endorsement_active: bool
    repair_completed: bool
    total_gross_rcv_loss: MoneyDecimal
    total_gross_acv_loss: MoneyDecimal
    post_sublimit_loss: MoneyDecimal
    deductible_applied: MoneyDecimal
    post_deductible_loss: MoneyDecimal
    post_coinsurance_loss: MoneyDecimal
    policy_limit_capped_payout: MoneyDecimal
    initial_acv_payout: MoneyDecimal
    recoverable_depreciation_holdback: MoneyDecimal
    final_total_payable: MoneyDecimal
    peril_buckets: tuple[PerilBucketOutcome, ...]
    amount_tolerance: MoneyDecimal = Field(default=MoneyDecimal("0.00"))


class ClaimsAdjudicationPrediction(AgentPrediction):
    """Structured prediction returned by an agent evaluated on `claims-adjudication`."""

    model_config = ConfigDict(extra="forbid")

    regime: ClaimsRegime
    claim_status: Literal[
        "COVERED_PAYABLE",
        "DENIED_OUTSIDE_PERIOD",
        "DENIED_EXCLUDED_PERIL",
        "DENIED_BELOW_DEDUCTIBLE",
    ]
    within_policy_period: bool
    coinsurance_penalty_applied: bool
    coinsurance_ratio: RateDecimal
    endorsement_override_applied: bool
    post_sublimit_loss: MoneyDecimal
    deductible_applied: MoneyDecimal
    post_deductible_loss: MoneyDecimal
    post_coinsurance_loss: MoneyDecimal
    initial_acv_payout: MoneyDecimal
    recoverable_depreciation_holdback: MoneyDecimal
    final_total_payable: MoneyDecimal
    peril_buckets: list[PerilBucketOutcome]


ClaimsAdjudicationScenario = Scenario[AgentInput, ClaimsAdjudicationGroundTruth]
