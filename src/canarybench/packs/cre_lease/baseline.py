"""Deterministic naive baseline adapter for smoke-testing `cre-lease`."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, TypeVar, cast

from canarybench.core.schemas import AgentInput, AgentPrediction, round_half_up
from canarybench.packs.cre_lease.schemas import (
    CamExpenseItem,
    CreLeasePrediction,
    CreLeaseRegime,
)

_TENANT_RSF_RE = re.compile(r"Tenant RSF:\s*([0-9,]+(?:\.\d+)?)")
_BLDG_RSF_RE = re.compile(r"Building RSF:\s*([0-9,]+(?:\.\d+)?)")
_BASE_STOP_RE = re.compile(r"Initial Base Year Stop:\s*USD\s*([0-9,]+\.\d{2})")
_BASE_YEAR_RE = re.compile(r"Initial Base Year:\s*(\d{4})")
_PRIOR_RENT_RE = re.compile(r"Prior Annual Base Rent:\s*USD\s*([0-9,]+\.\d{2})")
_LINE_RE = re.compile(
    r"Line\s+(\S+)\s*\|\s*(VARIABLE|FIXED|CAPEX|MGMT_FEE)\s*\|[^|]*\|\s*Actual=USD\s*([0-9,]+\.\d{2})"
)
_CPI_RE = re.compile(r"Year\s+\d+\s+Actual CPI:\s*(\d+\.\d+)%")

PredT = TypeVar("PredT", bound=AgentPrediction)


def _dec(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


class NaiveCreLeaseBaselineAdapter:
    """Naive baseline that ignores 95% gross-up, CapEx exclusions, CPI caps, and amendments."""

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        text = "\n".join(art.extracted_text or "" for art in agent_input.artifacts)
        norm = text.replace("\u00a0", " ").replace("\u00ad", "").replace("\u200b", "")

        t_m = _TENANT_RSF_RE.search(norm)
        b_m = _BLDG_RSF_RE.search(norm)
        tenant_rsf = _dec(t_m.group(1)) if t_m else Decimal("10000")
        bldg_rsf = _dec(b_m.group(1)) if b_m else Decimal("100000")
        pro_rata_pct = round_half_up((tenant_rsf / bldg_rsf) * Decimal("100"), 4)

        stop_m = _BASE_STOP_RE.search(norm)
        stop_amt = _dec(stop_m.group(1)) if stop_m else Decimal("500000.00")
        by_m = _BASE_YEAR_RE.search(norm)
        base_year = int(by_m.group(1)) if by_m else 2023

        rent_m = _PRIOR_RENT_RE.search(norm)
        prior_rent = _dec(rent_m.group(1)) if rent_m else Decimal("400000.00")

        items: list[CamExpenseItem] = []
        var_total = Decimal("0.00")
        fix_total = Decimal("0.00")
        capex_total = Decimal("0.00")
        mgmt_total = Decimal("0.00")

        for lid, cat_raw, amt_raw in _LINE_RE.findall(norm):
            cat = cast(Literal["VARIABLE", "FIXED", "CAPEX", "MGMT_FEE"], cat_raw)
            amt = _dec(amt_raw)
            items.append(
                CamExpenseItem(
                    line_id=lid,
                    category=cat,
                    actual_amount=amt,
                    eligible_amount=amt,
                    grossed_up_amount=amt,
                    included=True,
                )
            )
            if cat == "VARIABLE":
                var_total += amt
            elif cat == "FIXED":
                fix_total += amt
            elif cat == "CAPEX":
                capex_total += amt
            elif cat == "MGMT_FEE":
                mgmt_total += amt

        total_opex = var_total + fix_total + capex_total + mgmt_total
        excess = max(Decimal("0.00"), total_opex - stop_amt)
        cam_payable = round_half_up(excess * (tenant_rsf / bldg_rsf), 2)

        # Uncapped CPI compounding
        mult = Decimal("1")
        for cpi_str in _CPI_RE.findall(norm):
            mult *= Decimal("1") + (Decimal(cpi_str) / Decimal("100"))
        esc_rent = round_half_up(prior_rent * mult, 2)

        pred = CreLeasePrediction(
            scenario_id=agent_input.scenario_id,
            pack_id=agent_input.pack_id,
            engine_id=agent_input.engine_id,
            regime=CreLeaseRegime.MIXED_RECONCILIATION,
            currency="USD",
            pro_rata_share_pct=pro_rata_pct,
            gross_up_applied=False,
            amendment_override_applied=False,
            effective_base_year=base_year,
            grossed_up_variable_opex=var_total,
            eligible_fixed_opex=fix_total,
            included_capex_total=capex_total,
            mgmt_fee_allowed=mgmt_total,
            excluded_capex_total=Decimal("0.00"),
            total_building_opex=total_opex,
            base_year_stop_amount=stop_amt,
            excess_opex_over_stop=excess,
            tenant_cam_payable=cam_payable,
            escalated_base_rent_annual=esc_rent,
            total_annual_tenant_obligation=cam_payable + esc_rent,
            line_items=items,
        )
        return schema.model_validate(pred.model_dump())
