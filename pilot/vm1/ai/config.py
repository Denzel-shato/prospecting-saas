"""Build a provider from environment variables (read at call time, never at import time).

Nothing is selected by default: ``ENGINE6_AI_PROVIDER`` must name a provider explicitly, so
no real provider can be activated by accident. Models are required (no default) because
vendor model catalogs change. Error messages name missing variables, never their values.

    ENGINE6_AI_PROVIDER = mock | cloudflare | groq

    cloudflare: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_AI_MODEL
                [CLOUDFLARE_AI_BASE_URL]
    groq:       GROQ_API_KEY, GROQ_MODEL
                [GROQ_BASE_URL, GROQ_RESPONSE_MODE=json_object|json_schema, GROQ_STRICT_SCHEMA=true|false]
"""

from __future__ import annotations

import os
from typing import Mapping

from .cloudflare import DEFAULT_BASE_URL as CLOUDFLARE_BASE_URL, CloudflareWorkersAIProvider
from .errors import AIConfigError
from .groq import DEFAULT_BASE_URL as GROQ_BASE_URL, GroqProvider
from .mock import MockProvider
from .request import AIProvider
from .transport import HttpTransport

PROVIDER_VAR = "ENGINE6_AI_PROVIDER"
PROVIDER_NAMES = ("mock", "cloudflare", "groq")


def _required(env: Mapping[str, str], names: tuple[str, ...]) -> dict[str, str]:
    values = {n: env.get(n, "").strip() for n in names}
    missing = [n for n, v in values.items() if not v]
    if missing:
        raise AIConfigError(f"missing required environment variable(s): {', '.join(missing)}")
    return values


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    raise AIConfigError(f"{name} must be true or false")


def provider_from_env(
    env: Mapping[str, str] | None = None, *, transport: HttpTransport | None = None
) -> AIProvider:
    env = os.environ if env is None else env
    choice = env.get(PROVIDER_VAR, "").strip().lower()
    if not choice:
        raise AIConfigError(f"{PROVIDER_VAR} is not set (choose one of {', '.join(PROVIDER_NAMES)})")
    if choice == "mock":
        return MockProvider()
    if choice == "cloudflare":
        v = _required(env, ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_AI_MODEL"))
        return CloudflareWorkersAIProvider(
            account_id=v["CLOUDFLARE_ACCOUNT_ID"], api_token=v["CLOUDFLARE_API_TOKEN"],
            model=v["CLOUDFLARE_AI_MODEL"],
            base_url=env.get("CLOUDFLARE_AI_BASE_URL", "").strip() or CLOUDFLARE_BASE_URL,
            transport=transport,
        )
    if choice == "groq":
        v = _required(env, ("GROQ_API_KEY", "GROQ_MODEL"))
        return GroqProvider(
            api_key=v["GROQ_API_KEY"], model=v["GROQ_MODEL"],
            base_url=env.get("GROQ_BASE_URL", "").strip() or GROQ_BASE_URL,
            response_mode=env.get("GROQ_RESPONSE_MODE", "").strip() or "json_object",
            strict_schema=_bool(env, "GROQ_STRICT_SCHEMA", False),
            transport=transport,
        )
    raise AIConfigError(f"unknown {PROVIDER_VAR} (choose one of {', '.join(PROVIDER_NAMES)})")
