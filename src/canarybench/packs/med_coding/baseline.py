"""Deterministic naive baseline adapter for smoke-testing `med-coding`."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal, TypeVar

from lxml import etree

from canarybench.core.schemas import AgentInput, AgentPrediction
from canarybench.packs.med_coding.schemas import (
    ClaimLineAdjudication,
    MedCodingPrediction,
    MedCodingRegime,
)

PredT = TypeVar("PredT", bound=AgentPrediction)


class NaiveMedCodingBaselineAdapter:
    """Naive baseline that approves every submitted service line without NCCI/MUE/wire checks."""

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        raw_text = "\n".join(art.extracted_text or "" for art in agent_input.artifacts)
        wire_fmt = agent_input.context.get("wire_format", "X12_837P_JSON")
        lines: list[ClaimLineAdjudication] = []
        total = Decimal("0.00")

        if wire_fmt == "X12_837P_JSON":
            try:
                data = json.loads(raw_text, parse_float=Decimal)
                for ln in data.get("service_lines", []):
                    amt = Decimal(str(ln["charge_amount"]))
                    units = int(ln["units"])
                    total += amt
                    lines.append(
                        ClaimLineAdjudication(
                            line_number=int(ln["line_number"]),
                            cpt_hcpcs=str(ln["cpt_hcpcs"]),
                            modifiers=tuple(str(m) for m in ln.get("modifiers", ())),
                            submitted_units=units,
                            payable_units=units,
                            diagnosis_pointers=tuple(
                                int(p) for p in ln.get("diagnosis_pointers", (1,))
                            ),
                            line_status="PAYABLE",
                            denial_reason_code=None,
                            allowed_amount=amt,
                        )
                    )
            except Exception:
                pass
        else:
            try:
                root = etree.fromstring(raw_text.encode("utf-8"))
                for ln in root.findall("ServiceLines/ServiceLine"):
                    amt = Decimal((ln.findtext("ChargeAmount") or "0.00").strip())
                    units = int((ln.findtext("Units") or "1").strip())
                    mods = tuple(
                        m.text.strip()
                        for m in ln.findall("Modifiers/Modifier")
                        if m.text and m.text.strip()
                    )
                    ptrs = tuple(
                        int(p.text.strip())
                        for p in ln.findall("DiagnosisPointers/Pointer")
                        if p.text and p.text.strip()
                    )
                    total += amt
                    lines.append(
                        ClaimLineAdjudication(
                            line_number=int((ln.findtext("LineNumber") or "1").strip()),
                            cpt_hcpcs=(ln.findtext("CptHcpcs") or "99213").strip(),
                            modifiers=mods,
                            submitted_units=units,
                            payable_units=units,
                            diagnosis_pointers=ptrs,
                            line_status="PAYABLE",
                            denial_reason_code=None,
                            allowed_amount=amt,
                        )
                    )
            except Exception:
                pass

        disposition: Literal["PAID_IN_FULL", "PARTIAL_PAY", "DENIED"] = (
            "PAID_IN_FULL" if lines else "DENIED"
        )
        pred = MedCodingPrediction(
            scenario_id=agent_input.scenario_id,
            pack_id=agent_input.pack_id,
            engine_id=agent_input.engine_id,
            regime=MedCodingRegime.INTEGRATED_CLAIM_AUDIT,
            claim_valid_wire=True,
            npi_valid_luhn=True,
            validation_error_codes=[],
            claim_disposition=disposition,
            submitted_charge_total=total,
            payable_total=total,
            line_adjudications=lines,
        )
        return schema.model_validate(pred.model_dump())
