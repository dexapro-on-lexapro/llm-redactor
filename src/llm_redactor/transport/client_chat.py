"""Text-only MCP delegation over existing cloud transports and explicit API formats."""

from __future__ import annotations

from typing import Any

from ..config import CloudTargetConfig
from .client_profiles import SELECTOR_HEADER
from .cloud import forward_anthropic_messages, forward_chat_completion, forward_responses

BACKENDS = ("openai_compat", "openai_responses", "anthropic")


async def delegate_chat(
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    target: CloudTargetConfig,
    profile: str,
    backend: str,
) -> tuple[dict[str, Any], str]:
    """Messages have already been sanitized, including all system text."""
    headers = {SELECTOR_HEADER: profile}
    if backend == "openai_compat":
        body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
        if model:
            body["model"] = model
        result = await forward_chat_completion(body, target, upstream_headers=headers)
        choices = result.get("choices") or []
        text = choices[0].get("message", {}).get("content", "") if choices else ""
    elif backend == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body = {
            "messages": [m for m in messages if m["role"] != "system"],
            "max_tokens": max_tokens,
        }
        if model:
            body["model"] = model
        if system:
            body["system"] = system
        result = await forward_anthropic_messages(body, target, upstream_headers=headers)
        text = "".join(
            part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
        )
    elif backend == "openai_responses":
        instructions = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body = {
            "input": [
                {
                    "type": "message",
                    "role": m["role"],
                    "content": [
                        {
                            "type": "output_text" if m["role"] == "assistant" else "input_text",
                            "text": m["content"],
                        }
                    ],
                }
                for m in messages
                if m["role"] != "system"
            ],
            "max_output_tokens": max_tokens,
            "stream": False,
            "store": False,
        }
        if model:
            body["model"] = model
        if instructions:
            body["instructions"] = instructions
        result = await forward_responses(body, target, upstream_headers=headers)
        text = "".join(
            part.get("text", "")
            for item in result.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    else:
        raise ValueError("Select a supported API backend")
    if not isinstance(text, str):
        raise ValueError("The provider returned unsupported non-text content")
    return result, text
