"""Zero-paid-API fail-closed guard.

Rules enforced here:
* Only providers declared ``free_keyless`` may be constructed. Anything that needs a
  key, is paid, or is of unknown cost class raises ``PaidApiBlocked``.
* Credentials found in the environment are REPORTED (names only) and NEVER used.
* The spend ledger can only ever record $0.00; a non-zero entry raises.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

FREE_KEYLESS = "free_keyless"
ALLOWED_COST_CLASSES = frozenset({FREE_KEYLESS})

# Detected for the manifest only. The pilot never reads their values.
KNOWN_KEYED_ENV_VARS = (
    "EXA_API_KEY",
    "TAVILY_API_KEY",
    "BRAVE_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "SERPAPI_API_KEY",
    "SERPER_API_KEY",
    "HUNTER_API_KEY",
    "APOLLO_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GMAIL_CLIENT_SECRET",
    "SENDGRID_API_KEY",
    "MAILGUN_API_KEY",
    "SMTP_PASSWORD",
)


class PaidApiBlocked(RuntimeError):
    """Raised whenever a step would need a paid API, a key, or unknown-cost access."""


def require_zero_cost(provider_name: str, cost_class: str) -> None:
    if cost_class not in ALLOWED_COST_CLASSES:
        raise PaidApiBlocked(
            f"provider {provider_name!r} has cost class {cost_class!r}; the VM1 pilot allows "
            f"only {sorted(ALLOWED_COST_CLASSES)}. Blocked (no paid APIs, no keys, no unknown cost)."
        )


def credentials_present(env: Mapping[str, str] | None = None) -> list[str]:
    """Names (never values) of known credential env vars that are set. Reported, ignored."""
    env = os.environ if env is None else env
    return sorted(name for name in KNOWN_KEYED_ENV_VARS if env.get(name))


@dataclass
class SpendLedger:
    """Records external spend. By construction the total is always 0.0."""

    entries: list[dict] = field(default_factory=list)

    def record(self, provider: str, usd: float, note: str = "") -> None:
        if usd != 0:
            raise PaidApiBlocked(
                f"non-zero spend {usd!r} USD recorded for {provider!r}; pilot budget is $0."
            )
        self.entries.append({"provider": provider, "usd": 0.0, "note": note})

    @property
    def total_usd(self) -> float:
        return 0.0
