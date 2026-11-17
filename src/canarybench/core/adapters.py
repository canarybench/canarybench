"""Agent adapters for OpenAI-compatible endpoints, prediction files, and baselines."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, TypeVar

import httpx

from canarybench.core.schemas import AgentInput, AgentPrediction

PredT = TypeVar("PredT", bound=AgentPrediction)


class AgentAdapter(Protocol):
    """Contract for any agent, API endpoint, or local prediction source."""

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        """Produce a structured prediction strictly from AgentInput."""
        ...


class PredictionMissingError(KeyError):
    """Raised when a scenario_id is absent from a pre-computed predictions file."""


class FilePredictionsAdapter:
    """Offline adapter serving predictions from a local JSON or JSONL file."""

    def __init__(self, predictions_path: Path) -> None:
        self.predictions_path = predictions_path
        self._by_id: dict[str, dict[str, Any]] = self._load_file(predictions_path)

    @staticmethod
    def _load_file(path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"Predictions file not found: {path}")
        raw_text = path.read_text(encoding="utf-8")
        records: list[dict[str, Any]] = []
        if path.suffix.lower() == ".jsonl":
            for line_num, line in enumerate(raw_text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                item = json.loads(stripped, parse_float=Decimal)
                if not isinstance(item, dict):
                    raise ValueError(f"{path}:{line_num}: expected JSON object")
                records.append(item)
        else:
            loaded = json.loads(raw_text, parse_float=Decimal)
            if isinstance(loaded, dict) and "predictions" in loaded:
                loaded = loaded["predictions"]
            if not isinstance(loaded, list):
                raise ValueError(
                    f"{path}: expected JSON list or {{'predictions': [...]}} object"
                )
            for item in loaded:
                if not isinstance(item, dict):
                    raise ValueError(f"{path}: expected list of JSON objects")
                records.append(item)

        by_id: dict[str, dict[str, Any]] = {}
        for rec in records:
            sid = rec.get("scenario_id")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"{path}: each prediction must include string 'scenario_id'")
            by_id[sid] = rec
        return by_id

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        if agent_input.scenario_id not in self._by_id:
            raise PredictionMissingError(
                f"No prediction found for scenario_id '{agent_input.scenario_id}' "
                f"in {self.predictions_path}"
            )
        payload = dict(self._by_id[agent_input.scenario_id])
        payload.setdefault("pack_id", agent_input.pack_id.value)
        payload.setdefault("engine_id", agent_input.engine_id.value)
        return schema.model_validate(payload)


class CallableAgentAdapter:
    """Wraps a Python callable `(AgentInput, type[PredT]) -> PredT | dict`."""

    def __init__(
        self,
        fn: Callable[[AgentInput, type[Any]], Any],
    ) -> None:
        self._fn = fn

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        result = self._fn(agent_input, schema)
        if isinstance(result, schema):
            return result
        if isinstance(result, dict):
            payload = dict(result)
            payload.setdefault("pack_id", agent_input.pack_id.value)
            payload.setdefault("engine_id", agent_input.engine_id.value)
            return schema.model_validate(payload)
        return schema.model_validate(result)


class OpenAICompatibleAdapter:
    """Adapter querying any OpenAI-compatible `/chat/completions` JSON endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @staticmethod
    def _build_user_message(agent_input: AgentInput, schema: type[PredT]) -> str:
        sections: list[str] = [
            agent_input.prompt,
            "",
            "--- OUTPUT JSON SCHEMA ---",
            json.dumps(schema.model_json_schema(), indent=2),
            "",
            "IMPORTANT: Return ONLY a single valid JSON object matching the schema. "
            "Encode all monetary, quantity, and percentage values as exact decimal strings "
            '(e.g., "19.00", "1250.50").',
            f'Set "scenario_id" to "{agent_input.scenario_id}", '
            f'"pack_id" to "{agent_input.pack_id.value}", '
            f'and "engine_id" to "{agent_input.engine_id.value}".',
        ]
        for art in agent_input.artifacts:
            sections.append(f"\n--- DOCUMENT [{art.role}] ({art.rel_path}) ---")
            if art.extracted_text:
                sections.append(art.extracted_text)
            else:
                sections.append(
                    f"[Binary artifact {art.media_type}, "
                    f"{art.byte_size} bytes, sha256={art.sha256}]"
                )
        for att in agent_input.attachments:
            sections.append(
                f"\n--- ATTACHMENT [{att.doc_type}] {att.doc_id} ({att.timestamp_utc}) ---"
            )
            sections.append(f"Subject: {att.subject_or_title}")
            sections.append(att.body_text)
        return "\n".join(sections)

    @staticmethod
    def _strip_json_fences(content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def predict(self, agent_input: AgentInput, schema: type[PredT]) -> PredT:
        url = f"{self.base_url}/chat/completions"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert deterministic compliance and extraction engine. "
                        "Respond strictly with valid JSON using decimal strings for all amounts."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_user_message(agent_input, schema),
                },
            ],
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=body)
                    if resp.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                        time.sleep(min(2**attempt, 8))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                latency_ms = int((time.monotonic() - t0) * 1000)
                raw_content = data["choices"][0]["message"]["content"]
                cleaned = self._strip_json_fences(str(raw_content))
                parsed = json.loads(cleaned, parse_float=Decimal)
                if not isinstance(parsed, dict):
                    raise ValueError("Model did not return a JSON object")
                parsed["scenario_id"] = agent_input.scenario_id
                parsed["pack_id"] = agent_input.pack_id.value
                parsed["engine_id"] = agent_input.engine_id.value
                parsed["raw_response"] = str(raw_content)
                parsed["latency_ms"] = latency_ms
                return schema.model_validate(parsed)
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                break
        raise RuntimeError(
            f"OpenAI-compatible endpoint failed for {agent_input.scenario_id}: {last_exc}"
        ) from last_exc
