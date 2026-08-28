"""OpenRouter credentials and model selection -- the single place to configure
LLM access.

Everything here is read from the environment, following the same convention as
`sentinel/api/app.py`: `os.environ.get` with a documented default, and no
`.env` parser dependency. Copy `.env.example` to `.env` and export it, or set
the variables in the shell -- both work, because nothing here does anything
clever.

**No key means no LLM, and that is a supported state, not a broken one.**
`is_configured()` is false when `OPENROUTER_API_KEY` is unset, and every
caller is required to fall back to the deterministic template path rather than
raise. A submission that only works with a key in the environment cannot be
run by anyone reviewing it, and the template path is the one that carries the
citation-by-construction guarantee anyway -- the LLM path is the one that has
to earn its place, not the other way round.

**Why OpenRouter rather than a provider SDK.** OpenRouter exposes an
OpenAI-compatible `/chat/completions` endpoint, so the client is `httpx`
(already a dependency) plus a dict, with no new package and no vendor lock.
Switching model or provider is then a single environment variable rather than
a code change -- which matters here because the honest answer to "which model
drafts the narrative" is "whichever one the citation verifier rejects least,
measured", and that comparison needs to be cheap to run.
"""
from __future__ import annotations

import os

# --- Endpoint ---------------------------------------------------------------

# OpenRouter's OpenAI-compatible base. Override to point at a proxy, a local
# gateway, or a different OpenAI-compatible provider entirely; the client
# appends `/chat/completions` to whatever is set here.
BASE_URL = os.environ.get("OPENROUTER_BASE_URL",
                          "https://openrouter.ai/api/v1").rstrip("/")

# The key. Never logged, never written into a case record, never returned by
# the console API -- see `describe()` below, which exists so status can be
# displayed without the value leaking into a screenshot during the demo.
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# --- Model ------------------------------------------------------------------

# An OpenRouter model slug, in `vendor/model` form. Verify the exact slug
# against https://openrouter.ai/models before relying on this default --
# slugs are versioned and they move, and a silently unresolvable model id
# would surface as a runtime failure in the middle of a demo. Run
# `python scripts/check_llm.py` to confirm the configured slug resolves.
MODEL = os.environ.get("SENTINEL_LLM_MODEL", "anthropic/claude-sonnet-4.5")

# Deterministic by default, and this is not a stylistic preference. A
# suspicious-activity narrative is an auditable artifact: two runs over the
# same case file should produce the same text, or the case record's immutability
# guarantee becomes decorative. Raise it only for a deliberate sampling
# experiment, never for the filed path.
TEMPERATURE = float(os.environ.get("SENTINEL_LLM_TEMPERATURE", "0"))

# Narratives are six short sections. This cap is generous for that and tight
# enough that a runaway generation fails fast instead of billing.
MAX_TOKENS = int(os.environ.get("SENTINEL_LLM_MAX_TOKENS", "1500"))

# --- Failure behaviour ------------------------------------------------------

# A drafting call that has not returned in this many seconds is treated as a
# failure and the template path is used instead. An analyst queue that stalls
# on a hung HTTP request is worse than one that files a slightly plainer
# narrative.
TIMEOUT_SECONDS = float(os.environ.get("SENTINEL_LLM_TIMEOUT", "30"))

# Retries are for transport faults only (timeout, 5xx, connection reset).
# A 4xx is a configuration error and retrying it just delays the message that
# would have told you the key or the model slug is wrong.
MAX_RETRIES = int(os.environ.get("SENTINEL_LLM_MAX_RETRIES", "2"))

# --- Attribution ------------------------------------------------------------

# OpenRouter reads these two optional headers for request attribution. They
# are cosmetic and safe to leave at the defaults.
APP_URL = os.environ.get("SENTINEL_APP_URL",
                         "https://github.com/Pranav252005/FraudOps")
APP_TITLE = os.environ.get("SENTINEL_APP_TITLE", "Sentinel")


def is_configured() -> bool:
    """True when a drafting call could be attempted.

    Callers branch on this rather than catching an exception, so that "no key
    configured" and "the call failed" stay distinguishable in the metrics --
    a reviewer running without a key should see the template path reported as
    *not attempted*, not as a stack of failures.
    """
    return bool(API_KEY)


def headers() -> dict[str, str]:
    """Request headers for an OpenRouter chat completion."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": APP_URL,
        "X-Title": APP_TITLE,
    }


def endpoint() -> str:
    return f"{BASE_URL}/chat/completions"


def describe() -> dict[str, object]:
    """Configuration status, safe to log, display, or screenshot.

    Reports whether a key is present and its last four characters only --
    enough to tell two keys apart when debugging, not enough to be one.
    """
    return {
        "configured": is_configured(),
        "base_url": BASE_URL,
        "model": MODEL,
        "temperature": TEMPERATURE,
        "timeout_seconds": TIMEOUT_SECONDS,
        "key_suffix": f"...{API_KEY[-4:]}" if len(API_KEY) >= 4 else None,
    }
