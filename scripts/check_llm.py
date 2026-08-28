"""Confirm the OpenRouter configuration actually resolves, before a demo needs it.

Three failure modes matter here and they need to be distinguishable, because
each has a different fix and the middle one is the easy one to misdiagnose:

  1. No key set               -> the LLM path is off; the template path runs.
  2. Key set, model slug wrong -> a 404 from OpenRouter, which looks like an
                                  outage but is a typo. Model slugs are
                                  versioned and they move.
  3. Key set, model fine       -> a real completion comes back.

Run:  python scripts/check_llm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from sentinel.llm import config


def main() -> int:
    status = config.describe()
    print("OpenRouter configuration")
    for key, value in status.items():
        print(f"  {key:<18} {value}")
    print()

    if not config.is_configured():
        print("No OPENROUTER_API_KEY set.")
        print("The LLM narrative path is disabled; drafting uses the "
              "deterministic template.")
        print("This is a supported state -- see sentinel/llm/config.py.")
        print("To enable it: cp .env.example .env, add your key, export it.")
        return 0

    print(f"Calling {config.endpoint()} with model {config.MODEL!r} ...")
    payload = {
        "model": config.MODEL,
        "messages": [{"role": "user",
                      "content": "Reply with the single word: ready"}],
        "temperature": config.TEMPERATURE,
        "max_tokens": 16,
    }
    try:
        response = httpx.post(config.endpoint(), headers=config.headers(),
                              json=payload, timeout=config.TIMEOUT_SECONDS)
    except httpx.RequestError as exc:
        print(f"FAILED: transport error -- {exc!r}")
        print("Network or endpoint problem. The narrative path would fall "
              "back to the template here.")
        return 1

    if response.status_code == 401:
        print("FAILED: 401 -- the key was rejected. Check OPENROUTER_API_KEY.")
        return 1
    if response.status_code == 404:
        print(f"FAILED: 404 -- model slug {config.MODEL!r} did not resolve.")
        print("This is almost always a stale slug, not an outage. Check "
              "https://openrouter.ai/models and set SENTINEL_LLM_MODEL.")
        return 1
    if response.status_code >= 400:
        print(f"FAILED: HTTP {response.status_code} -- {response.text[:400]}")
        return 1

    body = response.json()
    text = body["choices"][0]["message"]["content"].strip()
    usage = body.get("usage", {})
    print(f"OK: model replied {text!r}")
    print(f"    resolved model: {body.get('model')}")
    print(f"    tokens: {usage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
