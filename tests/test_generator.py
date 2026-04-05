"""Tests for the AI-powered rule generator."""

import os
from unittest.mock import MagicMock, patch

import pytest

from riveter.generator import RuleGenerator

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_SAMPLE_RESOURCE = {
    "id": "web_server",
    "resource_type": "aws_instance",
    "instance_type": "t3.micro",
    "ami": "ami-0c55b159cbfafe1f0",
    "associate_public_ip_address": True,
    "root_block_device": {"encrypted": False, "volume_size": 20},
    "tags": {"Environment": "production", "Owner": "team@example.com"},
}

_VALID_RULES_YAML = """\
rules:
  - id: ec2-must-be-encrypted
    resource_type: aws_instance
    description: EC2 root volumes must be encrypted
    severity: error
    assert:
      root_block_device.encrypted: true

  - id: ec2-required-tags
    resource_type: aws_instance
    description: EC2 instances must have required tags
    severity: error
    assert:
      tags.Environment: present
      tags.Owner: present
"""

_YAML_WITH_INVALID_RULE = """\
rules:
  - id: ec2-valid-rule
    resource_type: aws_instance
    description: A valid rule
    severity: error
    assert:
      root_block_device.encrypted: true

  - id: ""
    resource_type: aws_instance
    assert:
      some_attr: true

  - resource_type: aws_instance
    assert:
      some_attr: true
"""


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------


def test_is_available_returns_false_without_env_var():
    """RuleGenerator.is_available() must be False when ANTHROPIC_API_KEY is not set."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        generator = RuleGenerator()
        assert generator.is_available() is False


def test_is_available_returns_false_when_package_missing():
    """RuleGenerator.is_available() must be False when anthropic is not installed."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
        with patch("builtins.__import__", side_effect=ImportError("No module named 'anthropic'")):
            generator = RuleGenerator()
            assert generator.is_available() is False


def test_is_available_returns_true_with_key_and_package():
    """RuleGenerator.is_available() is True when key is set and package importable."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            generator = RuleGenerator()
            assert generator.is_available() is True


# ---------------------------------------------------------------------------
# generate_for_resource_type – success path
# ---------------------------------------------------------------------------


def _make_generator_returning(yaml_text: str) -> RuleGenerator:
    """Return a RuleGenerator whose client responds with the given YAML text."""
    mock_content = MagicMock()
    mock_content.text = yaml_text
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    generator = RuleGenerator()
    generator._available = True
    generator._client = mock_client
    return generator


def test_generate_returns_list_of_dicts_on_success():
    """generate_for_resource_type returns a list of dicts for valid YAML."""
    generator = _make_generator_returning(_VALID_RULES_YAML)
    rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    assert isinstance(rules, list)
    assert len(rules) == 2
    assert all(isinstance(r, dict) for r in rules)


def test_generated_rules_have_required_fields():
    """Each returned rule dict has id, resource_type, and assert keys."""
    generator = _make_generator_returning(_VALID_RULES_YAML)
    rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    for rule in rules:
        assert "id" in rule
        assert "resource_type" in rule
        assert "assert" in rule


def test_invalid_rules_are_silently_dropped():
    """Rules with empty id or missing required fields are dropped; valid ones kept."""
    generator = _make_generator_returning(_YAML_WITH_INVALID_RULE)
    rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    assert len(rules) == 1
    assert rules[0]["id"] == "ec2-valid-rule"


def test_generate_strips_markdown_fences():
    """LLM output wrapped in markdown fences is parsed correctly."""
    fenced = f"```yaml\n{_VALID_RULES_YAML}```"
    generator = _make_generator_returning(fenced)
    rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    assert len(rules) == 2


def test_generate_returns_empty_on_api_error():
    """generate_for_resource_type returns [] when the Anthropic client raises."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("simulated API error")

    generator = RuleGenerator()
    generator._available = True
    generator._client = mock_client

    rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    assert rules == []


def test_generate_returns_empty_when_unavailable():
    """generate_for_resource_type returns [] immediately when is_available() is False."""
    with patch.dict(os.environ, {}, clear=True):
        generator = RuleGenerator()
        assert generator.is_available() is False
        rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
        assert rules == []


def test_generate_returns_empty_on_invalid_yaml():
    """generate_for_resource_type returns [] when LLM returns unparseable text."""
    generator = _make_generator_returning("this is not yaml: [[[")
    rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    assert rules == []


def test_generate_returns_empty_when_no_rules_key():
    """generate_for_resource_type returns [] when YAML has no 'rules' key."""
    generator = _make_generator_returning("some_other_key:\n  - foo: bar\n")
    rules = generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    assert rules == []


# ---------------------------------------------------------------------------
# Prompt content tests
# ---------------------------------------------------------------------------


def _capture_prompt(yaml_text: str = _VALID_RULES_YAML) -> str:
    """Return the prompt string sent to the Anthropic client."""
    captured: list[str] = []

    mock_content = MagicMock()
    mock_content.text = yaml_text
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

    generator = RuleGenerator()
    generator._available = True
    generator._client = mock_client
    generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE)
    return captured[0] if captured else ""


def test_prompt_contains_resource_type():
    """Prompt must mention the resource type being analyzed."""
    prompt = _capture_prompt()
    assert "aws_instance" in prompt


def test_prompt_contains_operator_examples():
    """Prompt must describe the available assertion operators."""
    prompt = _capture_prompt()
    assert "regex" in prompt
    assert "present" in prompt
    assert "gte" in prompt


def test_prompt_contains_focus_when_provided():
    """Optional focus string must appear in the prompt."""
    captured: list[str] = []

    mock_content = MagicMock()
    mock_content.text = _VALID_RULES_YAML
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

    generator = RuleGenerator()
    generator._available = True
    generator._client = mock_client
    generator.generate_for_resource_type("aws_instance", _SAMPLE_RESOURCE, focus="PCI-DSS")

    assert captured
    assert "PCI-DSS" in captured[0]


def test_prompt_contains_resource_attributes():
    """Prompt must include actual resource attributes from the sample."""
    prompt = _capture_prompt()
    # The sample resource has these attributes
    assert "t3.micro" in prompt
    assert "root_block_device" in prompt


# ---------------------------------------------------------------------------
# Warning / error classification tests
# ---------------------------------------------------------------------------


def test_get_warning_returns_none_on_success():
    """No warning when no errors have occurred."""
    generator = RuleGenerator()
    assert generator.get_warning() is None


def test_get_warning_auth_error():
    generator = RuleGenerator()
    generator._auth_error = True
    warning = generator.get_warning()
    assert warning is not None
    assert "invalid or expired" in warning


def test_get_warning_rate_limit():
    generator = RuleGenerator()
    generator._rate_limit_error = True
    warning = generator.get_warning()
    assert warning is not None
    assert "rate limit" in warning.lower()


def test_get_warning_timeout():
    generator = RuleGenerator()
    generator._timeout_error = True
    warning = generator.get_warning()
    assert warning is not None
    assert "reach Anthropic" in warning


def test_classify_error_sets_auth_flag():
    generator = RuleGenerator()

    class AuthenticationError(Exception):
        pass

    generator._classify_error(AuthenticationError("invalid key"))
    assert generator._auth_error is True


def test_classify_error_sets_rate_limit_flag():
    generator = RuleGenerator()

    class RateLimitError(Exception):
        pass

    generator._classify_error(RateLimitError("too many requests"))
    assert generator._rate_limit_error is True


def test_classify_error_sets_timeout_flag():
    generator = RuleGenerator()

    class TimeoutError(Exception):
        pass

    generator._classify_error(TimeoutError("request timed out"))
    assert generator._timeout_error is True


def test_classify_error_sets_connection_flag_for_unknown():
    generator = RuleGenerator()
    generator._classify_error(Exception("some unknown error"))
    assert generator._connection_error is True
