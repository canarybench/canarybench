"""Pydantic v2 domain schemas for the `med-coding` benchmark pack."""

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
    Scenario,
)


class MedCodingRegime(StrEnum):
    """Four medical coding, NCCI bundling, MUE, and X12-837P wire-validation regimes."""

    NCCI_PTP_BUNDLING = "ncci_ptp_bundling"
    MUE_UNIT_LIMITS = "mue_unit_limits"
    WIRE_VALIDATION = "wire_validation"
    INTEGRATED_CLAIM_AUDIT = "integrated_claim_audit"


class MedCodingTrapVariant(StrEnum):
    """Orthogonal NCCI PTP, MUE, and wire-protocol trap variants."""

    NONE = "none"
    PTP_CCMI_0_UNBYPASSABLE = "ptp_ccmi_0_unbypassable"
    PTP_CCMI_1_VALID_MODIFIER_XS = "ptp_ccmi_1_valid_modifier_xs"
    PTP_CCMI_1_MISSING_CLINICAL_SUPPORT = "ptp_ccmi_1_missing_clinical_support"
    PTP_CCMI_1_WRONG_MODIFIER = "ptp_ccmi_1_wrong_modifier"
    MUE_UNITS_EXCEEDED = "mue_units_exceeded"
    NPI_LUHN_INVALID = "npi_luhn_invalid"
    DX_POINTER_OUT_OF_RANGE = "dx_pointer_out_of_range"
    POS_PROCEDURE_MISMATCH = "pos_procedure_mismatch"
    WIRE_SCHEMA_MALFORMED = "wire_schema_malformed"


def classify_med_coding_engine(
    regime: MedCodingRegime,
    trap_variant: MedCodingTrapVariant,
) -> EngineId:
    """Deterministically assign each med-coding scenario to rule-triage or wire-protocol."""
    if regime == MedCodingRegime.WIRE_VALIDATION or trap_variant in {
        MedCodingTrapVariant.NPI_LUHN_INVALID,
        MedCodingTrapVariant.DX_POINTER_OUT_OF_RANGE,
        MedCodingTrapVariant.POS_PROCEDURE_MISMATCH,
        MedCodingTrapVariant.WIRE_SCHEMA_MALFORMED,
    }:
        return EngineId.WIRE_PROTOCOL
    return EngineId.RULE_TRIAGE


class ClaimLineAdjudication(BaseModel):
    """Line-level NCCI PTP, MUE, and wire-schema adjudication outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line_number: int = Field(ge=1)
    cpt_hcpcs: str = Field(pattern=r"^[A-Z0-9]{5}$")
    modifiers: tuple[str, ...] = ()
    submitted_units: int = Field(ge=1)
    payable_units: int = Field(ge=0)
    diagnosis_pointers: tuple[int, ...] = ()
    line_status: Literal["PAYABLE", "DENIED_NCCI_PTP", "DENIED_MUE", "DENIED_SCHEMA"]
    denial_reason_code: str | None = None
    allowed_amount: MoneyDecimal


class MedCodingGroundTruth(GroundTruth):
    """Immutable medical coding, NCCI PTP, and X12-837P adjudication ground truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime: MedCodingRegime
    trap_variant: MedCodingTrapVariant
    wire_format: Literal["X12_837P_JSON", "X12_837P_XML"]
    claim_valid_wire: bool
    npi_valid_luhn: bool
    validation_error_codes: tuple[str, ...] = ()
    claim_disposition: Literal["PAID_IN_FULL", "PARTIAL_PAY", "DENIED"]
    submitted_charge_total: MoneyDecimal
    payable_total: MoneyDecimal
    line_adjudications: tuple[ClaimLineAdjudication, ...]
    amount_tolerance: MoneyDecimal = Field(default=MoneyDecimal("0.00"))


class MedCodingPrediction(AgentPrediction):
    """Structured prediction returned by an agent evaluated on `med-coding`."""

    model_config = ConfigDict(extra="forbid")

    regime: MedCodingRegime
    claim_valid_wire: bool
    npi_valid_luhn: bool
    validation_error_codes: list[str] = Field(default_factory=list)
    claim_disposition: Literal["PAID_IN_FULL", "PARTIAL_PAY", "DENIED"]
    submitted_charge_total: MoneyDecimal
    payable_total: MoneyDecimal
    line_adjudications: list[ClaimLineAdjudication]


MedCodingScenario = Scenario[AgentInput, MedCodingGroundTruth]
