"""Tests for StrictDecimal, Pydantic v2 serialization, and Engine/Pack registries."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from canarybench.core.base import BaseEngine, BasePack
from canarybench.core.registry import (
    EngineNotFoundError,
    EngineRegistrationError,
    EngineRegistry,
    PackNotFoundError,
    PackRegistrationError,
    PackRegistry,
)
from canarybench.core.schemas import EngineId, PackId, StrictDecimal
from canarybench.packs.eu_vat_2027.schemas import (
    EuVatPrediction,
    EuVatRegime,
    VatBreakdownItem,
    VatCategoryCode,
    VatDirectiveArticle,
    VatLineItem,
)


class _MoneyBox(BaseModel):
    amount: StrictDecimal


def test_strict_decimal_rejects_float_bool_nan_inf() -> None:
    for bad in (19.99, 0.0, True, False, "NaN", "Infinity", "-inf", "", "abc"):
        with pytest.raises(ValidationError):
            _MoneyBox.model_validate({"amount": bad})


def test_strict_decimal_serializes_fixed_point_strings() -> None:
    box = _MoneyBox(amount=Decimal("1250.50"))
    raw = box.model_dump_json()
    parsed = json.loads(raw)
    assert parsed["amount"] == "1250.50"
    assert isinstance(parsed["amount"], str)

    sci = _MoneyBox(amount=Decimal("1E+3"))
    assert json.loads(sci.model_dump_json())["amount"] == "1000"


def test_eu_vat_prediction_round_trip() -> None:
    pred = EuVatPrediction(
        scenario_id="EU-VAT-0001",
        pack_id=PackId.EU_VAT_2027,
        engine_id=EngineId.WIRE_PROTOCOL,
        regime=EuVatRegime.INTRA_COMMUNITY_GOODS,
        document_type_code="380",
        taxing_member_state="DE",
        document_currency="EUR",
        tax_currency=None,
        ecb_units_per_eur=None,
        vat_category_code=VatCategoryCode.INTRA_COMMUNITY,
        legal_basis_code=VatDirectiveArticle.ART_138_1,
        reverse_charge=False,
        line_extension_total=Decimal("1000.00"),
        tax_exclusive_total=Decimal("1000.00"),
        total_vat_amount=Decimal("0.00"),
        total_vat_amount_eur=Decimal("0.00"),
        tax_inclusive_total=Decimal("1000.00"),
        payable_amount=Decimal("1000.00"),
        line_items=[
            VatLineItem(
                line_id="1",
                vat_category_code=VatCategoryCode.INTRA_COMMUNITY,
                vat_rate_pct=Decimal("0.00"),
                net_amount=Decimal("1000.00"),
            )
        ],
        vat_breakdown=[
            VatBreakdownItem(
                vat_category_code=VatCategoryCode.INTRA_COMMUNITY,
                vat_rate_pct=Decimal("0.00"),
                taxable_amount=Decimal("1000.00"),
                tax_amount=Decimal("0.00"),
            )
        ],
    )
    dumped = pred.model_dump_json()
    reloaded = EuVatPrediction.model_validate_json(dumped)
    assert reloaded == pred


def test_engine_and_pack_registries_discover_all_and_reject_bad_plugins() -> None:
    engine_reg = EngineRegistry()
    engines = engine_reg.list_engines()
    assert {e.engine_id for e in engines} == set(EngineId)
    for eid in EngineId:
        assert isinstance(engine_reg.get(eid), BaseEngine)

    with pytest.raises(EngineNotFoundError):
        engine_reg.get("nonexistent-engine")

    with pytest.raises(EngineRegistrationError):
        engine_reg.register(object)  # type: ignore[arg-type]

    pack_reg = PackRegistry()
    packs = pack_reg.list_packs()
    assert {p.pack_id for p in packs} == set(PackId)
    for pid in PackId:
        assert isinstance(pack_reg.get(pid), BasePack)

    # Filtering by engine returns only compatible packs
    wire_packs = pack_reg.list_packs(engine_id=EngineId.WIRE_PROTOCOL)
    assert {p.pack_id for p in wire_packs} == {PackId.EU_VAT_2027, PackId.MED_CODING}

    doc_packs = pack_reg.list_packs(engine_id=EngineId.DOC_RECONCILE)
    assert {p.pack_id for p in doc_packs} == {PackId.EU_VAT_2027, PackId.CRE_LEASE}

    with pytest.raises(PackNotFoundError):
        pack_reg.get("nonexistent-pack")

    with pytest.raises(PackRegistrationError):
        pack_reg.register(object)  # type: ignore[arg-type]
