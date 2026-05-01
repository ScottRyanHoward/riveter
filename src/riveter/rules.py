# Copyright (c) 2026 Scott Howard
# SPDX-License-Identifier: MIT

"""Rule parsing and validation.

Rules are defined in YAML and describe how to validate Terraform resources.

Rule format:
    rules:
      - id: unique-rule-id
        resource_type: aws_instance          # Terraform resource type, or "*" for all
        description: Human-readable summary
        filter:                               # optional — conditions a resource must match
          tags.Environment: production
        assert:                               # one or more assertions that must be true
          root_block_device.encrypted: true
          instance_type:
            regex: "^(t3|m5)\\\\.(large|xlarge)$"

Supported operators in assert:
    eq, ne, gt, gte, lt, lte — numeric/equality comparisons
    regex                     — regular expression match
    contains                  — list contains value
    length                    — list/string length (int or dict with operators)
    subset                    — list is a subset of another list
    none_match                — no item in list matches all fields of any given pattern
    present                   — value exists and is non-empty (special keyword)
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from .exceptions import FileSystemError, RuleValidationError
from .operators import AttributeResolutionError, NestedAttributeResolver, OperatorFactory

log = logging.getLogger(__name__)

_VALID_OPERATORS = {
    "gt",
    "lt",
    "gte",
    "lte",
    "ne",
    "eq",
    "regex",
    "contains",
    "not_contains",
    "length",
    "subset",
    "none_match",
}


_EXPECTED_LABELS: Dict[str, Optional[str]] = {
    "eq": "expected",
    "ne": "expected",
    "gt": "expected",
    "gte": "expected",
    "lt": "expected",
    "lte": "expected",
    "regex": "pattern",
    "contains": "required_value",
    "not_contains": "excluded_value",
    "length": "expected_length",
    "subset": "required_subset",
    "none_match": "forbidden_patterns",
    "present": None,
    "absent": None,
}

_OP_PASS_MESSAGES: Dict[str, Any] = {
    "eq": lambda path, val: f"{path} equals {val!r}",
    "ne": lambda path, val: f"{path} does not equal {val!r}",
    "gt": lambda path, val: f"{path} > {val}",
    "gte": lambda path, val: f"{path} >= {val}",
    "lt": lambda path, val: f"{path} < {val}",
    "lte": lambda path, val: f"{path} <= {val}",
    "regex": lambda path, val: f"{path} matches pattern {val!r}",
    "contains": lambda path, val: f"{path} contains {val!r}",
    "not_contains": lambda path, val: f"{path} does not contain {val!r}",
    "length": lambda path, val: f"{path} length satisfies {val}",
    "subset": lambda path, val: f"{path} contains all required values",
    "none_match": lambda path, val: f"No forbidden {path} patterns found",
}


@dataclass
class AssertionResult:
    """Result of evaluating a single assertion within a rule."""

    property_path: str
    operator: str
    expected: Any
    actual: Any
    passed: bool
    message: str

    @property
    def expected_label(self) -> Optional[str]:
        """Semantic JSON key for the expected value — operator-specific, or None to omit."""
        return _EXPECTED_LABELS.get(self.operator, "expected")


class Rule:
    """A single validation rule applied to Terraform resources.

    Attributes:
        id:               Unique rule identifier.
        resource_type:    Terraform resource type (e.g. ``aws_instance``) or ``"*"`` for all.
        description:      Human-readable summary of what the rule checks.
        filter:           Key/value conditions a resource must match for the rule to apply.
        assert_conditions: Assertions that must all be true for the rule to pass.
        metadata:         Arbitrary extra metadata (tags, references, etc.).
    """

    def __init__(self, rule_dict: Dict[str, Any], rule_file: Optional[str] = None) -> None:
        self.rule_file = rule_file
        self._validate_required_fields(rule_dict)

        self.id: str = rule_dict["id"]
        self.resource_type: str = rule_dict["resource_type"]
        self.description: str = rule_dict.get("description", "No description provided")
        self.filter: Dict[str, Any] = rule_dict.get("filter", {})
        self.assert_conditions: Dict[str, Any] = rule_dict["assert"]
        self.metadata: Dict[str, Any] = rule_dict.get("metadata", {})
        self._resolver = NestedAttributeResolver()

        self._validate_assertions(self.assert_conditions)
        log.debug("Loaded rule %s for %s", self.id, self.resource_type)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_required_fields(self, rule_dict: Dict[str, Any]) -> None:
        missing = [f for f in ("id", "resource_type", "assert") if f not in rule_dict]
        if missing:
            raise RuleValidationError(
                f"Rule missing required fields: {', '.join(missing)}",
                rule_id=rule_dict.get("id", "unknown"),
                rule_file=self.rule_file,
            )
        if not isinstance(rule_dict["id"], str) or not rule_dict["id"].strip():
            raise RuleValidationError("Rule 'id' must be a non-empty string")
        if (
            not isinstance(rule_dict["resource_type"], str)
            or not rule_dict["resource_type"].strip()
        ):
            raise RuleValidationError("Rule 'resource_type' must be a non-empty string")
        if not isinstance(rule_dict["assert"], dict) or not rule_dict["assert"]:
            raise RuleValidationError(
                "Rule 'assert' must be a non-empty dictionary",
                rule_id=rule_dict.get("id", "unknown"),
            )

    def _is_operator_config(self, d: Dict[str, Any]) -> bool:
        """Returns True if d is a dict whose keys are all valid operator names."""
        return bool(d) and all(k in _VALID_OPERATORS for k in d)

    def _validate_assertions(self, assertions: Dict[str, Any]) -> None:
        """Validate assertion syntax, including regex compilation."""
        for _key, value in assertions.items():
            if isinstance(value, dict) and self._is_operator_config(value):
                if "regex" in value:
                    try:
                        re.compile(str(value["regex"]))
                    except re.error as exc:
                        raise RuleValidationError(
                            f"Invalid regex in rule {self.id!r}: {exc}",
                            rule_id=self.id,
                            rule_file=self.rule_file,
                        ) from exc

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def matches_resource(self, resource: Dict[str, Any]) -> bool:
        """Return True if the resource satisfies all filter conditions.

        If the rule has no filter, it matches every resource of the right type.
        """
        for path, expected_value in self.filter.items():
            try:
                actual = self._resolver.resolve_path(resource, path)
            except AttributeResolutionError:
                return False
            if expected_value == "present":
                if actual is None or actual == "" or actual == [] or actual == {}:
                    return False
            elif expected_value == "absent":
                if actual is not None and actual != "" and actual != [] and actual != {}:
                    return False
            elif actual != expected_value:
                return False
        return True

    def validate_assertions(self, resource: Dict[str, Any]) -> List[AssertionResult]:
        """Evaluate all assertions against the resource and return results."""
        results: List[AssertionResult] = []

        for path, expected in self.assert_conditions.items():
            try:
                actual = self._resolver.resolve_path(resource, path)
            except AttributeResolutionError:
                actual = None

            if isinstance(expected, dict) and self._is_operator_config(expected):
                # One or more operator assertions on the same property
                for op_name, op_value in expected.items():
                    operator = OperatorFactory.create_operator(op_name)
                    passed = operator.evaluate(actual, op_value)
                    pass_fn = _OP_PASS_MESSAGES.get(op_name)
                    results.append(
                        AssertionResult(
                            property_path=path,
                            operator=op_name,
                            expected=op_value,
                            actual=actual,
                            passed=passed,
                            message=(
                                pass_fn(path, op_value)
                                if passed and pass_fn
                                else operator.get_error_message(actual, op_value)
                            ),
                        )
                    )

            elif expected == "present":
                passed = actual is not None and actual != "" and actual != [] and actual != {}
                results.append(
                    AssertionResult(
                        property_path=path,
                        operator="present",
                        expected="present",
                        actual=actual,
                        passed=passed,
                        message=(f"{path} is present" if passed else f"{path} is missing or empty"),
                    )
                )

            elif expected == "absent":
                passed = actual is None or actual == "" or actual == [] or actual == {}
                results.append(
                    AssertionResult(
                        property_path=path,
                        operator="absent",
                        expected="absent",
                        actual=actual,
                        passed=passed,
                        message=(
                            f"{path} is absent"
                            if passed
                            else f"{path} should be absent but has value {actual!r}"
                        ),
                    )
                )

            else:
                # Simple equality check
                passed = actual == expected
                results.append(
                    AssertionResult(
                        property_path=path,
                        operator="eq",
                        expected=expected,
                        actual=actual,
                        passed=passed,
                        message=(
                            f"{path} equals {expected!r}"
                            if passed
                            else f"Expected {path!r} to equal {expected!r}, got {actual!r}"
                        ),
                    )
                )

        return results


def load_rules(rules_file: str) -> List[Rule]:
    """Load and parse rules from a YAML file.

    The file must have a top-level ``rules`` key containing a list of rule dicts.

    Args:
        rules_file: Path to the rules YAML file.

    Returns:
        List of parsed :class:`Rule` objects.

    Raises:
        FileSystemError: If the file does not exist or cannot be read.
        RuleValidationError: If the file is malformed or a rule is invalid.
    """
    try:
        with open(rules_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise FileSystemError(
            f"Rules file not found: {rules_file}",
            file_path=rules_file,
        ) from exc
    except yaml.YAMLError as exc:
        raise RuleValidationError(
            f"Invalid YAML in rules file {rules_file!r}: {exc}",
        ) from exc

    if not isinstance(data, dict) or "rules" not in data:
        raise RuleValidationError(
            f"Rules file {rules_file!r} must contain a top-level 'rules' key",
        )

    rules: List[Rule] = []
    for rule_dict in data["rules"]:
        if not isinstance(rule_dict, dict):
            raise RuleValidationError(f"Each item under 'rules' must be a dict in {rules_file!r}")
        rules.append(Rule(rule_dict, rule_file=rules_file))

    log.debug("Loaded %d rules from %s", len(rules), rules_file)
    return rules
