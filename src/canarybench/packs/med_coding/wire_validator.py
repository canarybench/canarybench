"""Deterministic X12-837P-inspired JSON/XML validator, CMS NPI Luhn, and ICD-10-CM checks."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Literal

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from canarybench.core.schemas import MoneyDecimal

ICD10_CM_RE = re.compile(r"^[A-TV-Z][0-9][0-9AB](?:\.[0-9A-TV-Z]{1,4})?$")
CPT_HCPCS_RE = re.compile(r"^[A-Z0-9]{5}$")
NPI_RE = re.compile(r"^\d{10}$")

VALID_POS_CODES: frozenset[str] = frozenset({"11", "19", "21", "22", "23", "24", "81"})
INPATIENT_ONLY_CPTS: frozenset[str] = frozenset({"27130", "33533", "44140", "22551"})
OFFICE_ONLY_RESTRICTED_POS: frozenset[str] = frozenset({"11", "24"})


def _luhn_check_digit(digits: str) -> int:
    total = 0
    for idx, ch in enumerate(reversed(digits)):
        d = int(ch)
        if idx % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def is_valid_npi(npi: str) -> bool:
    """Validate a 10-digit CMS NPI using the ISO 7812 Luhn check with '80840' prefix."""
    if not NPI_RE.match(npi):
        return False
    expected_check = _luhn_check_digit("80840" + npi[:9])
    return int(npi[9]) == expected_check


def make_valid_npi(nine_digits: str) -> str:
    """Generate a valid 10-digit CMS NPI from a 9-digit base string."""
    if not re.match(r"^\d{9}$", nine_digits):
        raise ValueError(f"Expected 9 digits, got {nine_digits!r}")
    return nine_digits + str(_luhn_check_digit("80840" + nine_digits))


class Claim837PServiceLine(BaseModel):
    """Canonical X12-837P SV1 professional claim service line."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line_number: int = Field(ge=1)
    cpt_hcpcs: str = Field(pattern=r"^[A-Z0-9]{5}$")
    modifiers: tuple[str, ...] = ()
    pos_code: str = Field(pattern=r"^\d{2}$")
    units: int = Field(ge=1)
    charge_amount: MoneyDecimal
    diagnosis_pointers: tuple[int, ...] = Field(min_length=1, max_length=4)


class Claim837PWirePayload(BaseModel):
    """Canonical X12-837P-inspired claim envelope schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(min_length=1)
    service_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    billing_provider_npi: str = Field(pattern=r"^\d{10}$")
    rendering_provider_npi: str = Field(pattern=r"^\d{10}$")
    subscriber_id: str = Field(min_length=1)
    diagnoses: tuple[str, ...] = Field(min_length=1, max_length=12)
    service_lines: tuple[Claim837PServiceLine, ...] = Field(min_length=1)


def _xml_to_dict(raw_xml: str) -> dict[str, Any]:
    root = etree.fromstring(raw_xml.encode("utf-8"))
    if root.tag != "Claim837P":
        raise ValueError(f"Expected root tag <Claim837P>, got <{root.tag}>")

    def _req_text(parent: etree._Element, tag: str) -> str:
        el = parent.find(tag)
        if el is None or el.text is None:
            raise ValueError(f"Missing required XML element <{tag}>")
        return el.text.strip()

    dx_els = root.findall("Diagnoses/ICD10")
    diagnoses = [el.text.strip() for el in dx_els if el.text and el.text.strip()]

    lines: list[dict[str, Any]] = []
    for ln in root.findall("ServiceLines/ServiceLine"):
        mods = [
            m.text.strip() for m in ln.findall("Modifiers/Modifier") if m.text and m.text.strip()
        ]
        ptrs = [int(p.text.strip()) for p in ln.findall("DiagnosisPointers/Pointer") if p.text]
        lines.append(
            {
                "line_number": int(_req_text(ln, "LineNumber")),
                "cpt_hcpcs": _req_text(ln, "CptHcpcs"),
                "modifiers": mods,
                "pos_code": _req_text(ln, "PosCode"),
                "units": int(_req_text(ln, "Units")),
                "charge_amount": _req_text(ln, "ChargeAmount"),
                "diagnosis_pointers": ptrs,
            }
        )

    return {
        "claim_id": _req_text(root, "ClaimId"),
        "service_date": _req_text(root, "ServiceDate"),
        "billing_provider_npi": _req_text(root, "BillingProviderNpi"),
        "rendering_provider_npi": _req_text(root, "RenderingProviderNpi"),
        "subscriber_id": _req_text(root, "SubscriberId"),
        "diagnoses": diagnoses,
        "service_lines": lines,
    }


def validate_claim_wire(
    raw_text: str,
    wire_format: Literal["X12_837P_JSON", "X12_837P_XML"],
) -> tuple[Claim837PWirePayload | None, tuple[str, ...]]:
    """Validate X12-837P JSON/XML structure, NPI Luhn, ICD-10-CM syntax, pointers, and POS."""
    errors: set[str] = set()
    try:
        if wire_format == "X12_837P_JSON":
            raw_obj = json.loads(raw_text, parse_float=Decimal)
            if not isinstance(raw_obj, dict):
                return None, ("ERR_WIRE_SCHEMA",)
        else:
            raw_obj = _xml_to_dict(raw_text)
        payload = Claim837PWirePayload.model_validate(raw_obj)
    except (ValueError, etree.XMLSyntaxError, ValidationError):
        return None, ("ERR_WIRE_SCHEMA",)

    if not (
        is_valid_npi(payload.billing_provider_npi) and is_valid_npi(payload.rendering_provider_npi)
    ):
        errors.add("ERR_NPI_LUHN")

    for dx in payload.diagnoses:
        if not ICD10_CM_RE.match(dx):
            errors.add("ERR_ICD10_SYNTAX")

    max_ptr = min(4, len(payload.diagnoses))
    for ln in payload.service_lines:
        if ln.charge_amount <= Decimal("0.00"):
            errors.add("ERR_WIRE_SCHEMA")
        if ln.pos_code not in VALID_POS_CODES:
            errors.add("ERR_WIRE_SCHEMA")
        if len(set(ln.diagnosis_pointers)) != len(ln.diagnosis_pointers) or any(
            p < 1 or p > max_ptr for p in ln.diagnosis_pointers
        ):
            errors.add("ERR_DX_POINTER")
        if ln.cpt_hcpcs in INPATIENT_ONLY_CPTS and ln.pos_code in OFFICE_ONLY_RESTRICTED_POS:
            errors.add("ERR_POS_MISMATCH")

    return payload, tuple(sorted(errors))
