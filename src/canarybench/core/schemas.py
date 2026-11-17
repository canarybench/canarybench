"""Strict Pydantic v2 schemas and exact Decimal utilities for canarybench."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)


def _reject_float_parse_decimal(value: Any) -> Decimal:
    """Validate Decimal input while strictly rejecting Python float, bool, NaN, and Inf."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid Decimal")
    if isinstance(value, float):
        raise ValueError(
            "Float monetary/numeric values are forbidden in canarybench; pass str or Decimal"
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal (NaN/Inf) is forbidden")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("Empty string is not a valid Decimal")
        try:
            parsed = Decimal(stripped)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid Decimal value: {value!r}") from exc
        if not parsed.is_finite():
            raise ValueError("Non-finite Decimal (NaN/Inf) is forbidden")
        return parsed
    raise ValueError(f"Expected str, int, or Decimal; got {type(value).__name__}")


def _serialize_decimal_str(value: Decimal) -> str:
    """Serialize Decimal as fixed-point string without scientific notation."""
    return format(value, "f")


def round_half_up(value: Decimal, places: int = 2) -> Decimal:
    """Round a Decimal deterministically using ROUND_HALF_UP."""
    quantizer = Decimal(10) ** -places
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


StrictDecimal = Annotated[
    Decimal,
    BeforeValidator(_reject_float_parse_decimal),
    PlainSerializer(_serialize_decimal_str, return_type=str, when_used="json"),
]

MoneyDecimal = StrictDecimal
RateDecimal = StrictDecimal


class EngineId(StrEnum):
    """Four horizontal failure-archetype engines shared across domain packs."""

    LEDGER_MATH = "ledger-math"
    DOC_RECONCILE = "doc-reconcile"
    RULE_TRIAGE = "rule-triage"
    WIRE_PROTOCOL = "wire-protocol"


class PackId(StrEnum):
    """Canonical vertical domain packs supported by canarybench."""

    EU_VAT_2027 = "eu-vat-2027"
    CRE_LEASE = "cre-lease"
    CUSTOMS_CBAM = "customs-cbam"
    MED_CODING = "med-coding"
    CLAIMS_ADJUDICATION = "claims-adjudication"


class ArtifactRef(BaseModel):
    """Reference to a rendered document artifact (UBL XML, PDF, JSON/XML wire) inside a drop."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    role: Literal[
        "primary_invoice",
        "credit_note",
        "supporting_doc",
        "ubl_xml",
        "pdf_render",
        "lease_schedule",
        "customs_declaration",
        "claim_payload",
        "policy_schedule",
        "json_wire",
        "xml_wire",
    ]
    media_type: str
    rel_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_size: int = Field(ge=1)
    extracted_text: str | None = None


class ContextAttachment(BaseModel):
    """Supporting business/logistics/regulatory context document shown to the agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    doc_type: Literal[
        "CMR_WAYBILL",
        "LOGISTICS_EMAIL",
        "PURCHASE_ORDER",
        "CUSTOMS_EXPORT_EAD",
        "WAREHOUSE_RECEIPT",
        "VIES_LOOKUP_LOG",
        "LEASE_AMENDMENT",
        "LANDLORD_EMAIL",
        "BOM_MANIFEST",
        "SUPPLIER_ORIGIN_DECL",
        "CBAM_VERIFICATION_REPORT",
        "CLINICAL_NOTE",
        "NCCI_POLICY_BULLETIN",
        "POLICY_ENDORSEMENT",
        "ADJUSTER_REPORT",
        "REPAIR_INVOICE",
    ]
    timestamp_utc: str
    subject_or_title: str
    body_text: str


class AgentInput(BaseModel):
    """Immutable payload containing everything the agent under evaluation may observe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    pack_id: PackId
    engine_id: EngineId
    modality: str
    prompt: str
    artifacts: tuple[ArtifactRef, ...]
    attachments: tuple[ContextAttachment, ...] = ()
    context: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "2.0"


class GroundTruth(BaseModel):
    """Base immutable ground-truth contract; never passed to an AgentAdapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    pack_id: PackId
    engine_id: EngineId
    rubric_version: str
    difficulty_tier: Literal["standard", "adversarial", "edge"]
    trap_tags: tuple[str, ...] = ()


class AgentPrediction(BaseModel):
    """Base structured prediction returned by an AgentAdapter."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    pack_id: PackId
    engine_id: EngineId
    raw_response: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class Scenario[InputT: AgentInput, TruthT: GroundTruth](BaseModel):
    """Complete evaluation scenario pairing observable AgentInput with hidden GroundTruth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    pack_id: PackId
    engine_id: EngineId
    drop_id: str
    agent_input: InputT
    ground_truth: TruthT

    @model_validator(mode="after")
    def _validate_identity_consistency(self) -> Scenario[InputT, TruthT]:
        if (
            self.agent_input.scenario_id != self.scenario_id
            or self.ground_truth.scenario_id != self.scenario_id
        ):
            raise ValueError(
                f"scenario_id mismatch across Scenario ({self.scenario_id}), "
                f"agent_input ({self.agent_input.scenario_id}), "
                f"and ground_truth ({self.ground_truth.scenario_id})"
            )
        if (
            self.agent_input.pack_id != self.pack_id
            or self.ground_truth.pack_id != self.pack_id
        ):
            raise ValueError(
                f"pack_id mismatch across Scenario ({self.pack_id}), "
                f"agent_input ({self.agent_input.pack_id}), "
                f"and ground_truth ({self.ground_truth.pack_id})"
            )
        if (
            self.agent_input.engine_id != self.engine_id
            or self.ground_truth.engine_id != self.engine_id
        ):
            raise ValueError(
                f"engine_id mismatch across Scenario ({self.engine_id}), "
                f"agent_input ({self.agent_input.engine_id}), "
                f"and ground_truth ({self.ground_truth.engine_id})"
            )
        return self


class CheckResult(BaseModel):
    """Single deterministic grading check outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    passed: bool
    weight: StrictDecimal
    score: StrictDecimal
    expected: str | None = None
    actual: str | None = None
    message: str | None = None


class GradeResult(BaseModel):
    """Scenario-level deterministic grading result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str
    pack_id: PackId
    engine_id: EngineId
    passed: bool
    score: StrictDecimal
    hard_fail: bool = False
    hard_fail_reason: str | None = None
    checks: tuple[CheckResult, ...] = ()
    trap_tags: tuple[str, ...] = ()
    difficulty_tier: Literal["standard", "adversarial", "edge"] = "standard"
    modality: str = "unknown"
    error: str | None = None


class BucketMetrics(BaseModel):
    """Aggregated pass rate and mean score for an engine, pack, trap tag, modality, or tier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int
    passed: int
    pass_rate: StrictDecimal
    mean_score: StrictDecimal


class BenchReport(BaseModel):
    """Aggregated deterministic evaluation report across one or more packs and engines."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: str
    pack_id: PackId | Literal["multi-pack"]
    pack_ids: tuple[PackId, ...]
    engine_ids: tuple[EngineId, ...]
    pack_versions: dict[str, str]
    drop_id: str
    canary_digest: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_scenarios: int
    passed_scenarios: int
    pass_rate: StrictDecimal
    mean_score: StrictDecimal
    breakdown_by_engine: dict[str, BucketMetrics] = Field(default_factory=dict)
    breakdown_by_pack: dict[str, BucketMetrics] = Field(default_factory=dict)
    breakdown_by_trap: dict[str, BucketMetrics] = Field(default_factory=dict)
    breakdown_by_tier: dict[str, BucketMetrics] = Field(default_factory=dict)
    breakdown_by_modality: dict[str, BucketMetrics] = Field(default_factory=dict)
    results: tuple[GradeResult, ...]


SuiteReport = BenchReport
