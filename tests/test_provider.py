from __future__ import annotations

import json
from dataclasses import replace

from find_my_customer.config import get_settings
from find_my_customer.prompt import build_prompt
from find_my_customer.provider import NvidiaProvider, OpenAIProvider
from find_my_customer.skill_runtime import REPOSITORY_ROOT


class FakeResponse:
    id = "resp_test"
    status = "completed"

    def __init__(self):
        self.output_text = (REPOSITORY_ROOT / "examples" / "analysis.example.json").read_text(encoding="utf-8")

    def model_dump(self, mode="json"):
        assert mode == "json"
        return {
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "output": [{"type": "web_search_call", "action": {"sources": [{"url": "https://example.com/evidence"}]}}],
        }


class FakeResponses:
    def __init__(self):
        self.created = None

    def create(self, **kwargs):
        self.created = kwargs
        return FakeResponse()

    def retrieve(self, response_id):
        assert response_id == "resp_test"
        return FakeResponse()


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


class FakeChatCompletion:
    id = "chatcmpl_test"

    class Choice:
        class Message:
            content = (REPOSITORY_ROOT / "examples" / "analysis.example.json").read_text(encoding="utf-8")

        message = Message()

    choices = [Choice()]

    def model_dump(self, mode="json"):
        assert mode == "json"
        return {"usage": {"prompt_tokens": 12, "completion_tokens": 34}}


class FakeChatCompletions:
    def __init__(self):
        self.created = None

    def create(self, **kwargs):
        self.created = kwargs
        return FakeChatCompletion()


class FakeNvidiaClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()


def test_openai_adapter_is_backgrounded_bounded_and_web_search_only():
    settings = replace(get_settings(), openai_api_key="test", provider="openai")
    provider = OpenAIProvider(settings)
    provider.client = FakeClient()
    created_ids = []
    result = provider.run(
        build_prompt("https://example.com", "Test product", "quick", "general"),
        on_created=created_ids.append,
    )

    request = provider.client.responses.created
    assert request["background"] is True
    assert request["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert request["max_tool_calls"] == 30
    assert request["max_output_tokens"] == 30_000
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["text"]["format"]["type"] == "json_schema"
    assert created_ids == ["resp_test"]
    assert result.response_id == "resp_test"
    assert result.usage["output_tokens"] == 20
    assert result.source_ledger == [{"url": "https://example.com/evidence", "title": ""}]


def test_openai_adapter_resumes_existing_background_response():
    settings = replace(get_settings(), openai_api_key="test", provider="openai")
    provider = OpenAIProvider(settings)
    provider.client = FakeClient()
    result = provider.run(
        build_prompt("https://example.com", "Test product", "quick", "general"),
        response_id="resp_test",
    )
    assert provider.client.responses.created is None
    assert json.loads(json.dumps(result.report))["product"]["name"] == "SignalDesk"


def test_nvidia_adapter_uses_nemotron_chat_completions():
    settings = replace(
        get_settings(),
        nvidia_api_key="test",
        nvidia_model="nvidia/llama-3.3-nemotron-super-49b-v1",
        provider="nvidia",
    )
    provider = NvidiaProvider(settings)
    provider.client = FakeNvidiaClient()
    created_ids = []
    result = provider.run(
        build_prompt("https://example.com", "Test product", "quick", "general"),
        on_created=created_ids.append,
    )
    request = provider.client.chat.completions.created
    assert request["model"] == "nvidia/llama-3.3-nemotron-super-49b-v1"
    assert request["response_format"] == {"type": "json_object"}
    assert created_ids == ["chatcmpl_test"]
    assert result.usage["completion_tokens"] == 34
