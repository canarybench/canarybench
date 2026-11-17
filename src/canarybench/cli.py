"""Typer + Rich CLI entrypoint for canarybench."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from canarybench.core.adapters import (
    AgentAdapter,
    FilePredictionsAdapter,
    OpenAICompatibleAdapter,
)
from canarybench.core.base import BasePack
from canarybench.core.registry import (
    EngineNotFoundError,
    PackNotFoundError,
    default_engine_registry,
    default_pack_registry,
)
from canarybench.core.runner import BenchmarkRunner
from canarybench.core.schemas import BenchReport, BucketMetrics, EngineId

app = typer.Typer(
    name="canarybench",
    help="Contamination-free deterministic AI evaluation harness.",
    no_args_is_help=True,
)
err_console = Console(stderr=True)
out_console = Console()


def _parse_engine_id(engine: str | None) -> EngineId | None:
    if engine is None:
        return None
    try:
        default_engine_registry.get(engine)
        return EngineId(engine)
    except (EngineNotFoundError, ValueError) as exc:
        available = ", ".join(e.engine_id.value for e in default_engine_registry.list_engines())
        err_console.print(f"[red]Unknown engine '{engine}'. Available: {available}[/red]")
        raise typer.Exit(code=2) from exc


def _resolve_packs(
    *,
    pack_id: str | None,
    engine_id: EngineId | None,
) -> list[BasePack[Any, Any, Any]]:
    if pack_id is None and engine_id is None:
        err_console.print("[red]Specify at least one of --pack or --engine.[/red]")
        raise typer.Exit(code=2)

    if pack_id is not None:
        try:
            pack = default_pack_registry.get(pack_id)
        except PackNotFoundError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        if engine_id is not None and engine_id not in pack.metadata.supported_engines:
            supported = ", ".join(e.value for e in pack.metadata.supported_engines)
            err_console.print(
                f"[red]Pack '{pack_id}' does not support engine '{engine_id.value}'. "
                f"Supported: {supported}[/red]"
            )
            raise typer.Exit(code=2)
        return [pack]

    assert engine_id is not None
    packs = default_pack_registry.packs_for_engine(engine_id)
    if not packs:
        err_console.print(
            f"[red]No registered packs support engine '{engine_id.value}'.[/red]"
        )
        raise typer.Exit(code=2)
    return packs


def _render_bucket_table(
    *,
    title: str,
    key_col: str,
    key_style: str,
    buckets: dict[str, BucketMetrics],
    console: Console,
) -> None:
    if not buckets:
        return
    tbl = Table(title=title)
    tbl.add_column(key_col, style=key_style)
    tbl.add_column("Passed / Total", justify="right")
    tbl.add_column("Pass Rate", justify="right")
    tbl.add_column("Mean Score", justify="right")
    for key, bm in buckets.items():
        tbl.add_row(
            key,
            f"{bm.passed}/{bm.count}",
            f"{(bm.pass_rate * Decimal('100')):.1f}%",
            f"{bm.mean_score:.4f}",
        )
    console.print(tbl)


def _render_report(report: BenchReport, *, console: Console) -> None:
    pack_label = ", ".join(p.value for p in report.pack_ids)
    engine_label = ", ".join(e.value for e in report.engine_ids)
    summary = Table(title=f"CanaryBench Report: {pack_label} ({report.drop_id})")
    summary.add_column("Metric", style="bold cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Packs", pack_label)
    summary.add_row("Engines", engine_label)
    summary.add_row("Total Scenarios", str(report.total_scenarios))
    summary.add_row("Passed", str(report.passed_scenarios))
    summary.add_row("Pass Rate", f"{(report.pass_rate * Decimal('100')):.2f}%")
    summary.add_row("Mean Score", f"{report.mean_score:.4f}")
    hard_fails = sum(1 for r in report.results if r.hard_fail)
    summary.add_row("Hard-Fail Gate Violations", str(hard_fails))
    console.print(summary)

    _render_bucket_table(
        title="Breakdown by Engine",
        key_col="Engine",
        key_style="cyan",
        buckets=report.breakdown_by_engine,
        console=console,
    )
    _render_bucket_table(
        title="Breakdown by Pack",
        key_col="Pack",
        key_style="green",
        buckets=report.breakdown_by_pack,
        console=console,
    )
    _render_bucket_table(
        title="Breakdown by Modality",
        key_col="Modality",
        key_style="magenta",
        buckets=report.breakdown_by_modality,
        console=console,
    )
    _render_bucket_table(
        title="Breakdown by Trap / Regime Tag",
        key_col="Tag",
        key_style="yellow",
        buckets=report.breakdown_by_trap,
        console=console,
    )


def _check_fail_under(report: BenchReport, fail_under: float | None) -> None:
    if fail_under is None:
        return
    threshold = Decimal(str(fail_under))
    if report.pass_rate < threshold:
        err_console.print(
            f"[red]Pass rate {report.pass_rate:.4f} is below --fail-under {threshold:.4f}[/red]"
        )
        raise typer.Exit(code=1)


@app.command("list-engines")
def list_engines(
    json_output: bool = typer.Option(False, "--json", help="Emit engine metadata as JSON."),
) -> None:
    """List the registered horizontal failure-archetype engines."""
    engines = default_engine_registry.list_engines()
    if json_output:
        payload = [e.model_dump(mode="json") for e in engines]
        typer.echo(json.dumps(payload, indent=2))
        return

    table = Table(title="Registered CanaryBench Engines")
    table.add_column("Engine ID", style="bold cyan")
    table.add_column("Version")
    table.add_column("Failure Archetype")
    table.add_column("Description")
    for e in engines:
        table.add_row(
            e.engine_id.value,
            e.version,
            e.failure_archetype,
            e.description,
        )
    out_console.print(table)


@app.command("list-packs")
def list_packs(
    engine: str | None = typer.Option(
        None, "--engine", help="Filter packs supporting this engine ID."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit pack metadata as JSON."),
) -> None:
    """List all available domain packs discovered via registry and entry points."""
    engine_id = _parse_engine_id(engine)
    packs = default_pack_registry.list_packs(engine_id=engine_id)
    if json_output:
        payload = [p.model_dump(mode="json") for p in packs]
        typer.echo(json.dumps(payload, indent=2))
        return

    table = Table(title="Registered CanaryBench Packs")
    table.add_column("Pack ID", style="bold green")
    table.add_column("Version")
    table.add_column("Engines")
    table.add_column("Modalities")
    table.add_column("Description")
    for p in packs:
        table.add_row(
            p.pack_id.value,
            p.version,
            ", ".join(e.value for e in p.supported_engines),
            ", ".join(p.supported_modalities),
            p.description,
        )
    out_console.print(table)


def _build_baseline_resolver(
    packs: Sequence[BasePack[Any, Any, Any]],
    baseline_mock: str,
) -> dict[str, AgentAdapter]:
    resolved: dict[str, AgentAdapter] = {}
    for pack in packs:
        adapter = pack.baseline_adapter(baseline_mock)
        if adapter is None:
            err_console.print(
                f"[red]--baseline-mock {baseline_mock!r} is not implemented for pack "
                f"'{pack.metadata.pack_id.value}'.[/red]"
            )
            raise typer.Exit(code=2)
        resolved[pack.metadata.pack_id.value] = adapter
    return resolved


@app.command("run")
def run_benchmark(
    pack_id: str | None = typer.Option(None, "--pack", help="Domain pack ID (e.g. eu-vat-2027)."),
    engine: str | None = typer.Option(
        None, "--engine", help="Failure-archetype engine ID (e.g. ledger-math)."
    ),
    dataset: Path | None = typer.Option(None, "--dataset", help="Custom JSONL drop manifest."),
    predictions: Path | None = typer.Option(
        None, "--predictions", help="Evaluate offline JSON/JSONL predictions."
    ),
    baseline_mock: str | None = typer.Option(
        None, "--baseline-mock", help="Run deterministic offline baseline (e.g. 'naive')."
    ),
    endpoint: str | None = typer.Option(
        None,
        "--endpoint",
        help="OpenAI-compatible base URL (or set OPENAI_BASE_URL).",
    ),
    model: str | None = typer.Option(None, "--model", help="Model name for --endpoint."),
    api_key: str | None = typer.Option(
        None, "--api-key", help="API key (or set OPENAI_API_KEY)."
    ),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Evaluate first N scenarios."),
    offset: int = typer.Option(0, "--offset", min=0, help="Skip first K scenarios."),
    output: Path | None = typer.Option(None, "--output", help="Write BenchReport JSON to path."),
    save_predictions: Path | None = typer.Option(
        None, "--save-predictions", help="Save model predictions as JSONL."
    ),
    fail_under: float | None = typer.Option(
        None, "--fail-under", min=0.0, max=1.0, help="Exit 1 if pass_rate < threshold."
    ),
) -> None:
    """Run one or more domain packs filtered by --pack and/or --engine."""
    engine_id = _parse_engine_id(engine)
    packs = _resolve_packs(pack_id=pack_id, engine_id=engine_id)

    if len(packs) > 1 and dataset is not None:
        err_console.print("[red]--dataset cannot be used on a multi-pack --engine run.[/red]")
        raise typer.Exit(code=2)

    mode_count = sum(
        [
            predictions is not None,
            baseline_mock is not None,
            model is not None or endpoint is not None,
        ]
    )
    if mode_count != 1:
        err_console.print(
            "[red]Specify exactly one execution mode: "
            "--predictions, --baseline-mock, or --model/--endpoint.[/red]"
        )
        raise typer.Exit(code=2)

    if predictions is not None:
        runner = BenchmarkRunner(packs, FilePredictionsAdapter(predictions))
    elif baseline_mock is not None:
        by_pack = _build_baseline_resolver(packs, baseline_mock)
        runner = BenchmarkRunner(
            packs,
            adapter_resolver=lambda p: by_pack[p.metadata.pack_id.value],
        )
    else:
        resolved_endpoint = endpoint or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not model:
            err_console.print("[red]--model is required when using --endpoint.[/red]")
            raise typer.Exit(code=2)
        runner = BenchmarkRunner(
            packs,
            OpenAICompatibleAdapter(
                base_url=resolved_endpoint,
                model=model,
                api_key=resolved_key,
            ),
        )

    report = runner.run(
        engine_id=engine_id,
        dataset_path=dataset,
        limit=limit,
        offset=offset,
        save_predictions_path=save_predictions,
    )

    _render_report(report, console=err_console if output else out_console)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        err_console.print(f"[green]Wrote report to {output}[/green]")

    _check_fail_under(report, fail_under)


@app.command("grade")
def grade_predictions(
    pack_id: str | None = typer.Option(None, "--pack", help="Domain pack ID."),
    engine: str | None = typer.Option(None, "--engine", help="Filter by engine ID."),
    predictions: Path = typer.Option(..., "--predictions", help="JSON or JSONL predictions file."),
    dataset: Path | None = typer.Option(None, "--dataset", help="Custom JSONL drop manifest."),
    limit: int | None = typer.Option(None, "--limit", min=1),
    offset: int = typer.Option(0, "--offset", min=0),
    output: Path | None = typer.Option(None, "--output", help="Write BenchReport JSON to path."),
    verbose: bool = typer.Option(False, "--verbose", help="Print failing check diffs."),
    fail_under: float | None = typer.Option(None, "--fail-under", min=0.0, max=1.0),
) -> None:
    """Deterministically grade a local JSON/JSONL predictions file offline."""
    engine_id = _parse_engine_id(engine)
    packs = _resolve_packs(pack_id=pack_id, engine_id=engine_id)
    if len(packs) > 1 and dataset is not None:
        err_console.print("[red]--dataset cannot be used on a multi-pack --engine grade run.[/red]")
        raise typer.Exit(code=2)

    adapter = FilePredictionsAdapter(predictions)
    runner = BenchmarkRunner(packs, adapter)
    report = runner.run(engine_id=engine_id, dataset_path=dataset, limit=limit, offset=offset)
    _render_report(report, console=out_console)

    if verbose:
        for res in report.results:
            if not res.passed:
                failed = [
                    f"{c.check_id}(exp={c.expected}, act={c.actual})"
                    for c in res.checks
                    if not c.passed
                ]
                err_text = f" error={res.error}" if res.error else ""
                out_console.print(
                    f"[red]FAIL {res.scenario_id} "
                    f"[{res.pack_id.value}/{res.engine_id.value}][/red] "
                    f"hard_fail={res.hard_fail} [{', '.join(failed)}]{err_text}"
                )

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    _check_fail_under(report, fail_under)


@app.command("inspect")
def inspect_scenario(
    pack_id: str = typer.Option(..., "--pack", help="Domain pack ID."),
    scenario_id: str = typer.Option(..., "--scenario", help="Scenario ID to inspect."),
    dataset: Path | None = typer.Option(None, "--dataset", help="Custom JSONL drop manifest."),
    hide_ground_truth: bool = typer.Option(False, "--hide-ground-truth"),
    validate_xml: bool = typer.Option(
        False,
        "--validate-xml",
        help="Validate the scenario's ground-truth regulatory wire artifact.",
    ),
) -> None:
    """Inspect a single scenario's input artifacts, context attachments, and ground truth."""
    try:
        pack = default_pack_registry.get(pack_id)
    except PackNotFoundError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    resolved_dataset = dataset or pack.default_dataset_path()
    scenarios = pack.load_scenarios(resolved_dataset)
    match: Any = next((s for s in scenarios if s.scenario_id == scenario_id), None)
    if match is None:
        err_console.print(
            f"[red]Scenario '{scenario_id}' not found in {resolved_dataset}[/red]"
        )
        raise typer.Exit(code=2)

    out_console.print(
        Panel(
            f"Scenario: [bold]{match.scenario_id}[/bold] | "
            f"Pack: {match.pack_id.value} | Engine: {match.engine_id.value} | "
            f"Drop: {match.drop_id}\n"
            f"Modality: {match.agent_input.modality} | "
            f"Artifacts: {len(match.agent_input.artifacts)} | "
            f"Attachments: {len(match.agent_input.attachments)}",
            title="AgentInput Summary",
        )
    )
    for art in match.agent_input.artifacts:
        out_console.print(
            f"  • Artifact [{art.role}] {art.media_type} -> {art.rel_path} ({art.byte_size} bytes)"
        )
    for att in match.agent_input.attachments:
        out_console.print(
            Panel(
                att.body_text,
                title=f"Attachment {att.doc_id} [{att.doc_type}] ({att.timestamp_utc})",
            )
        )

    if not hide_ground_truth:
        out_console.print(
            Panel(
                match.ground_truth.model_dump_json(indent=2),
                title="GroundTruth",
            )
        )

    if validate_xml:
        errors = pack.validate_ground_truth_artifact(match, resolved_dataset.parent)
        if errors:
            for e in errors:
                err_console.print(f"[red]VALIDATION ERROR: {e}[/red]")
            raise typer.Exit(code=1)
        out_console.print(
            f"[green]Ground-truth wire validation PASSED: {match.scenario_id}[/green]"
        )
