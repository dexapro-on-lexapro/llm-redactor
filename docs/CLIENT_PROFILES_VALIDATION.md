# Client profile validation

Validated on 9 November 2026 using Python 3.12.16 and the fork's own MCP and cloud transport code. Upstream base commit: `059d3e0d2862a18faa56fbe7bf9a3b028c691f41`.

## Automated checks

- Full suite: **221 passed, 1 skipped**. The skip is the existing optional image-redaction test.
- New feature tests: **23 passed**.
- Ruff formatting and lint: passed across source, tests, evaluation code, and tools.
- Mypy: passed across 67 source files.
- Git whitespace/error check: passed.

Coverage includes configuration merging and environment precedence; named profiles; case-insensitive headers; authentication preservation; protected-header and CR/LF rejection; unknown-profile refusal before networking; selector removal; buffered and streamed transports; exact preservation of raw signed-body bytes; and redaction/restoration in all three MCP API formats.

## Live AgentRouter test

The user explicitly supplied a temporary AgentRouter credential and authorized live testing with **`gpt-6.1-sol`**. Only synthetic task text was sent. The credential was supplied via a named process environment variable, never a tool argument, repository file, command-line flag, or published result.

The successful route was `POST https://agentrouter.org/v1/responses`. Requests contained a synthetic email, which was verified absent from the serialized outgoing request. The local profile-selector header was also verified absent upstream.

| Profile | Outgoing identity metadata | HTTP status | Model result |
| --- | --- | --- | --- |
| `default` | `python-httpx/0.28.1` | 401 | Rejected |
| `opencode` | `opencode/2.2.6` | 200 | `gpt-6.1-sol` returned `PROFILE_OK` |
| `codex` | `codex_cli_rs/0.167.0`, originator `codex_cli_rs` | 200 | `gpt-6.1-sol` returned `PROFILE_OK` |
| `claude-code` | `claude-cli/2.1.319 (external, cli)` | 200 | `gpt-6.1-sol` returned `PROFILE_OK` |

The initial Chat Completions checks returned 401 with the default transport and 400 with the OpenCode/Claude Code profiles for this model. No model was substituted. Switching explicitly to the Responses format produced the results above. Client identity and API format are independent settings.

A further call used the **actual stdio MCP server**, not only an imported handler: the client initialized, discovered `llm.clients`, inherited the configured Responses backend, selected `codex`, and received `PROFILE_OK` from `gpt-6.1-sol`. The server's default regex plus local NER path detected the synthetic email. The four successful calls reported 333 total input/output tokens in aggregate.

The temporary credential file used by the test harness was removed after testing. Published evidence contains only profile names, public endpoint paths, synthetic-data checks, model names, statuses, output text, and usage counts.

## Scope of the evidence

These results establish that this account, model, endpoint, and these profile headers worked at the test date. They do not establish universal provider compatibility, an authenticated first-party client identity, or continued access under future server policy changes. The feature does not recreate a complete SDK/TLS fingerprint or invoke the actual client binaries.

Existing LLM Redactor privacy policies and detector limitations still apply. The HTTP Responses route remains the original passthrough route; the new MCP Responses path sanitizes text before forwarding. There is no automatic profile or model fallback after a rejection.
