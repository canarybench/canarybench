"""Pydantic v2 domain schemas for the `eu-vat-2027` benchmark pack."""

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


class EuVatRegime(StrEnum):
    """Five high-failure cross-border and domestic EU VAT compliance regimes."""

    TRIANGULAR_TRADE = "triangular_trade"
    CROSS_BORDER_SERVICES = "cross_border_services"
    INTRA_COMMUNITY_GOODS = "intra_community_goods"
    MIXED_RATE_CREDIT_NOTE = "mixed_rate_credit_note"
    SMALL_BUSINESS_SME = "small_business_sme"


class TrapVariant(StrEnum):
    """Orthogonal compliance or arithmetic trap variant within a regime."""

    NONE = "none"
    # Regime 1: Triangular Trade (Art. 141)
    TRI_A_EQUALS_C = "tri_a_equals_c"
    TRI_B_REGISTERED_IN_C = "tri_b_registered_in_c"
    TRI_FOUR_PARTY_CHAIN = "tri_four_party_chain"
    TRI_INVALID_C_VAT = "tri_invalid_c_vat"
    # Regime 2: Cross-Border B2B Services (Art. 44 / Art. 196)
    SVC_EXPIRED_VIES = "svc_expired_vies"
    SVC_MALFORMED_VAT = "svc_malformed_vat"
    SVC_MISSING_VAT = "svc_missing_vat"
    SVC_B2C_CONSUMER = "svc_b2c_consumer"
    SVC_DOMESTIC = "svc_domestic"
    # Regime 3: Intra-Community Supply of Goods (Art. 138)
    ICS_CMR_DOMESTIC = "ics_cmr_domestic"
    ICS_CMR_MISSING = "ics_cmr_missing"
    ICS_CMR_CONTRADICTORY = "ics_cmr_contradictory"
    ICS_INVALID_BUYER_VIES = "ics_invalid_buyer_vies"
    # Regime 4: Mixed-Rate & Partial Credit Notes (380 / 381)
    MIXED_FULL_INVOICE_380 = "mixed_full_invoice_380"
    MIXED_PARTIAL_CREDIT_381 = "mixed_partial_credit_381"
    MIXED_PENNY_ROUNDING_380 = "mixed_penny_rounding_380"
    # Regime 5: Small Business Exemption (Kleinunternehmer / SME Dir 2020/285)
    SME_EU_100K_BREACHED = "sme_eu_100k_breached"
    SME_DOMESTIC_THRESHOLD_BREACHED = "sme_domestic_threshold_breached"
    SME_MISSING_OR_INVALID_EX_ID = "sme_missing_or_invalid_ex_id"


def classify_eu_vat_engine(
    regime: EuVatRegime,
    trap_variant: TrapVariant,
    modality: str,
) -> EngineId:
    """Deterministically tag an EU VAT scenario into one of the 4 horizontal engines."""
    if trap_variant in {
        TrapVariant.SVC_MALFORMED_VAT,
        TrapVariant.SME_MISSING_OR_INVALID_EX_ID,
    } or modality == "ubl_xml":
        return EngineId.WIRE_PROTOCOL

    if modality == "context_override" or regime == EuVatRegime.INTRA_COMMUNITY_GOODS:
        return EngineId.DOC_RECONCILE

    if regime == EuVatRegime.MIXED_RATE_CREDIT_NOTE or modality == "pdf_fx":
        return EngineId.LEDGER_MATH

    return EngineId.RULE_TRIAGE


class VatCategoryCode(StrEnum):
    """UNCL5305 Tax Category Codes used by EN 16931."""

    STANDARD = "S"
    ZERO_RATED = "Z"
    EXEMPT = "E"
    REVERSE_CHARGE = "AE"
    INTRA_COMMUNITY = "K"


class VatDirectiveArticle(StrEnum):
    """Canonical EU VAT Directive 2006/112/EC legal basis identifiers."""

    ART_44_196 = "2006/112/EC_ART_44_196"
    ART_138_1 = "2006/112/EC_ART_138_1"
    ART_141_197 = "2006/112/EC_ART_141_197"
    ART_284_SME = "2006/112/EC_ART_284"
    STANDARD_TAXABLE = "STANDARD_TAXABLE"


class VatLineItem(BaseModel):
    """Line-level VAT classification and net amount."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line_id: str
    vat_category_code: VatCategoryCode
    vat_rate_pct: RateDecimal
    net_amount: MoneyDecimal


class VatBreakdownItem(BaseModel):
    """EN 16931 BG-23 bucketed VAT breakdown in document currency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vat_category_code: VatCategoryCode
    vat_rate_pct: RateDecimal
    taxable_amount: MoneyDecimal
    tax_amount: MoneyDecimal


class EuVatGroundTruth(GroundTruth):
    """Immutable EU VAT compliance & EN 16931 arithmetic ground truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime: EuVatRegime
    trap_variant: TrapVariant
    document_type_code: Literal["380", "381"]
    issuer_country: str = Field(pattern=r"^[A-Z]{2}$")
    customer_country: str = Field(pattern=r"^[A-Z]{2}$")
    taxing_member_state: str = Field(pattern=r"^[A-Z]{2}$")
    document_currency: str = Field(pattern=r"^[A-Z]{3}$")
    tax_currency: Literal["EUR"] | None = None
    ecb_units_per_eur: RateDecimal | None = None
    vat_category_code: VatCategoryCode
    legal_basis_code: VatDirectiveArticle
    reverse_charge: bool
    line_extension_total: MoneyDecimal
    allowance_total: MoneyDecimal
    charge_total: MoneyDecimal
    tax_exclusive_total: MoneyDecimal
    total_vat_amount: MoneyDecimal
    total_vat_amount_eur: MoneyDecimal
    tax_inclusive_total: MoneyDecimal
    payable_amount: MoneyDecimal
    line_items: tuple[VatLineItem, ...]
    vat_breakdown: tuple[VatBreakdownItem, ...]
    mandatory_invoice_legend: str | None = None
    supplier_vat_id_used: str | None = None
    buyer_vat_id_used: str | None = None
    ground_truth_ubl_rel_path: str | None = None
    amount_tolerance: MoneyDecimal = Field(default=MoneyDecimal("0.00"))


class EuVatPrediction(AgentPrediction):
    """Structured prediction returned by an agent evaluated on `eu-vat-2027`."""

    model_config = ConfigDict(extra="forbid")

    regime: EuVatRegime
    document_type_code: Literal["380", "381"]
    taxing_member_state: str = Field(pattern=r"^[A-Z]{2}$")
    document_currency: str = Field(pattern=r"^[A-Z]{3}$")
    tax_currency: Literal["EUR"] | None = None
    ecb_units_per_eur: RateDecimal | None = None
    vat_category_code: VatCategoryCode
    legal_basis_code: VatDirectiveArticle
    reverse_charge: bool
    line_extension_total: MoneyDecimal
    tax_exclusive_total: MoneyDecimal
    total_vat_amount: MoneyDecimal
    total_vat_amount_eur: MoneyDecimal
    tax_inclusive_total: MoneyDecimal
    payable_amount: MoneyDecimal
    line_items: list[VatLineItem]
    vat_breakdown: list[VatBreakdownItem]


EuVatScenario = Scenario[AgentInput, EuVatGroundTruth]
