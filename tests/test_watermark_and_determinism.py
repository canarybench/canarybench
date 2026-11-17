"""Tests for canary watermarking, ground-truth invariance, and byte reproducibility."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from private.factory.packs.claims_adjudication.renderer import (
    generate_pack_drop as generate_claims_drop,
)
from private.factory.packs.cre_lease.renderer import generate_pack_drop as generate_cre_drop
from private.factory.packs.customs_cbam.renderer import (
    generate_pack_drop as generate_customs_drop,
)
from private.factory.packs.eu_vat_2027.renderer import generate_pack_drop as generate_eu_vat_drop
from private.factory.packs.med_coding.renderer import generate_pack_drop as generate_med_drop
from private.factory.watermark import CanaryWatermarkEngine, CanaryWatermarkError

from canarybench.core.schemas import Scenario
from canarybench.packs.eu_vat_2027.xml_validator import validate_en16931


def test_uuidv8_o1_encrypt_decrypt_and_tamper_detection() -> None:
    key = hashlib.sha256(b"test-master-key-12345").digest()
    engine = CanaryWatermarkEngine(key)

    uid = engine.mint_encrypted_uuidv8(
        drop_id="2026-W46",
        drop_seq=46,
        subscriber_seq=90210,
        scenario_idx=387,
    )
    assert uid.version == 8

    decoded = engine.decrypt_uuidv8(drop_id="2026-W46", uid=uid)
    assert decoded.drop_seq == 46
    assert decoded.subscriber_seq == 90210
    assert decoded.scenario_idx == 387

    # Flip 1 bit in low byte -> MAC must reject
    tampered = uuid.UUID(int=uid.int ^ 0x01)
    with pytest.raises(CanaryWatermarkError):
        engine.decrypt_uuidv8(drop_id="2026-W46", uid=tampered)

    # Wrong drop_id -> MAC must reject
    with pytest.raises(CanaryWatermarkError):
        engine.decrypt_uuidv8(drop_id="2026-W47", uid=uid)


def test_watermark_ground_truth_invariance_and_channel_extraction_eu_vat(tmp_path: Path) -> None:
    key = hashlib.sha256(b"test-master-key-67890").digest()
    engine = CanaryWatermarkEngine(key)

    dir_a = tmp_path / "sub_a"
    dir_b = tmp_path / "sub_b"

    scenarios_a = generate_eu_vat_drop(
        output_dir=dir_a,
        manifest_name="drop.jsonl",
        count=10,
        drop_id="2026-W46",
        master_seed=99999,
        watermark_engine=engine,
        subscriber_id="acme-corp",
        subscriber_seq=101,
        drop_seq=12,
    )
    scenarios_b = generate_eu_vat_drop(
        output_dir=dir_b,
        manifest_name="drop.jsonl",
        count=10,
        drop_id="2026-W46",
        master_seed=99999,
        watermark_engine=engine,
        subscriber_id="globex-ltd",
        subscriber_seq=202,
        drop_seq=12,
    )

    for idx, (sa, sb) in enumerate(zip(scenarios_a, scenarios_b, strict=True)):
        # Ground truth must be 100% invariant across subscribers
        assert sa.ground_truth.model_dump() == sb.ground_truth.model_dump()

        # Verify UBL XML watermark extraction & EN 16931 validity
        assert sa.ground_truth.ground_truth_ubl_rel_path is not None
        assert sb.ground_truth.ground_truth_ubl_rel_path is not None
        xml_a = (dir_a / sa.ground_truth.ground_truth_ubl_rel_path).read_bytes()
        xml_b = (dir_b / sb.ground_truth.ground_truth_ubl_rel_path).read_bytes()
        assert validate_en16931(xml_a) == []
        assert validate_en16931(xml_b) == []

        uid_a = engine.extract_ubl_uuidv8(xml_a)
        uid_b = engine.extract_ubl_uuidv8(xml_b)
        assert uid_a is not None and uid_b is not None
        assert engine.decrypt_uuidv8(drop_id="2026-W46", uid=uid_a).subscriber_seq == 101
        assert engine.decrypt_uuidv8(drop_id="2026-W46", uid=uid_b).subscriber_seq == 202
        assert engine.decrypt_uuidv8(drop_id="2026-W46", uid=uid_a).scenario_idx == idx

        # Verify PDF watermark extraction when primary artifact is PDF
        art_a = sa.agent_input.artifacts[0]
        if art_a.media_type == "application/pdf":
            pdf_bytes = (dir_a / art_a.rel_path).read_bytes()
            pdf_uid = engine.extract_pdf_uuidv8(pdf_bytes)
            assert pdf_uid is not None
            assert engine.decrypt_uuidv8(drop_id="2026-W46", uid=pdf_uid).subscriber_seq == 101


def test_watermark_invariance_and_attribution_across_new_packs(tmp_path: Path) -> None:
    key = hashlib.sha256(b"multi-pack-wm-key").digest()
    engine = CanaryWatermarkEngine(key)

    generators: tuple[tuple[str, Callable[..., Sequence[Scenario[Any, Any]]]], ...] = (
        ("cre-lease", generate_cre_drop),
        ("customs-cbam", generate_customs_drop),
        ("med-coding", generate_med_drop),
        ("claims-adjudication", generate_claims_drop),
    )
    for slug, gen_fn in generators:
        dir_a = tmp_path / slug / "sub_a"
        dir_b = tmp_path / slug / "sub_b"
        sc_a = gen_fn(
            output_dir=dir_a,
            manifest_name="drop.jsonl",
            count=5,
            drop_id="2026-W46",
            master_seed=77777,
            watermark_engine=engine,
            subscriber_id="sub-alpha",
            subscriber_seq=303,
            drop_seq=9,
        )
        sc_b = gen_fn(
            output_dir=dir_b,
            manifest_name="drop.jsonl",
            count=5,
            drop_id="2026-W46",
            master_seed=77777,
            watermark_engine=engine,
            subscriber_id="sub-beta",
            subscriber_seq=404,
            drop_seq=9,
        )
        for idx, (sa, sb) in enumerate(zip(sc_a, sc_b, strict=True)):
            assert sa.ground_truth.model_dump() == sb.ground_truth.model_dump()
            art_a = sa.agent_input.artifacts[0]
            if art_a.media_type == "application/pdf":
                pdf_uid = engine.extract_pdf_uuidv8((dir_a / art_a.rel_path).read_bytes())
                assert pdf_uid is not None
                decoded = engine.decrypt_uuidv8(drop_id="2026-W46", uid=pdf_uid)
                assert decoded.subscriber_seq == 303
                assert decoded.scenario_idx == idx
            elif art_a.media_type == "application/xml":
                xml_text = (dir_a / art_a.rel_path).read_text(encoding="utf-8")
                m = re.search(r"<!-- cb-wm:([0-9a-f-]+) -->", xml_text)
                if m is not None:
                    decoded = engine.decrypt_uuidv8(
                        drop_id="2026-W46", uid=uuid.UUID(m.group(1))
                    )
                    assert decoded.subscriber_seq == 303
                    assert decoded.scenario_idx == idx


def test_byte_reproducibility_same_seed(tmp_path: Path) -> None:
    key = hashlib.sha256(b"determinism-key").digest()
    engine = CanaryWatermarkEngine(key)

    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"

    for out in (run1, run2):
        generate_eu_vat_drop(
            output_dir=out,
            manifest_name="drop.jsonl",
            count=10,
            drop_id="2026-W46",
            master_seed=123456,
            watermark_engine=engine,
            subscriber_id="sub-det",
            subscriber_seq=77,
            drop_seq=5,
        )

    assert (run1 / "drop.jsonl").read_bytes() == (run2 / "drop.jsonl").read_bytes()
    for p1 in sorted(run1.rglob("*")):
        if p1.is_file():
            rel = p1.relative_to(run1)
            assert p1.read_bytes() == (run2 / rel).read_bytes(), f"Mismatch in {rel}"
