# Copyright (c) 2026 Scott Howard
# SPDX-License-Identifier: MIT

"""AI-powered violation explanations via the Anthropic API.

Usage:
    explainer = Explainer(model="claude-sonnet-4-20250514")
    if explainer.is_available():
        text = explainer.explain(rule_dict, resource_name, resource_type, resource_attrs)
"""

import logging
import os
from typing import Any, Dict, Optional

import yaml

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-20250514"


class Explainer:
    """Generates plain-English explanations of rule violations using Claude.

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
                log.debug("anthropic package not installed; AI explanations unavailable")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True only if ANTHROPIC_API_KEY is set and anthropic is installed."""
        return self._available

    def explain(
        self,
        rule: Dict[str, Any],
        resource_name: str,
        resource_type: str,
        resource_attrs: Dict[str, Any],
    ) -> Optional[str]:
        """Return a plain-English explanation of a rule violation.

        Args:
            rule:           Rule dict with keys ``id``, ``description``, ``severity``,
                            and ``assert`` (or ``assert_conditions``).
            resource_name:  Terraform resource name (e.g. ``web_server``).
            resource_type:  Terraform resource type (e.g. ``aws_instance``).
            resource_attrs: Full attribute dict for the resource.

        Returns:
            3–4 sentence explanation string, or ``None`` on any failure.
        """
        if not self._available or self._client is None:
            return None

        prompt = self._build_prompt(rule, resource_name, resource_type, resource_attrs)
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            content = message.content
            if content and hasattr(content[0], "text"):
                return str(content[0].text).strip()
            return None
        except Exception as exc:  # noqa: BLE001
            self._classify_error(exc)
            log.debug("Anthropic API error: %s", exc)
            return None

    def get_scan_warning(self) -> Optional[str]:
        """Return a one-line warning if any API errors occurred during this scan.

        Returns None if no errors occurred.  Intended to be printed once after
        all parallel explain() calls complete.
        """
        if self._auth_error:
            return (
                "✗ Anthropic API key is invalid or expired. "
                "Check your key at console.anthropic.com"
            )
        if self._rate_limit_error:
            return "✗ Anthropic rate limit hit. Explanations skipped for this scan."
        if self._timeout_error:
            return "✗ Could not reach Anthropic API. Scan results shown without explanations."
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
        rule: Dict[str, Any],
        resource_name: str,
        resource_type: str,
        resource_attrs: Dict[str, Any],
    ) -> str:
        rule_id = rule.get("id", "unknown")
        description = rule.get("description", "No description provided")
        severity = rule.get("severity", "error")
        # Support both Rule objects serialised via rule_dict and raw dicts
        assert_conditions = rule.get("assert_conditions", rule.get("assert", {}))

        # Limit attrs to keep prompt under 500 tokens
        safe_attrs: Dict[str, Any] = {}
        for k, v in resource_attrs.items():
            if k not in ("resource_type", "id"):
                safe_attrs[k] = v

        attrs_yaml = yaml.dump(safe_attrs, default_flow_style=False).strip()

        return (
            "A Terraform infrastructure security rule has been violated.\n\n"
            f"Rule ID: {rule_id}\n"
            f"Description: {description}\n"
            f"Severity: {severity}\n"
            f"Failed assertion(s): {assert_conditions}\n\n"
            f"Resource type: {resource_type}\n"
            f"Resource name: {resource_name}\n"
            f"Resource attributes:\n{attrs_yaml}\n\n"
            "In 3-4 sentences, explain:\n"
            "1. Why this is a security risk\n"
            "2. What an attacker could do if this misconfiguration exists\n"
            "3. The exact Terraform change needed to remediate this violation\n\n"
            "Be specific and actionable. Do not repeat the rule ID or resource name."
        )
