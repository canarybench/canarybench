"""Deterministic naive baseline adapter for smoke-testing `eu-vat-2027` without GroundTruth."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, TypeVar

from canarybench.core.schemas import AgentInput, AgentPrediction, round_half_up
from canarybench.packs.eu_vat_2027.schemas import (
    EuVatPrediction,
    EuVatRegime,
    VatBreakdownItem,
    VatCategoryCode,
    VatDirectiveArticle,
    VatLineItem,
)

_TAX_EXCL_RE = re.compile(
    r"(?:TaxExclusiveAmount[^>]*>|Net\s+Subtotal[^:]*:\s*[A-Z]{3}\s*)(\d+\.\d{2})"
)
_CCY_RE = re.compile(r"(?:DocumentCurrencyCode>|Currency:\s*)([A-Z]{3})")
_SUP_COUNTRY_RE = re.compile(r"Seller\s+Country:\s*([A-Z]{2})|<cbc:IdentificationCode>([A-Z]{2})")


PredT = TypeVar("PredT", bound=AgentPrediction)


class NaiveVatBaselineAdapter:
    """Naive baseline that assumes domestic 19% standard VAT and ignores traps/attachments.

    Strictly observes only `AgentInput` (never `GroundTruth`), demonstrating real failure
    rates on cross-border reverse charge, Art. 138 transport proof, FX, and SME traps.
    """

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        text = "\n".join(art.extracted_text or "" for art in agent_input.artifacts)
        ccy_m = _CCY_RE.search(text)
        currency = ccy_m.group(1) if ccy_m else "EUR"

        net_m = _TAX_EXCL_RE.search(text)
        net = Decimal(net_m.group(1)) if net_m else Decimal("1000.00")

        sup_m = _SUP_COUNTRY_RE.search(text)
        sup_country = (sup_m.group(1) or sup_m.group(2)) if sup_m else "DE"

        doc_type: Literal["380", "381"] = (
            "381" if "CreditNote" in text or "CREDIT NOTE" in text else "380"
        )
        rate = Decimal("19.00")
        vat = round_half_up(net * rate / Decimal("100"), 2)
        gross = net + vat

        pred = EuVatPrediction(
            scenario_id=agent_input.scenario_id,
            pack_id=agent_input.pack_id,
            engine_id=agent_input.engine_id,
            regime=EuVatRegime.MIXED_RATE_CREDIT_NOTE,
            document_type_code=doc_type,
            taxing_member_state=sup_country,
            document_currency=currency,
            tax_currency="EUR" if currency != "EUR" else None,
            ecb_units_per_eur=Decimal("1.0000") if currency != "EUR" else None,
            vat_category_code=VatCategoryCode.STANDARD,
            legal_basis_code=VatDirectiveArticle.STANDARD_TAXABLE,
            reverse_charge=False,
            line_extension_total=net,
            tax_exclusive_total=net,
            total_vat_amount=vat,
            total_vat_amount_eur=vat,
            tax_inclusive_total=gross,
            payable_amount=gross,
            line_items=[
                VatLineItem(
                    line_id="1",
                    vat_category_code=VatCategoryCode.STANDARD,
                    vat_rate_pct=rate,
                    net_amount=net,
                )
            ],
            vat_breakdown=[
                VatBreakdownItem(
                    vat_category_code=VatCategoryCode.STANDARD,
                    vat_rate_pct=rate,
                    taxable_amount=net,
                    tax_amount=vat,
                )
            ],
        )
        return schema.model_validate(pred.model_dump())
