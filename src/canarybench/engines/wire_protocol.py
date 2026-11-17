"""Wire-Protocol engine: strict schema, code-list, and regulatory payload checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from canarybench.core.base import BaseEngine, EngineMetadata
from canarybench.core.schemas import CheckResult, EngineId


class WireProtocolEngine(BaseEngine):
    """Deterministic checks for strict wire schemas, code lists, and payload conformance."""

    metadata: ClassVar[EngineMetadata] = EngineMetadata(
        engine_id=EngineId.WIRE_PROTOCOL,
        version="0.1.0",
        display_name="Wire Protocol Engine",
        description=(
            "Strict schema, regulatory code-list, XML/JSON payload structural ordering, "
            "and business-rule conformance verification."
        ),
        failure_archetype="Strict Schema & Regulatory Payloads",
        primitive_check_ids=(
            "payload_violations",
            "protocol_codes",
            "strict_schema",
        ),
    )

    def primitive_checks(self) -> tuple[str, ...]:
        return self.metadata.primitive_check_ids

    @staticmethod
    def check_payload_violations(
        check_id: str,
        *,
        violations: Sequence[str],
        weight: Decimal,
    ) -> CheckResult:
        passed = len(violations) == 0
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected="0 violations",
            actual=f"{len(violations)} violations",
            message="; ".join(violations[:5]) if violations else None,
        )

    @staticmethod
    def check_protocol_codes(
        check_id: str,
        *,
        expected_codes: Mapping[str, str | None],
        actual_codes: Mapping[str, str | None],
        weight: Decimal,
        message: str | None = None,
    ) -> CheckResult:
        passed = set(expected_codes.keys()) == set(actual_codes.keys()) and all(
            expected_codes[k] == actual_codes[k] for k in expected_codes
        )
        exp_str = ",".join(f"{k}={v}" for k, v in expected_codes.items())
        act_str = ",".join(f"{k}={v}" for k, v in actual_codes.items())
        return CheckResult(
            check_id=check_id,
            passed=passed,
            weight=weight,
            score=weight if passed else Decimal("0.00"),
            expected=exp_str,
            actual=act_str,
            message=message,
        )

    @staticmethod
    def check_strict_schema(
        check_id: str,
        *,
        model_cls: type[BaseModel],
        payload: Mapping[str, Any],
        weight: Decimal,
    ) -> CheckResult:
        try:
            model_cls.model_validate(payload)
            return CheckResult(
                check_id=check_id,
                passed=True,
                weight=weight,
                score=weight,
                expected=model_cls.__name__,
                actual=model_cls.__name__,
            )
        except ValidationError as exc:
            return CheckResult(
                check_id=check_id,
                passed=False,
                weight=weight,
                score=Decimal("0.00"),
                expected=model_cls.__name__,
                actual="ValidationError",
                message=str(exc),
            )
