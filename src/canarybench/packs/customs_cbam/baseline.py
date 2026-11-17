"""Deterministic naive baseline adapter for smoke-testing `customs-cbam`."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TypeVar

from canarybench.core.schemas import AgentInput, AgentPrediction, round_half_up
from canarybench.packs.customs_cbam.schemas import (
    CustomsCbamPrediction,
    CustomsCbamRegime,
)

_HS6_RE = re.compile(r"HS6=(\d{6})")
_VAL_RE = re.compile(r"Customs Value:\s*EUR\s*([0-9,]+\.\d{2})")
_PREF_RATE_RE = re.compile(r"Preferential Duty Rate:\s*(\d+\.\d+)%")
_MASS_RE = re.compile(r"Import Mass:\s*(\d+\.\d{3})\s*tonnes")
_SEE_RE = re.compile(r"Specific Embedded Emissions:\s*(\d+\.\d{3})\s*tCO2/t")
_ETS_RE = re.compile(r"EU ETS Reference Price:\s*EUR\s*(\d+\.\d{2})/tCO2")

PredT = TypeVar("PredT", bound=AgentPrediction)


def _dec(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


class NaiveCustomsCbamBaselineAdapter:
    """Naive baseline picking first BOM HS6, assuming FTA origin & skipping CBAM deductions."""

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        text = "\n".join(art.extracted_text or "" for art in agent_input.artifacts)
        norm = text.replace("\u00a0", " ").replace("\u00ad", "").replace("\u200b", "")

        hs_m = _HS6_RE.search(norm)
        hs6 = hs_m.group(1) if hs_m else "731815"

        val_m = _VAL_RE.search(norm)
        cval = _dec(val_m.group(1)) if val_m else Decimal("10000.00")

        pref_m = _PREF_RATE_RE.search(norm)
        duty_rate = Decimal(pref_m.group(1)) if pref_m else Decimal("0.00")
        duty = round_half_up(cval * duty_rate / Decimal("100"), 2)

        mass_m = _MASS_RE.search(norm)
        see_m = _SEE_RE.search(norm)
        ets_m = _ETS_RE.search(norm)
        mass = Decimal(mass_m.group(1)) if mass_m else Decimal("0.000")
        see = Decimal(see_m.group(1)) if see_m else Decimal("0.000")
        ets = Decimal(ets_m.group(1)) if ets_m else Decimal("75.00")

        net_em = round_half_up(mass * see, 3)
        cbam_gross = round_half_up(net_em * ets, 2)

        pred = CustomsCbamPrediction(
            scenario_id=agent_input.scenario_id,
            pack_id=agent_input.pack_id,
            engine_id=agent_input.engine_id,
            regime=CustomsCbamRegime.INTEGRATED_IMPORT,
            classified_hs6=hs6,
            applied_gri_rule="GRI_1",
            preferential_origin_eligible=True,
            origin_rule_applied="CTH",
            non_originating_pct=Decimal("0.00"),
            applied_duty_rate_pct=duty_rate,
            customs_duty_eur=duty,
            cbam_in_scope=True,
            cbam_de_minimis_exempt=False,
            net_embedded_emissions_tco2=net_em,
            gross_cbam_liability_eur=cbam_gross,
            cbam_net_payable_eur=cbam_gross,
            total_border_charge_eur=duty + cbam_gross,
        )
        return schema.model_validate(pred.model_dump())
