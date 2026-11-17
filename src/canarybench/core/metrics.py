"""Deterministic metric aggregation for BenchReport generation."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal

from canarybench.core.schemas import (
    BenchReport,
    BucketMetrics,
    EngineId,
    GradeResult,
    PackId,
    round_half_up,
)


def _compute_bucket(items: Sequence[GradeResult]) -> BucketMetrics:
    count = len(items)
    if count == 0:
        return BucketMetrics(
            count=0,
            passed=0,
            pass_rate=Decimal("0.0000"),
            mean_score=Decimal("0.0000"),
        )
    passed_count = sum(1 for item in items if item.passed)
    total_score = sum((item.score for item in items), start=Decimal("0"))
    denom = Decimal(count)
    return BucketMetrics(
        count=count,
        passed=passed_count,
        pass_rate=round_half_up(Decimal(passed_count) / denom, 4),
        mean_score=round_half_up(total_score / denom, 4),
    )


def build_bench_report(
    *,
    pack_ids: Sequence[PackId],
    engine_ids: Sequence[EngineId],
    pack_versions: Mapping[str, str],
    drop_id: str,
    canary_digest: str | None,
    results: Sequence[GradeResult],
) -> BenchReport:
    """Compute exact Decimal metrics across engines, packs, traps, tiers, and modalities."""
    overall = _compute_bucket(results)

    by_engine: dict[str, list[GradeResult]] = defaultdict(list)
    by_pack: dict[str, list[GradeResult]] = defaultdict(list)
    by_trap: dict[str, list[GradeResult]] = defaultdict(list)
    by_tier: dict[str, list[GradeResult]] = defaultdict(list)
    by_modality: dict[str, list[GradeResult]] = defaultdict(list)

    for res in results:
        by_engine[res.engine_id.value].append(res)
        by_pack[res.pack_id.value].append(res)
        by_tier[res.difficulty_tier].append(res)
        by_modality[res.modality].append(res)
        for tag in res.trap_tags:
            by_trap[tag].append(res)

    unique_packs = tuple(dict.fromkeys(pack_ids))
    unique_engines = tuple(dict.fromkeys(engine_ids))
    top_pack_id: PackId | str
    if len(unique_packs) == 1:
        top_pack_id = unique_packs[0]
    else:
        top_pack_id = "multi-pack"

    pack_key = ",".join(p.value for p in unique_packs)
    engine_key = ",".join(e.value for e in unique_engines)
    report_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"canarybench:{pack_key}:{engine_key}:{drop_id}:{len(results)}:{overall.pass_rate}",
    )

    return BenchReport(
        report_id=str(report_uuid),
        pack_id=top_pack_id,  # type: ignore[arg-type]
        pack_ids=unique_packs,
        engine_ids=unique_engines,
        pack_versions=dict(pack_versions),
        drop_id=drop_id,
        canary_digest=canary_digest,
        total_scenarios=overall.count,
        passed_scenarios=overall.passed,
        pass_rate=overall.pass_rate,
        mean_score=overall.mean_score,
        breakdown_by_engine={k: _compute_bucket(by_engine[k]) for k in sorted(by_engine)},
        breakdown_by_pack={k: _compute_bucket(by_pack[k]) for k in sorted(by_pack)},
        breakdown_by_trap={k: _compute_bucket(by_trap[k]) for k in sorted(by_trap)},
        breakdown_by_tier={k: _compute_bucket(by_tier[k]) for k in sorted(by_tier)},
        breakdown_by_modality={
            k: _compute_bucket(by_modality[k]) for k in sorted(by_modality)
        },
        results=tuple(results),
    )


build_suite_report = build_bench_report
