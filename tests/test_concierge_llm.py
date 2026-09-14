from datetime import datetime
from io import BytesIO
import json
import os
from unittest.mock import patch
from urllib.error import URLError
from zoneinfo import ZoneInfo

import concierge_llm


NOW = datetime(2026, 9, 13, 12, 0, tzinfo=ZoneInfo("America/New_York"))


def setup_function():
    concierge_llm._interpret_cached.cache_clear()


def test_llm_is_disabled_without_explicit_provider_and_key():
    with patch.dict(os.environ, {"FAMILY_LLM_PROVIDER": "none", "OPENAI_API_KEY": ""}, clear=False):
        assert concierge_llm.interpret("Schedule soccer", ["Alex"], NOW) is None


def test_local_structured_response_is_validated():
    provider_result = {
        "request_type": "calendar",
        "title": "Two events for Alex",
        "primary_member": "Alex",
        "notification_members": ["Jordan", "Unknown Person"],
        "date": "2026-09-14",
        "time": "15:30",
        "calendar_events": [
            {"title": "Speech", "start_time": "15:30", "end_time": "16:00"},
            {"title": "Therapy", "start_time": "16:00", "end_time": "16:30"},
        ],
        "repeat_interval": "none",
    }
    api_response = {
        "message": {"content": json.dumps(provider_result)}
    }
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return BytesIO(json.dumps(api_response).encode("utf-8"))

    environment = {
        "FAMILY_LLM_PROVIDER": "ollama",
        "FAMILY_LLM_MODEL": "test-model",
        "OPENAI_API_KEY": "private-test-key",
    }
    with patch.dict(os.environ, environment, clear=False), patch.object(concierge_llm, "urlopen", fake_urlopen):
        result = concierge_llm.interpret("Alex has two events tomorrow", ["Alex", "Jordan"], NOW)

    sent = json.loads(captured["request"].data)
    assert sent['format']['additionalProperties'] is False
    assert captured['request'].get_header('Authorization') is None
    assert result["primary_member"] == "Alex"
    assert result["notification_members"] == ["Jordan"]
    assert len(result["calendar_events"]) == 2


def test_provider_failure_returns_to_local_parser():
    environment = {"FAMILY_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "private-test-key"}
    with patch.dict(os.environ, environment, clear=False), patch.object(
        concierge_llm, "urlopen", side_effect=URLError("offline")
    ):
        assert concierge_llm.interpret("Schedule soccer", ["Alex"], NOW) is None


def test_ollama_uses_local_schema_without_api_key():
    result = {"request_type": "calendar", "title": "Speech", "primary_member": "Alex",
              "notification_members": [], "date": "2026-09-14", "time": "15:30",
              "calendar_events": [{"title": "Speech", "start_time": "15:30", "end_time": "16:00"}],
              "repeat_interval": "none"}
    captured = {}
    def fake(request, timeout):
        captured['url'] = request.full_url
        captured['body'] = json.loads(request.data)
        assert request.get_header('Authorization') is None
        return BytesIO(json.dumps({'done': True, 'message': {'content': json.dumps(result)}}).encode())
    with patch.dict(os.environ, {'FAMILY_LLM_PROVIDER': 'ollama', 'FAMILY_LLM_MODEL': 'gpt-oss:20b',
                                 'OLLAMA_BASE_URL': 'http://host.docker.internal:11434', 'OPENAI_API_KEY': ''}), \
         patch.object(concierge_llm, 'urlopen', fake):
        plan = concierge_llm.interpret('Alex speech tomorrow', ['Alex'], NOW)
    assert plan['primary_member'] == 'Alex'
    assert captured['url'] == 'http://host.docker.internal:11434/api/chat'
    assert captured['body']['stream'] is False
    assert captured['body']['format']['additionalProperties'] is False


def test_ollama_failure_does_not_call_cloud():
    with patch.dict(os.environ, {'FAMILY_LLM_PROVIDER': 'ollama'}), \
         patch.object(concierge_llm, 'urlopen', side_effect=URLError('offline')) as call:
        assert concierge_llm.interpret('Alex speech tomorrow', ['Alex'], NOW) is None
        assert call.call_count == 1


def test_cloud_provider_and_remote_ollama_never_transmit():
    for environment in [
        {'FAMILY_LLM_PROVIDER':'openai','OPENAI_API_KEY':'test'},
        {'FAMILY_LLM_PROVIDER':'ollama','OLLAMA_BASE_URL':'https://remote.example'},
        {'FAMILY_LLM_PROVIDER':'ollama','OLLAMA_BASE_URL':'http://localhost:11434','FAMILY_LLM_MODEL':'qwen:cloud'},
    ]:
        with patch.dict(os.environ,environment), patch.object(concierge_llm,'urlopen') as call:
            assert concierge_llm.interpret('private request',['Name'],NOW) is None
            call.assert_not_called()
