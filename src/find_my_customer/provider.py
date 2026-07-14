from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from .config import Settings
from .prompt import PromptBundle
from .skill_runtime import REPOSITORY_ROOT, report_schema


@dataclass(frozen=True)
class ProviderResult:
    report: dict
    response_id: str
    source_ledger: list[dict[str, str]]
    usage: dict[str, Any]


def _collect_sources(value: Any, found: dict[str, dict[str, str]]) -> None:
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            found[url] = {"url": url, "title": str(value.get("title", ""))[:500]}
        for child in value.values():
            _collect_sources(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_sources(child, found)


class OpenAIProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=60.0, max_retries=2)

    def _wait(self, response, on_poll: Callable[[], None] | None):
        while response.status in {"queued", "in_progress"}:
            time.sleep(2)
            if on_poll:
                on_poll()
            response = self.client.responses.retrieve(response.id)
        if response.status != "completed":
            raise RuntimeError(f"OpenAI response ended with status {response.status}")
        return response

    def run(
        self,
        prompt: PromptBundle,
        *,
        response_id: str | None = None,
        on_created: Callable[[str], None] | None = None,
        on_poll: Callable[[], None] | None = None,
    ) -> ProviderResult:
        if response_id:
            response = self.client.responses.retrieve(response_id)
        else:
            response = self.client.responses.create(
                model=self.settings.openai_model,
                instructions=prompt.instructions,
                input=prompt.input_text,
                tools=[{"type": "web_search", "search_context_size": "high"}],
                include=["web_search_call.action.sources"],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "first_customer_report",
                        "schema": report_schema(),
                        "strict": False,
                    }
                },
                reasoning={"effort": "high"},
                max_output_tokens=30_000,
                max_tool_calls=30,
                background=True,
                store=True,
            )
            if on_created:
                on_created(response.id)
        response = self._wait(response, on_poll)
        try:
            report = json.loads(response.output_text)
        except json.JSONDecodeError as error:
            raise RuntimeError("OpenAI returned invalid report JSON") from error
        raw = response.model_dump(mode="json")
        found: dict[str, dict[str, str]] = {}
        _collect_sources(raw, found)
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ProviderResult(report=report, response_id=response.id, source_ledger=list(found.values()), usage=usage)

    def repair(
        self,
        previous: ProviderResult,
        validation_errors: list[str],
        *,
        on_created: Callable[[str], None] | None = None,
        on_poll: Callable[[], None] | None = None,
    ) -> ProviderResult:
        response = self.client.responses.create(
            model=self.settings.openai_model,
            previous_response_id=previous.response_id,
            input=(
                "Repair the report JSON once. Do not perform new research and do not introduce new URLs. "
                "Return the complete corrected report. Deterministic validator errors:\n- "
                + "\n- ".join(validation_errors[:40])
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "first_customer_report_repair",
                    "schema": report_schema(),
                    "strict": False,
                }
            },
            reasoning={"effort": "medium"},
            max_output_tokens=30_000,
            background=True,
            store=True,
        )
        if on_created:
            on_created(response.id)
        response = self._wait(response, on_poll)
        try:
            report = json.loads(response.output_text)
        except json.JSONDecodeError as error:
            raise RuntimeError("OpenAI repair returned invalid report JSON") from error
        raw = response.model_dump(mode="json")
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ProviderResult(
            report=report,
            response_id=response.id,
            source_ledger=previous.source_ledger,
            usage={"research": previous.usage, "repair": usage},
        )


class FixtureProvider:
    def run(self, prompt: PromptBundle, **kwargs) -> ProviderResult:
        del prompt
        on_created = kwargs.get("on_created")
        if on_created:
            on_created("fixture")
        path = Path(REPOSITORY_ROOT) / "examples" / "analysis.example.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        return ProviderResult(report=report, response_id="fixture", source_ledger=[], usage={})

    def repair(self, previous: ProviderResult, validation_errors: list[str], **kwargs) -> ProviderResult:
        del validation_errors
        on_created = kwargs.get("on_created")
        if on_created:
            on_created(previous.response_id)
        return previous


def provider_for(settings: Settings):
    if settings.provider == "fixture":
        return FixtureProvider()
    if settings.provider == "openai":
        return OpenAIProvider(settings)
    raise RuntimeError(f"Unsupported provider: {settings.provider}")
