"""Tests for all 5 packs, 4 engines, OpenAICompatibleAdapter, Typer CLI, and public drops."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from typer.testing import CliRunner

from canarybench.cli import app
from canarybench.core.adapters import OpenAICompatibleAdapter
from canarybench.core.base import BasePack
from canarybench.core.registry import default_pack_registry
from canarybench.core.schemas import EngineId, PackId, Scenario
from canarybench.packs.eu_vat_2027.pack import EuVat2027Pack
from canarybench.packs.eu_vat_2027.schemas import (
    EuVatPrediction,
    VatBreakdownItem,
    VatCategoryCode,
    VatLineItem,
)
from canarybench.packs.eu_vat_2027.xml_validator import validate_en16931

runner = CliRunner()


def _gt_to_perfect_prediction(
    pack: BasePack[Any, Any, Any],
    *,
    engine_id: EngineId | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    pred_cls = pack.prediction_schema()
    preds: list[dict[str, object]] = []
    for sc in pack.load_scenarios(engine_id=engine_id, limit=limit):
        gt_dict = json.loads(sc.ground_truth.model_dump_json())
        gt_dict["scenario_id"] = sc.scenario_id
        gt_dict["pack_id"] = sc.pack_id.value
        gt_dict["engine_id"] = sc.engine_id.value
        allowed_fields = set(pred_cls.model_fields.keys())
        filtered = {k: v for k, v in gt_dict.items() if k in allowed_fields}
        pred = pred_cls.model_validate(filtered)
        preds.append(json.loads(pred.model_dump_json()))
    return preds


def test_public_25_eu_vat_all_valid_en16931_and_5_regimes_covered() -> None:
    pack = EuVat2027Pack()
    scenarios = pack.load_scenarios()
    assert len(scenarios) == 25

    regimes = {s.ground_truth.regime for s in scenarios}
    assert len(regimes) == 5

    data_root = pack.default_dataset_path().parent
    for s in scenarios:
        assert s.ground_truth.ground_truth_ubl_rel_path is not None
        xml_path = data_root / s.ground_truth.ground_truth_ubl_rel_path
        assert xml_path.exists()
        assert validate_en16931(xml_path.read_text(encoding="utf-8")) == []
        for art in s.agent_input.artifacts:
            assert (data_root / art.rel_path).exists()


def test_all_5_packs_public_datasets_artifacts_and_perfect_grading() -> None:
    expected_counts = {
        PackId.EU_VAT_2027: 25,
        PackId.CRE_LEASE: 10,
        PackId.CUSTOMS_CBAM: 10,
        PackId.MED_CODING: 10,
        PackId.CLAIMS_ADJUDICATION: 10,
    }
    for pack_id, exp_count in expected_counts.items():
        pack = default_pack_registry.get(pack_id)
        scenarios: list[Scenario[Any, Any]] = pack.load_scenarios()
        assert len(scenarios) == exp_count
        data_root = pack.default_dataset_path().parent
        pred_cls = pack.prediction_schema()
        perfect_dicts = _gt_to_perfect_prediction(pack)

        for sc, pred_dict in zip(scenarios, perfect_dicts, strict=True):
            for art in sc.agent_input.artifacts:
                assert (data_root / art.rel_path).exists()
            assert pack.validate_ground_truth_artifact(sc, data_root) == []
            pred = pred_cls.model_validate(pred_dict)
            res = pack.grade(sc, pred)
            assert res.passed is True, f"{pack_id.value}:{sc.scenario_id} failed: {res.checks}"
            assert res.score == Decimal("1.0000")


def test_grader_hard_fail_gate_blocks_zero_vat_category_gaming() -> None:
    pack = EuVat2027Pack()
    target = next(
        s
        for s in pack.load_scenarios()
        if s.ground_truth.vat_category_code
        in {VatCategoryCode.INTRA_COMMUNITY, VatCategoryCode.REVERSE_CHARGE}
    )
    gt = target.ground_truth
    wrong_pred = EuVatPrediction(
        scenario_id=target.scenario_id,
        pack_id=target.pack_id,
        engine_id=target.engine_id,
        regime=gt.regime,
        document_type_code=gt.document_type_code,
        taxing_member_state=gt.taxing_member_state,
        document_currency=gt.document_currency,
        tax_currency=gt.tax_currency,
        ecb_units_per_eur=gt.ecb_units_per_eur,
        vat_category_code=VatCategoryCode.EXEMPT,
        legal_basis_code=gt.legal_basis_code,
        reverse_charge=gt.reverse_charge,
        line_extension_total=gt.line_extension_total,
        tax_exclusive_total=gt.tax_exclusive_total,
        total_vat_amount=gt.total_vat_amount,
        total_vat_amount_eur=gt.total_vat_amount_eur,
        tax_inclusive_total=gt.tax_inclusive_total,
        payable_amount=gt.payable_amount,
        line_items=[
            VatLineItem(
                line_id=ln.line_id,
                vat_category_code=VatCategoryCode.EXEMPT,
                vat_rate_pct=ln.vat_rate_pct,
                net_amount=ln.net_amount,
            )
            for ln in gt.line_items
        ],
        vat_breakdown=[
            VatBreakdownItem(
                vat_category_code=VatCategoryCode.EXEMPT,
                vat_rate_pct=b.vat_rate_pct,
                taxable_amount=b.taxable_amount,
                tax_amount=b.tax_amount,
            )
            for b in gt.vat_breakdown
        ],
    )
    res = pack.grade(target, wrong_pred)
    assert res.passed is False
    assert res.hard_fail is True
    assert res.score == Decimal("0.0000")


def test_cli_list_engines_packs_run_grade_and_inspect(tmp_path: Path) -> None:
    res_eng = runner.invoke(app, ["list-engines", "--json"])
    assert res_eng.exit_code == 0
    engines = json.loads(res_eng.stdout)
    assert {e["engine_id"] for e in engines} == {e.value for e in EngineId}

    res_list = runner.invoke(app, ["list-packs", "--json"])
    assert res_list.exit_code == 0
    listed = json.loads(res_list.stdout)
    assert {p["pack_id"] for p in listed} == {p.value for p in PackId}

    res_filtered = runner.invoke(app, ["list-packs", "--engine", "wire-protocol", "--json"])
    assert res_filtered.exit_code == 0
    filtered_ids = {p["pack_id"] for p in json.loads(res_filtered.stdout)}
    assert filtered_ids == {"eu-vat-2027", "med-coding"}

    # Naive baseline run with fail-under=0.90 should exit 1 across packs
    for pid in PackId:
        res_naive = runner.invoke(
            app, ["run", "--pack", pid.value, "--baseline-mock", "naive", "--fail-under", "0.9"]
        )
        assert res_naive.exit_code == 1

    # Multi-pack engine-filtered run (`--engine ledger-math`)
    engine_report_path = tmp_path / "ledger_math_report.json"
    res_engine_run = runner.invoke(
        app,
        [
            "run",
            "--engine",
            "ledger-math",
            "--baseline-mock",
            "naive",
            "--output",
            str(engine_report_path),
        ],
    )
    assert res_engine_run.exit_code == 0
    eng_report = json.loads(engine_report_path.read_text(encoding="utf-8"))
    assert eng_report["pack_id"] == "multi-pack"
    assert set(eng_report["engine_ids"]) == {"ledger-math"}
    assert len(eng_report["pack_ids"]) == 4

    # Pack + engine combined filter
    cre_doc_report = tmp_path / "cre_doc.json"
    res_combo = runner.invoke(
        app,
        [
            "run",
            "--pack",
            "cre-lease",
            "--engine",
            "doc-reconcile",
            "--baseline-mock",
            "naive",
            "--output",
            str(cre_doc_report),
        ],
    )
    assert res_combo.exit_code == 0
    combo_data = json.loads(cre_doc_report.read_text(encoding="utf-8"))
    assert all(r["engine_id"] == "doc-reconcile" for r in combo_data["results"])

    # Perfect predictions file graded via `canarybench grade` should pass 100%
    pack = EuVat2027Pack()
    preds_path = tmp_path / "perfect_preds.json"
    preds_path.write_text(json.dumps(_gt_to_perfect_prediction(pack)), encoding="utf-8")
    report_path = tmp_path / "report.json"

    res_grade = runner.invoke(
        app,
        [
            "grade",
            "--pack",
            "eu-vat-2027",
            "--predictions",
            str(preds_path),
            "--output",
            str(report_path),
            "--fail-under",
            "1.0",
        ],
    )
    assert res_grade.exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["pass_rate"] == "1.0000"
    assert report["passed_scenarios"] == 25

    res_inspect_vat = runner.invoke(
        app,
        ["inspect", "--pack", "eu-vat-2027", "--scenario", "EU-VAT-0001", "--validate-xml"],
    )
    assert res_inspect_vat.exit_code == 0
    assert "Ground-truth wire validation PASSED" in res_inspect_vat.stdout

    res_inspect_med = runner.invoke(
        app,
        ["inspect", "--pack", "med-coding", "--scenario", "MED-0001", "--validate-xml"],
    )
    assert res_inspect_med.exit_code == 0
    assert "Ground-truth wire validation PASSED" in res_inspect_med.stdout


def test_openai_compatible_adapter_with_mock_http(monkeypatch: object) -> None:
    pack = EuVat2027Pack()
    sc = pack.load_scenarios(limit=1)[0]
    gt = sc.ground_truth
    payload_dict = _gt_to_perfect_prediction(pack, limit=1)[0]
    response_body = {"choices": [{"message": {"content": json.dumps(payload_dict)}}]}

    def _mock_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json=response_body,
            request=httpx.Request("POST", "https://mock/v1/chat/completions"),
        )

    monkeypatch.setattr(httpx.Client, "post", _mock_post)  # type: ignore[attr-defined]
    adapter = OpenAICompatibleAdapter(
        base_url="https://mock/v1", model="test-model", api_key="sk-test"
    )
    pred = adapter.predict(sc.agent_input, EuVatPrediction)
    assert pred.total_vat_amount == gt.total_vat_amount
    assert pack.grade(sc, pred).passed is True
