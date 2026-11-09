"""Select owner-configured client metadata without changing authentication or bodies."""

from __future__ import annotations

import re

from ..config import ClientProfileConfig, CloudTargetConfig

SELECTOR_HEADER = "x-llm-redactor-client-profile"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_FORBIDDEN = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "x-goog-api-key",
    "cookie",
    "set-cookie",
    "host",
    "connection",
    "content-length",
    "content-type",
    "content-encoding",
    "transfer-encoding",
    "accept-encoding",
    "te",
    "trailer",
    "upgrade",
    SELECTOR_HEADER,
}
_IDENTITY = {"user-agent", "originator", "version", "x-app"}


class ClientProfileError(ValueError):
    """Fixed diagnostics deliberately exclude profile/header values."""


def validate_client_profiles(config: CloudTargetConfig) -> None:
    profiles = config.client_profiles
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 32:
        raise ClientProfileError("Configure between 1 and 32 named client profiles")
    for name, profile in profiles.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ClientProfileError("Client profile names must be simple identifiers")
        if not isinstance(profile, ClientProfileConfig) or not isinstance(profile.headers, dict):
            raise ClientProfileError("Client profiles require a headers mapping")
        if len(profile.headers) > 32:
            raise ClientProfileError("Too many client profile headers")
        seen: set[str] = set()
        for key, value in profile.headers.items():
            if (
                not isinstance(key, str)
                or not _HEADER.fullmatch(key)
                or key.lower() in _FORBIDDEN
                or key.lower() in seen
            ):
                raise ClientProfileError("Invalid, duplicate, or protected client profile header")
            seen.add(key.lower())
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 4096
                or any(ord(c) < 32 or ord(c) > 126 for c in value)
            ):
                raise ClientProfileError("Client header values must be bounded printable ASCII")
    if not isinstance(config.client_profile, str) or config.client_profile not in profiles:
        raise ClientProfileError("The default client profile is not configured")


def resolve_client_profile(config: CloudTargetConfig, selected: object = None) -> str:
    validate_client_profiles(config)
    name = config.client_profile if selected is None else selected
    if not isinstance(name, str) or name not in config.client_profiles:
        raise ClientProfileError("Select a configured client profile")
    return name


def client_headers(
    config: CloudTargetConfig, upstream_headers: dict[str, str] | None = None
) -> dict[str, str]:
    """Incoming headers < named profile < transport authentication/essentials.

    The selector is local control data and never goes to the upstream provider.
    No process, terminal, OS, project, session or credential discovery occurs here.
    """
    headers = {k.lower(): v for k, v in (upstream_headers or {}).items()}
    selected = headers.pop(SELECTOR_HEADER, None)
    name = resolve_client_profile(config, selected)
    if name != "default":
        headers = {
            k: v
            for k, v in headers.items()
            if k not in _IDENTITY and not k.startswith(("x-stainless-", "x-opencode-"))
        }
    headers.update({k.lower(): v for k, v in config.client_profiles[name].headers.items()})
    return headers
