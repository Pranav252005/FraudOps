"""The LLM config surface, and the two properties that must not regress.

The interesting assertions here are not "the getters work". They are that an
unconfigured install is a *supported* state rather than a crash, and that the
key cannot leak through the status object that the console and the check
script both display.
"""
from __future__ import annotations

import importlib

import pytest

from sentinel.llm import config as llm_config


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-testkey-ABCD")
    monkeypatch.setenv("SENTINEL_LLM_MODEL", "vendor/some-model")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.test/api/v1/")
    return importlib.reload(llm_config)


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return importlib.reload(llm_config)


def teardown_module():
    # Leave the module in whatever state the ambient environment implies, so
    # one reloaded fixture cannot bleed into an unrelated test file.
    importlib.reload(llm_config)


def test_missing_key_is_a_supported_state_not_an_error(unconfigured):
    """No key must never raise. Every caller falls back to the template path,
    so a reviewer with no key can still run the whole system."""
    assert unconfigured.is_configured() is False
    assert unconfigured.describe()["configured"] is False


def test_describe_never_exposes_the_key(configured):
    """`describe()` is displayed in the console and printed by
    scripts/check_llm.py, which means it can end up in a screenshot."""
    status = configured.describe()
    rendered = repr(status)
    assert "sk-or-v1-testkey-ABCD" not in rendered
    assert status["key_suffix"] == "...ABCD"


def test_describe_key_suffix_is_none_when_unconfigured(unconfigured):
    assert unconfigured.describe()["key_suffix"] is None


def test_endpoint_normalises_a_trailing_slash(configured):
    """A base url pasted with a trailing slash is the obvious way to get a
    404 that looks like a bad model slug."""
    assert configured.endpoint() == "https://example.test/api/v1/chat/completions"


def test_headers_carry_bearer_and_attribution(configured):
    headers = configured.headers()
    assert headers["Authorization"] == "Bearer sk-or-v1-testkey-ABCD"
    assert headers["Content-Type"] == "application/json"
    assert headers["HTTP-Referer"]
    assert headers["X-Title"]


def test_temperature_defaults_to_deterministic(unconfigured):
    """A filed narrative is an auditable artifact: same case file, same text."""
    assert unconfigured.TEMPERATURE == 0


def test_llm_package_is_not_imported_by_the_measured_path():
    """Nothing in detection, scoring or evaluation may depend on the LLM --
    a non-deterministic component inside a measured path would contaminate
    every reported interval."""
    import pkgutil

    import sentinel.detect
    import sentinel.eval

    offenders = []
    for package in (sentinel.detect, sentinel.eval):
        for module in pkgutil.iter_modules(package.__path__):
            name = f"{package.__name__}.{module.name}"
            source = importlib.import_module(name).__dict__
            if any(getattr(v, "__name__", "").startswith("sentinel.llm")
                   for v in source.values()):
                offenders.append(name)
    assert offenders == []
