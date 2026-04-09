"""Unit tests for private CLI helper functions in riveter.cli."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from riveter.cli import (
    _attach_explanations,
    _filter_by_pattern,
    _print_summary,
    _setup_logging,
)
from riveter.rules import Rule
from riveter.scanner import ValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(rule_id: str, resource_type: str = "aws_instance") -> Rule:
    return Rule(
        {
            "id": rule_id,
            "resource_type": resource_type,
            "description": f"Rule {rule_id}",
            "assert": {"instance_type": "t3.large"},
        }
    )


def _make_result(
    rule_id: str,
    passed: bool,
    message: str = "",
    explanation: str | None = None,
) -> ValidationResult:
    rule = _make_rule(rule_id)
    resource = {"id": "web", "resource_type": "aws_instance"}
    msg = message or ("All checks passed" if passed else f"Expected t3.large, got t2.micro")
    result = ValidationResult(rule=rule, resource=resource, passed=passed, message=msg)
    result.explanation = explanation
    return result


# ---------------------------------------------------------------------------
# _setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def _reset_logging(self):
        """Remove all root-logger handlers so basicConfig takes effect."""
        root = logging.getLogger()
        for h in root.handlers[:]:
            root.removeHandler(h)

    def test_debug_true_sets_debug_level(self):
        self._reset_logging()
        _setup_logging(debug=True)
        assert logging.getLogger().level == logging.DEBUG

    def test_debug_false_sets_warning_level(self):
        self._reset_logging()
        _setup_logging(debug=False)
        assert logging.getLogger().level == logging.WARNING


# ---------------------------------------------------------------------------
# _filter_by_pattern
# ---------------------------------------------------------------------------


class TestFilterByPattern:
    def setup_method(self):
        self.rules = [
            _make_rule("ec2-check-type"),
            _make_rule("ec2-check-ami"),
            _make_rule("s3-public-access"),
            _make_rule("iam-role-policy"),
        ]

    def test_no_filters_returns_all(self):
        result = _filter_by_pattern(self.rules, [], [])
        assert result == self.rules

    def test_include_glob_prefix(self):
        result = _filter_by_pattern(self.rules, ["ec2-*"], [])
        ids = [r.id for r in result]
        assert "ec2-check-type" in ids
        assert "ec2-check-ami" in ids
        assert "s3-public-access" not in ids

    def test_include_glob_exact(self):
        result = _filter_by_pattern(self.rules, ["s3-public-access"], [])
        assert len(result) == 1
        assert result[0].id == "s3-public-access"

    def test_exclude_glob(self):
        result = _filter_by_pattern(self.rules, [], ["ec2-*"])
        ids = [r.id for r in result]
        assert "ec2-check-type" not in ids
        assert "ec2-check-ami" not in ids
        assert "s3-public-access" in ids

    def test_include_then_exclude(self):
        # Include ec2-* then exclude ec2-check-ami
        result = _filter_by_pattern(self.rules, ["ec2-*"], ["*-ami"])
        ids = [r.id for r in result]
        assert "ec2-check-type" in ids
        assert "ec2-check-ami" not in ids

    def test_include_no_match_returns_empty(self):
        result = _filter_by_pattern(self.rules, ["nonexistent-*"], [])
        assert result == []

    def test_exclude_all_returns_empty(self):
        result = _filter_by_pattern(self.rules, [], ["*"])
        assert result == []

    def test_multiple_include_patterns(self):
        result = _filter_by_pattern(self.rules, ["ec2-*", "s3-*"], [])
        ids = [r.id for r in result]
        assert "ec2-check-type" in ids
        assert "s3-public-access" in ids
        assert "iam-role-policy" not in ids

    def test_wildcard_include_returns_all(self):
        result = _filter_by_pattern(self.rules, ["*"], [])
        assert result == self.rules


# ---------------------------------------------------------------------------
# _print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_all_passing(self, capsys):
        results = [_make_result("r1", True), _make_result("r2", True)]
        _print_summary(results)
        # No assertion on exact output since Rich uses its own console,
        # but function should not raise.

    def test_mixed_results_no_exception(self):
        results = [
            _make_result("r1", True),
            _make_result("r2", False),
            _make_result("r3", False, message="SKIPPED: no matching resources"),
        ]
        # Should not raise
        _print_summary(results)

    def test_empty_results_no_exception(self):
        _print_summary([])


# ---------------------------------------------------------------------------
# _attach_explanations
# ---------------------------------------------------------------------------


class TestAttachExplanations:
    def test_no_api_key_prints_warning_and_returns(self):
        mock_explainer = MagicMock()
        mock_explainer.is_available.return_value = False

        results = [_make_result("r1", False)]
        with patch("riveter.cli.Explainer", return_value=mock_explainer):
            _attach_explanations(results)

        # Explanation should not be set
        assert results[0].explanation is None
        mock_explainer.explain.assert_not_called()

    def test_no_failing_results_skips_api_calls(self):
        mock_explainer = MagicMock()
        mock_explainer.is_available.return_value = True
        mock_explainer.get_scan_warning.return_value = None

        results = [_make_result("r1", True)]
        with patch("riveter.cli.Explainer", return_value=mock_explainer):
            _attach_explanations(results)

        mock_explainer.explain.assert_not_called()

    def test_failing_results_get_explanations(self):
        explanation_text = "This rule ensures the instance type is correct."
        mock_explainer = MagicMock()
        mock_explainer.is_available.return_value = True
        mock_explainer.explain.return_value = explanation_text
        mock_explainer.get_scan_warning.return_value = None

        results = [_make_result("r1", False)]
        with patch("riveter.cli.Explainer", return_value=mock_explainer):
            _attach_explanations(results)

        assert results[0].explanation == explanation_text

    def test_skipped_results_not_explained(self):
        mock_explainer = MagicMock()
        mock_explainer.is_available.return_value = True
        mock_explainer.get_scan_warning.return_value = None

        results = [_make_result("r1", False, message="SKIPPED: no matching resources")]
        with patch("riveter.cli.Explainer", return_value=mock_explainer):
            _attach_explanations(results)

        mock_explainer.explain.assert_not_called()

    def test_explain_exception_does_not_propagate(self):
        mock_explainer = MagicMock()
        mock_explainer.is_available.return_value = True
        mock_explainer.explain.side_effect = RuntimeError("API call failed")
        mock_explainer.get_scan_warning.return_value = None

        results = [_make_result("r1", False)]
        # Should not raise
        with patch("riveter.cli.Explainer", return_value=mock_explainer):
            _attach_explanations(results)

    def test_model_passed_to_explainer(self):
        mock_explainer = MagicMock()
        mock_explainer.is_available.return_value = True
        mock_explainer.get_scan_warning.return_value = None

        results = [_make_result("r1", True)]
        with patch("riveter.cli.Explainer", return_value=mock_explainer) as mock_cls:
            _attach_explanations(results, model="claude-opus-4-6")

        mock_cls.assert_called_once_with(model="claude-opus-4-6")
