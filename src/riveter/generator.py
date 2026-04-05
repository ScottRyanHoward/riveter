# Copyright (c) 2026 Scott Howard
# SPDX-License-Identifier: MIT

"""LLM-assisted rule generation via the Anthropic API.

Usage:
    generator = RuleGenerator(model="claude-sonnet-4-20250514")
    if generator.is_available():
        rules = generator.generate_for_resource_type(resource_type, sample_resource, focus=focus)
"""

import logging
import os
from typing import Any, Dict, List, Optional

import yaml

from .exceptions import RuleValidationError
from .rules import Rule

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-20250514"

_RULE_SCHEMA_REFERENCE = """\
Each rule must have this YAML structure:

  - id: unique-kebab-case-id          # required: lowercase letters, digits, hyphens
    resource_type: aws_instance       # required: Terraform resource type (e.g. aws_instance)
    description: Human-readable text  # optional but recommended
    filter:                           # optional: only apply rule when these attrs match
      tags.Environment: production
    assert:                           # required: one or more assertions (all must pass)
      root_block_device.encrypted: true
    metadata:                         # optional
      tags: [security]
      references:
        - https://example.com/docs

Supported assertion operators (used as nested dict under the attribute path):
  eq, ne          — equality / inequality
  gt, gte         — greater than, greater than or equal
  lt, lte         — less than, less than or equal
  regex           — regular expression match (string)
  contains        — list contains a value
  length          — list or string length check (int for exact, or dict with operators)
  subset          — list is a subset of another
  present         — value exists and is non-empty (use as a bare keyword value: present)

Simple equality is written without an operator:
  instance_type: t3.micro            # equals "t3.micro"
  root_block_device.encrypted: true  # equals true

Nested paths use dot-notation:
  root_block_device.encrypted        # nested object
  tags.Environment                   # tag value
  ingress[0].cidr_blocks             # array element"""

_FEW_SHOT_EXAMPLES = """\
Example rules for reference:

rules:
  - id: ec2-must-be-encrypted
    resource_type: aws_instance
    description: All EC2 root EBS volumes must be encrypted
    assert:
      root_block_device.encrypted: true
    metadata:
      tags: [encryption, ec2]

  - id: ec2-approved-instance-types
    resource_type: aws_instance
    description: EC2 instances must use approved instance types
    assert:
      instance_type:
        regex: "^(t3|t4g|m5|m6i)\\\\.(micro|small|medium|large|xlarge|2xlarge)$"

  - id: ec2-required-tags
    resource_type: aws_instance
    description: EC2 instances must have required governance tags
    assert:
      tags.Environment: present
      tags.Owner: present"""


class RuleGenerator:
    """Generates Riveter rules for a given Terraform resource type using Claude.

    The Anthropic client is lazily imported — the class is safe to instantiate
    even when the ``anthropic`` package is not installed or no API key is set.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        self._model = model or _DEFAULT_MODEL
        self._client: Any = None  # anthropic.Anthropic once initialized
        self._available = False
        self._auth_error = False
        self._rate_limit_error = False
        self._timeout_error = False
        self._connection_error = False

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            try:
                import anthropic  # noqa: PLC0415

                self._client = anthropic.Anthropic(api_key=api_key)
                self._available = True
            except ImportError:
                log.debug("anthropic package not installed; AI rule generation unavailable")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True only if ANTHROPIC_API_KEY is set and anthropic is installed."""
        return self._available

    def generate_for_resource_type(
        self,
        resource_type: str,
        sample_resource: Dict[str, Any],
        focus: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Generate 3–5 Riveter rules for a given Terraform resource type.

        Args:
            resource_type:   Terraform resource type (e.g. ``aws_instance``).
            sample_resource: A representative resource attribute dict for context.
            focus:           Optional plain-text guidance, e.g. "PCI-DSS compliance"
                             or "cost optimization".

        Returns:
            List of validated rule dicts ready for YAML serialisation.
            Returns an empty list on any failure.
        """
        if not self._available or self._client is None:
            return []

        prompt = self._build_prompt(resource_type, sample_resource, focus)
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            content = message.content
            if content and hasattr(content[0], "text"):
                raw = str(content[0].text).strip()
                return self._parse_and_validate(raw, resource_type)
            return []
        except Exception as exc:  # noqa: BLE001
            self._classify_error(exc)
            log.debug("Anthropic API error during rule generation: %s", exc)
            return []

    def get_warning(self) -> Optional[str]:
        """Return a one-line warning if any API errors occurred.

        Returns None if no errors occurred.
        """
        if self._auth_error:
            return (
                "✗ Anthropic API key is invalid or expired. "
                "Check your key at console.anthropic.com"
            )
        if self._rate_limit_error:
            return "✗ Anthropic rate limit hit. Some resource types may have been skipped."
        if self._timeout_error:
            return "✗ Could not reach Anthropic API. Some resource types may have been skipped."
        if self._connection_error:
            return "✗ Anthropic API call failed. Run with --debug for details."
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_error(self, exc: Exception) -> None:
        name = type(exc).__name__
        if "Authentication" in name or "Auth" in name:
            self._auth_error = True
        elif "RateLimit" in name:
            self._rate_limit_error = True
        elif "Timeout" in name or "timeout" in name.lower():
            self._timeout_error = True
        else:
            self._connection_error = True

    def _build_prompt(
        self,
        resource_type: str,
        sample_resource: Dict[str, Any],
        focus: Optional[str],
    ) -> str:
        # Strip internal riveter keys to keep the prompt clean
        attrs: Dict[str, Any] = {
            k: v for k, v in sample_resource.items() if k not in ("resource_type", "id")
        }
        attrs_yaml = yaml.dump(attrs, default_flow_style=False).strip()

        focus_line = (
            f"\nFocus area: {focus}\n"
            if focus
            else "\nFocus area: general security and operational best practices\n"
        )

        return (
            "You are an infrastructure security expert. Generate Riveter rules for the "
            f"Terraform resource type '{resource_type}'.\n"
            f"{focus_line}\n"
            f"{_RULE_SCHEMA_REFERENCE}\n\n"
            f"{_FEW_SHOT_EXAMPLES}\n\n"
            f"Here is a sample '{resource_type}' resource from the user's Terraform:\n\n"
            f"{attrs_yaml}\n\n"
            "Generate 3-5 rules specifically for this resource type. Rules must:\n"
            "  - Use only attributes visible in the sample resource or commonly present "
            f"on '{resource_type}' resources\n"
            "  - Be actionable and enforceable (not aspirational)\n"
            "  - Cover different aspects (encryption, access control, tagging, etc.) "
            "where applicable\n\n"
            "Return ONLY a valid YAML block starting with 'rules:' and nothing else. "
            "No explanation, no markdown fences, no preamble."
        )

    def _parse_and_validate(self, raw: str, resource_type: str) -> List[Dict[str, Any]]:
        """Parse LLM YAML output and validate each rule. Silently drops invalid ones."""
        # Strip accidental markdown code fences
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop first and last fence lines
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            log.debug("Failed to parse generated YAML for %s: %s", resource_type, exc)
            return []

        if not isinstance(parsed, dict):
            log.debug("Generated output for %s is not a YAML dict", resource_type)
            return []

        rules_list = parsed.get("rules", [])
        if not isinstance(rules_list, list):
            log.debug("Generated 'rules' key for %s is not a list", resource_type)
            return []

        valid: List[Dict[str, Any]] = []
        for rule_dict in rules_list:
            if not isinstance(rule_dict, dict):
                continue
            try:
                Rule(rule_dict)
                valid.append(rule_dict)
            except (RuleValidationError, Exception) as exc:  # noqa: BLE001
                log.debug(
                    "Dropping invalid generated rule '%s': %s",
                    rule_dict.get("id", "<unknown>"),
                    exc,
                )

        return valid
