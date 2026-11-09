# Outbound client profiles

The master agent can choose which client metadata LLM Redactor presents when it delegates a task. Named profiles apply HTTP headers; API format is selected separately. The endpoint and credential remain in owner configuration.

## MCP use

Call `llm.clients` to discover the configured profile names and supported API formats. Then call `llm.chat`:

```json
{
  "client_profile": "codex",
  "backend": "openai_responses",
  "model": "gpt-6.1-sol",
  "max_tokens": 1024,
  "messages": [{"role": "user", "content": "Review this focused problem."}]
}
```

Use `client_profile: "opencode"` or `"claude-code"` to change client metadata. The model and backend can stay the same. The result includes the selected `client_profile` and `backend`.

`backend` supports `openai_compat` (Chat Completions), `openai_responses`, and `anthropic` (Messages). Omitting it uses `cloud_target.backend`. System text is redacted before conversion into Responses instructions or Anthropic system text. Responses calls use `store: false`; only text output is returned, without replaying opaque reasoning state or executing tools.

This MCP path accepts text messages containing only `role` and `content`. Header maps, endpoints, keys, and transport callbacks are not per-call arguments. Invalid client profile selection fails before an inference request.

## Owner configuration

The default profile is `default`, preserving the previous forwarding behavior. These compatibility profiles are also supplied:

| Name | HTTP metadata |
| --- | --- |
| `default` | Preserve incoming headers; standalone calls retain the transport's normal User-Agent |
| `opencode` | `User-Agent: opencode/2.2.6` |
| `codex` | `User-Agent: codex_cli_rs/0.167.0`, `originator: codex_cli_rs` |
| `claude-code` | `User-Agent: claude-cli/2.1.319 (external, cli)`, `x-app: cli` |

The versions are static compatibility identifiers, not automatic discoveries of installed applications. Owners can replace any profile's headers or add a custom name:

```yaml
cloud_target:
  endpoint: https://agentrouter.org/v1
  api_key_env: AGENTROUTER_API_KEY
  backend: openai_responses
  client_profile: codex
  client_profiles:
    codex:
      headers:
        User-Agent: codex_cli_rs/0.167.0
        originator: codex_cli_rs
    company-sdk:
      headers:
        User-Agent: CompanySDK/1.0
```

YAML merges named entries into the built-ins; a supplied entry replaces that profile's header mapping. `LLM_REDACTOR_CLIENT_PROFILE` overrides the configured default. `llm.clients` returns names and header names, without credentials or header values.

Headers are case-insensitive. Precedence is incoming headers, then profile headers, then transport essentials/authentication. A selected named profile clears inherited User-Agent/originator/version/x-app and `x-stainless-*`/`x-opencode-*` headers before applying its own metadata. `default` preserves incoming identity headers. Profiles do not collect OS, home directory, terminal, project, session, or installed-client information.

Profile headers cannot set authentication, cookies, Host, content framing/type, compression negotiation, or the profile-selector header. Header names and values are validated, including rejection of CR/LF and duplicate case variants. Custom metadata is owner-controlled; include only information you intend to disclose.

## HTTP proxy use

Set the owner default for all cloud forwarding, or send this local control header:

```text
X-LLM-Redactor-Client-Profile: opencode
```

The selector is consumed locally and never forwarded. Unknown names produce HTTP 422. Profile selection applies to existing buffered, streamed, raw signed-body and passthrough transport paths. It does not rewrite request bodies, URLs, signatures, or API protocols in proxy mode. Existing route privacy/bypass policies continue to apply; selecting a profile does not add redaction to a previously unredacted passthrough route. In particular, HTTP Responses remains the upstream project's passthrough path; the new MCP Responses path performs message redaction.

## Client compatibility and authorization

Profiles provide configurable request metadata. They do not run OpenCode, Codex, or Claude Code, recreate their complete SDK/TLS fingerprints, or establish authenticated first-party client identity. Credentials, account entitlement, client-specific OAuth, attestation, and server authorization rules still apply. No fallback profile is automatically attempted after a rejection.

OpenCode and Codex expose their client conventions in source. Modern OpenCode includes channel/app fields and additional session/project metadata; this profile deliberately supplies a smaller compatible identifier. Codex normally includes OS/terminal information; this profile omits that local information. Claude Code's distribution is not fully open source; its profile uses the established CLI User-Agent convention rather than claiming byte-for-byte replication of the whole client.

References inspected for this feature:

- [OpenCode request metadata](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/session/model-request.ts) and [User-Agent construction](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/app.ts).
- [Codex default HTTP client](https://github.com/openai/codex/blob/e54a5713caf331f42a6eef0166186df5f7563c29/codex-rs/login/src/auth/default_client.rs).
- [Official OpenAI documentation on Codex originator and client metadata](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server).
- [AgentRouter's own Claude Code setup](https://github.com/agentrouter-org/docs/blob/main/en/start.md) and [Codex setup](https://github.com/agentrouter-org/docs/blob/main/codex.md).
- [Reported AgentRouter client-header compatibility](https://github.com/yetone/magpie/issues/2422); third-party observations, not an authorization guarantee.

See `CLIENT_PROFILES_VALIDATION.md` for the live test results. No supplied API key belongs in this repository.
