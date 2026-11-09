"""Capture the real outbound headers, bodies, and MCP restoration for client selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from llm_redactor.config import ClientProfileConfig, CloudTargetConfig, Config, load_config
from llm_redactor.transport import cloud, mcp_server
from llm_redactor.transport.client_profiles import (
    SELECTOR_HEADER,
    ClientProfileError,
    client_headers,
    validate_client_profiles,
)
from llm_redactor.transport.http_proxy import app, configure


@pytest.fixture(autouse=True)
async def isolated_state(monkeypatch: pytest.MonkeyPatch):
    await cloud.aclose_client()
    monkeypatch.setattr(mcp_server, "_config", Config())
    yield
    await cloud.aclose_client()


def test_config_profiles_merge_and_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    file = tmp_path / "config.yaml"
    file.write_text(
        "cloud_target:\n  client_profile: codex\n  client_profiles:\n"
        "    opencode:\n      headers:\n        User-Agent: opencode/owner-version\n"
        "    custom:\n      headers:\n        User-Agent: OwnerSDK/1.0\n"
    )
    cfg = load_config(file)
    assert cfg.cloud_target.client_profile == "codex"
    assert "claude-code" in cfg.cloud_target.client_profiles
    assert (
        client_headers(cfg.cloud_target, {SELECTOR_HEADER: "opencode"})["user-agent"]
        == "opencode/owner-version"
    )
    monkeypatch.setenv("LLM_REDACTOR_CLIENT_PROFILE", "custom")
    assert load_config(file).cloud_target.client_profile == "custom"


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer forbidden"},
        {"X-API-Key": "forbidden"},
        {"Host": "elsewhere.invalid"},
        {"Content-Length": "1"},
        {"User-Agent": "bad\r\nInjected: yes"},
        {"bad header": "x"},
        {"User-Agent": "a", "user-agent": "b"},
        {SELECTOR_HEADER: "codex"},
        {"Accept-Encoding": "br"},
    ],
)
def test_invalid_profile_headers_are_rejected_without_echo(headers: dict[str, str]):
    cfg = CloudTargetConfig(
        client_profiles={"bad": ClientProfileConfig(headers)}, client_profile="bad"
    )
    with pytest.raises(ClientProfileError) as error:
        validate_client_profiles(cfg)
    assert "forbidden" not in str(error.value)
    assert "Injected" not in str(error.value)


def test_profile_selection_is_case_insensitive_for_headers_and_preserves_auth():
    cfg = CloudTargetConfig()
    headers = client_headers(
        cfg,
        {
            "User-Agent": "parent-agent",
            "Originator": "parent",
            "X-Stainless-Runtime": "python",
            "X-OpenCode-Project": "private-project",
            "Authorization": "Bearer synthetic",
            "X-App": "parent",
            "X-LLM-Redactor-Client-Profile": "opencode",
        },
    )
    assert headers == {"user-agent": "opencode/2.2.6", "authorization": "Bearer synthetic"}
    assert client_headers(cfg, {"User-Agent": "parent"})["user-agent"] == "parent"


@pytest.mark.parametrize("profile", ["default", "opencode", "codex", "claude-code"])
@pytest.mark.asyncio
async def test_buffered_cloud_requests_apply_profile(
    profile: str, httpx_mock: Any, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("PROFILE_TEST_KEY", "synthetic-profile-key")
    target = CloudTargetConfig(
        endpoint="https://provider.invalid/v1", api_key_env="PROFILE_TEST_KEY"
    )
    httpx_mock.add_response(json={"choices": []})
    body = {"model": "test", "messages": [{"role": "user", "content": "safe"}]}
    await cloud.forward_chat_completion(body, target, upstream_headers={SELECTOR_HEADER: profile})
    request = httpx_mock.get_request()
    assert json.loads(request.content) == body
    assert request.headers["authorization"] == "Bearer synthetic-profile-key"
    assert SELECTOR_HEADER not in request.headers
    if profile != "default":
        for key, value in target.client_profiles[profile].headers.items():
            assert request.headers[key] == value


@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.asyncio
async def test_anthropic_stream_preserves_raw_bytes_and_selected_profile(
    raw: bool, httpx_mock: Any
):
    target = CloudTargetConfig(endpoint="https://provider.invalid/v1")
    payload = b'{ "model": "test", "messages": [], "stream": true }'
    httpx_mock.add_response(headers={"content-type": "text/event-stream"}, content=b"data: {}\n\n")
    if raw:
        result = await cloud.forward_anthropic_raw_stream(
            payload, target, upstream_headers={SELECTOR_HEADER: "claude-code"}
        )
    else:
        result = await cloud.forward_anthropic_messages_stream(
            json.loads(payload), target, upstream_headers={SELECTOR_HEADER: "claude-code"}
        )
    assert result.iterator is not None
    _ = [chunk async for chunk in result.iterator]
    request = httpx_mock.get_request()
    assert request.headers["user-agent"].startswith("claude-cli/")
    assert SELECTOR_HEADER not in request.headers
    if raw:
        assert request.content == payload


@pytest.mark.parametrize("backend", ["openai_compat", "anthropic", "openai_responses"])
@pytest.mark.asyncio
async def test_mcp_redacts_and_restores_in_each_api_format(
    backend: str, httpx_mock: Any, monkeypatch: pytest.MonkeyPatch
):
    cfg = Config()
    cfg.cloud_target.endpoint = "https://provider.invalid/v1"
    monkeypatch.setattr(mcp_server, "_config", cfg)
    original_detect = mcp_server._detect_text

    async def regex_only(text: str, **kwargs: Any):
        return await original_detect(text, use_ner=False)

    monkeypatch.setattr(mcp_server, "_detect_text", regex_only)
    from llm_redactor.redact.placeholder import PREFIX, SUFFIX

    answer = f"Answer for {PREFIX}EMAIL_1{SUFFIX}"
    response = (
        {"choices": [{"message": {"content": answer}}]}
        if backend == "openai_compat"
        else {"content": [{"type": "text", "text": answer}]}
        if backend == "anthropic"
        else {"output": [{"type": "message", "content": [{"type": "output_text", "text": answer}]}]}
    )
    httpx_mock.add_response(json=response)
    result = await mcp_server._handle_llm_chat(
        {
            "model": "test-model",
            "backend": backend,
            "client_profile": "codex",
            "messages": [
                {"role": "system", "content": "Help alice@example.org."},
                {"role": "user", "content": "Answer alice@example.org."},
            ],
        }
    )
    output = json.loads(result[0].text)
    assert output["response"] == "Answer for alice@example.org"
    assert output["client_profile"] == "codex"
    request = httpx_mock.get_request()
    assert b"alice@example.org" not in request.content
    assert request.headers["originator"] == "codex_cli_rs"
    assert SELECTOR_HEADER not in request.headers
    payload = json.loads(request.content)
    assert "client_profile" not in payload
    if backend == "openai_responses":
        assert request.url.path == "/v1/responses"
        assert payload["store"] is False
        assert "instructions" in payload
    elif backend == "anthropic":
        assert request.url.path == "/v1/messages"
        assert "system" in payload


@pytest.mark.asyncio
async def test_unknown_mcp_profile_makes_no_request(httpx_mock: Any):
    result = await mcp_server._handle_llm_chat(
        {
            "client_profile": "unconfigured",
            "messages": [{"role": "user", "content": "safe"}],
        }
    )
    assert "error" in json.loads(result[0].text)
    assert not httpx_mock.get_requests()


def test_proxy_profile_selection_and_error(httpx_mock: Any):
    cfg = Config()
    cfg.cloud_target.endpoint = "https://provider.invalid/v1"
    cfg.pipeline.opt_b_redact.strict = False
    configure(cfg, use_ner=False)
    httpx_mock.add_response(json={"choices": [{"message": {"content": "safe"}}]})
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "safe"}],
            },
            headers={SELECTOR_HEADER: "opencode"},
        )
        assert response.status_code == 200
        rejected = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "safe"}],
            },
            headers={SELECTOR_HEADER: "invalid"},
        )
        assert rejected.status_code == 422
    assert len(httpx_mock.get_requests()) == 1
    assert httpx_mock.get_request().headers["user-agent"] == "opencode/2.2.6"


@pytest.mark.asyncio
async def test_mcp_client_discovery_is_non_secret():
    result = await mcp_server.call_tool("llm.clients", {})
    payload = json.loads(result[0].text)
    assert {p["name"] for p in payload["client_profiles"]} == {
        "default",
        "opencode",
        "codex",
        "claude-code",
    }
    assert "headers" not in payload["client_profiles"][0]
