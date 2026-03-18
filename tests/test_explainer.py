"""Tests for the AI-powered violation explainer."""

import os
from unittest.mock import MagicMock, patch

from riveter.explainer import Explainer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RULE = {
    "id": "ec2_no_public_ip",
    "description": "EC2 instances must not have public IPs",
    "severity": "error",
    "assert": {"metadata_options.http_tokens": "required"},
}

_RESOURCE_ATTRS = {
    "instance_type": "t3.micro",
    "metadata_options": {"http_tokens": "optional"},
    "tags": {"Environment": "production"},
}


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------


def test_is_available_returns_false_without_env_var():
    """Explainer.is_available() must be False when ANTHROPIC_API_KEY is not set."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        explainer = Explainer()
        assert explainer.is_available() is False


def test_is_available_returns_false_when_package_missing():
    """Explainer.is_available() must be False when anthropic is not installed."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
        with patch("builtins.__import__", side_effect=ImportError("No module named 'anthropic'")):
            explainer = Explainer()
            assert explainer.is_available() is False


# ---------------------------------------------------------------------------
# Error-handling tests
# ---------------------------------------------------------------------------


def test_explain_returns_none_on_api_error():
    """explain() must return None when the Anthropic client raises an exception."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("simulated API error")

    explainer = Explainer()
    explainer._available = True
    explainer._client = mock_client

    result = explainer.explain(_RULE, "web_server", "aws_instance", _RESOURCE_ATTRS)
    assert result is None


def test_explain_returns_none_when_unavailable():
    """explain() returns None immediately when is_available() is False."""
    with patch.dict(os.environ, {}, clear=True):
        explainer = Explainer()
        assert explainer.is_available() is False
        result = explainer.explain(_RULE, "web_server", "aws_instance", _RESOURCE_ATTRS)
        assert result is None


# ---------------------------------------------------------------------------
# Prompt content tests
# ---------------------------------------------------------------------------


def _make_explainer_with_capture() -> tuple[Explainer, list[str]]:
    """Return an Explainer whose client records the prompt it receives."""
    captured: list[str] = []

    mock_content = MagicMock()
    mock_content.text = "This is a security risk explanation."
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    def fake_create(**kwargs: object) -> MagicMock:
        messages = kwargs.get("messages", [])
        for msg in messages:
            if isinstance(msg, dict):
                captured.append(str(msg.get("content", "")))
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = fake_create

    explainer = Explainer()
    explainer._available = True
    explainer._client = mock_client

    return explainer, captured


def test_prompt_contains_rule_id():
    """The prompt sent to Claude must contain the rule ID."""
    explainer, captured = _make_explainer_with_capture()
    explainer.explain(_RULE, "web_server", "aws_instance", _RESOURCE_ATTRS)
    assert captured, "No prompt was captured"
    assert "ec2-imdsv2-required" in captured[0]


def test_prompt_contains_resource_name():
    """The prompt sent to Claude must contain the resource name."""
    explainer, captured = _make_explainer_with_capture()
    explainer.explain(_RULE, "web_server", "aws_instance", _RESOURCE_ATTRS)
    assert captured, "No prompt was captured"
    assert "web_server" in captured[0]


def test_prompt_contains_failed_assertion():
    """The prompt sent to Claude must contain the failed assertion."""
    explainer, captured = _make_explainer_with_capture()
    explainer.explain(_RULE, "web_server", "aws_instance", _RESOURCE_ATTRS)
    assert captured, "No prompt was captured"
    # The assert conditions dict is serialised into the prompt
    assert "http_tokens" in captured[0]


# ---------------------------------------------------------------------------
# Scan-level warning tests
# ---------------------------------------------------------------------------


def test_get_scan_warning_returns_none_on_success():
    """No warning is returned when no errors occurred."""
    explainer = Explainer()
    assert explainer.get_scan_warning() is None


def test_get_scan_warning_auth_error():
    """Auth errors produce the correct warning message."""
    explainer = Explainer()
    explainer._auth_error = True
    warning = explainer.get_scan_warning()
    assert warning is not None
    assert "invalid or expired" in warning


def test_get_scan_warning_rate_limit():
    explainer = Explainer()
    explainer._rate_limit_error = True
    warning = explainer.get_scan_warning()
    assert warning is not None
    assert "rate limit" in warning.lower()


def test_get_scan_warning_timeout():
    explainer = Explainer()
    explainer._timeout_error = True
    warning = explainer.get_scan_warning()
    assert warning is not None
    assert "reach Anthropic" in warning
