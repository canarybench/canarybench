"""Deterministic naive baseline adapter for smoke-testing `claims-adjudication`."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TypeVar

from canarybench.core.schemas import AgentInput, AgentPrediction
from canarybench.packs.claims_adjudication.schemas import (
    ClaimsAdjudicationPrediction,
    ClaimsRegime,
    PerilBucketOutcome,
)

_DED_RE = re.compile(r"Base Deductible:\s*USD\s*([0-9,]+\.\d{2})")
_BUCKET_RE = re.compile(
    r"Bucket\s+(\S+)\s*\|\s*Peril=([A-Z0-9_]+)\s*\|\s*RCV=USD\s*([0-9,]+\.\d{2})\s*\|\s*ACV=USD\s*([0-9,]+\.\d{2})"
)

PredT = TypeVar("PredT", bound=AgentPrediction)


def _dec(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


class NaiveClaimsBaselineAdapter:
    """Naive baseline that sums gross RCV and subtracts base dollar deductible only."""

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        text = "\n".join(art.extracted_text or "" for art in agent_input.artifacts)
        norm = text.replace("\u00a0", " ").replace("\u00ad", "").replace("\u200b", "")

        ded_m = _DED_RE.search(norm)
        ded = _dec(ded_m.group(1)) if ded_m else Decimal("5000.00")

        buckets: list[PerilBucketOutcome] = []
        gross_rcv = Decimal("0.00")
        for bid, peril, rcv_s, acv_s in _BUCKET_RE.findall(norm):
            rcv = _dec(rcv_s)
            acv = _dec(acv_s)
            gross_rcv += rcv
            buckets.append(
                PerilBucketOutcome(
                    bucket_id=bid,
                    peril_code=peril,
                    covered=True,
                    gross_rcv_loss=rcv,
                    gross_acv_loss=acv,
                    sublimit_applied=None,
                    capped_loss=rcv,
                )
            )

        post_ded = max(Decimal("0.00"), gross_rcv - ded)
        pred = ClaimsAdjudicationPrediction(
            scenario_id=agent_input.scenario_id,
            pack_id=agent_input.pack_id,
            engine_id=agent_input.engine_id,
            regime=ClaimsRegime.FULL_WATERFALL,
            claim_status="COVERED_PAYABLE" if post_ded > 0 else "DENIED_BELOW_DEDUCTIBLE",
            within_policy_period=True,
            coinsurance_penalty_applied=False,
            coinsurance_ratio=Decimal("1.000000"),
            endorsement_override_applied=False,
            post_sublimit_loss=gross_rcv,
            deductible_applied=ded,
            post_deductible_loss=post_ded,
            post_coinsurance_loss=post_ded,
            initial_acv_payout=post_ded,
            recoverable_depreciation_holdback=Decimal("0.00"),
            final_total_payable=post_ded,
            peril_buckets=buckets,
        )
        return schema.model_validate(pred.model_dump())
