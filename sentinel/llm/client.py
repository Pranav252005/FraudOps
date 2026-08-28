"""A minimal OpenAI-compatible chat client, with one hard rule: it never raises.

Every call returns a `Completion`. On success it carries text; on failure it
carries a machine-readable reason and no text. The caller's job is then to
fall back, and the reason is what gets counted -- "the model was slow" and
"the model invented a transaction id" are different problems with different
fixes, and a bare `None` loses that distinction.

The retry policy is deliberately narrow. Transport faults (timeout, connection
reset) and 5xx are retried, because they are transient by definition. A 4xx is
not retried at all: a 401 means the key is wrong and a 404 means the model slug
is wrong, and retrying either just delays the message that would have told you
which. This is the same reasoning as `scripts/check_llm.py`.

The HTTP call is injectable (`post=`) so the whole failure surface can be
tested without a network or a key. That matters more than usual here: the
behaviour under failure *is* the feature, so it needs the same test coverage
as the happy path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from sentinel.llm import config

# Failure reasons. These are counted and reported, so they are a closed set
# rather than free text.
NOT_CONFIGURED = "not_configured"
TRANSPORT = "transport"
HTTP_CLIENT_ERROR = "http_client_error"   # 4xx -- configuration, not luck
HTTP_SERVER_ERROR = "http_server_error"   # 5xx -- retried, then given up on
MALFORMED = "malformed_response"


@dataclass
class Completion:
    """The outcome of one drafting attempt."""
    text: str | None = None
    failure: str | None = None
    detail: str = ""
    model: str = ""
    attempts: int = 0
    usage: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.text is not None and self.failure is None


def _default_post(url, headers, payload, timeout):
    return httpx.post(url, headers=headers, json=payload, timeout=timeout)


def complete(system: str, user: str, *, post=_default_post) -> Completion:
    """One chat completion. Returns a `Completion`; never raises.

    `post` is the HTTP call, injected so tests can drive every failure branch
    without a network. It must accept (url, headers, payload, timeout) and
    return an object with `.status_code`, `.text` and `.json()`.
    """
    if not config.is_configured():
        return Completion(failure=NOT_CONFIGURED,
                          detail="OPENROUTER_API_KEY is not set")

    payload = {
        "model": config.MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": config.TEMPERATURE,
        "max_tokens": config.MAX_TOKENS,
    }

    last = Completion(failure=TRANSPORT, detail="no attempt made")
    for attempt in range(1, config.MAX_RETRIES + 2):
        try:
            response = post(config.endpoint(), config.headers(), payload,
                            config.TIMEOUT_SECONDS)
        except httpx.RequestError as exc:
            last = Completion(failure=TRANSPORT, detail=repr(exc),
                              attempts=attempt)
            continue

        status = getattr(response, "status_code", 0)

        if 400 <= status < 500:
            # Not retried, on purpose. See the module docstring.
            return Completion(failure=HTTP_CLIENT_ERROR,
                              detail=f"HTTP {status}: "
                                     f"{_body_excerpt(response)}",
                              attempts=attempt)
        if status >= 500:
            last = Completion(failure=HTTP_SERVER_ERROR,
                              detail=f"HTTP {status}: "
                                     f"{_body_excerpt(response)}",
                              attempts=attempt)
            continue

        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except Exception as exc:                       # noqa: BLE001
            # A 200 whose shape is not what the API contract promises. Rare,
            # but a gateway or proxy in front of the endpoint can produce it,
            # and it must not surface as an unhandled exception mid-queue.
            return Completion(failure=MALFORMED, detail=repr(exc),
                              attempts=attempt)

        if not isinstance(text, str) or not text.strip():
            return Completion(failure=MALFORMED,
                              detail="empty completion content",
                              attempts=attempt)

        return Completion(text=text, model=body.get("model", config.MODEL),
                          attempts=attempt, usage=body.get("usage", {}) or {})

    return last


def _body_excerpt(response, limit: int = 300) -> str:
    try:
        return str(getattr(response, "text", ""))[:limit]
    except Exception:                                  # noqa: BLE001
        return "<unreadable body>"
