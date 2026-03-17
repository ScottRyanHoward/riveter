"""Core validation engine: applies rules to Terraform resources."""

import time
from typing import Any, Dict, List, Optional

from .rules import AssertionResult, Rule, Severity


class ValidationResult:
    """Result of validating a single resource against a single rule.

    Attributes:
        rule:              The rule that was evaluated.
        resource:          The Terraform resource that was checked.
        passed:            Whether all assertions in the rule passed.
        message:           Human-readable summary of the result.
        severity:          Severity level inherited from the rule.
        assertion_results: Individual assertion outcomes.
        execution_time:    Wall-clock time taken to evaluate the rule (seconds).
        explanation:       Optional AI-generated plain-English explanation (``--explain`` flag).
    """

    def __init__(
        self,
        rule: Rule,
        resource: Dict[str, Any],
        passed: bool,
        message: str,
        assertion_results: List[AssertionResult] | None = None,
        execution_time: float = 0.0,
        explanation: Optional[str] = None,
    ) -> None:
        self.rule = rule
        self.resource = resource
        self.passed = passed
        self.message = message
        self.severity = rule.severity
        self.assertion_results: List[AssertionResult] = assertion_results or []
        self.execution_time = execution_time
        self.explanation: Optional[str] = explanation

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "rule_id": self.rule.id,
            "resource_type": self.resource.get("resource_type"),
            "resource_id": self.resource.get("id"),
            "passed": self.passed,
            "severity": self.severity.value,
            "message": self.message,
            "explanation": self.explanation,
            "execution_time": self.execution_time,
            "assertion_results": [
                {
                    "property_path": ar.property_path,
                    "operator": ar.operator,
                    "expected": ar.expected,
                    "actual": ar.actual,
                    "passed": ar.passed,
                    "message": ar.message,
                }
                for ar in self.assertion_results
            ],
        }


def validate_resources(
    rules: List[Rule],
    resources: List[Dict[str, Any]],
    min_severity: Severity = Severity.INFO,
) -> List[ValidationResult]:
    """Apply rules to resources and return validation results.

    For each (rule, resource) pair where the resource type matches and the
    rule's filter conditions are met, every assertion in the rule is evaluated.
    Rules that match no resources are reported as SKIPPED.

    Args:
        rules:        Rules to apply.
        resources:    Terraform resources extracted from HCL.
        min_severity: Only evaluate rules at or above this severity level.

    Returns:
        List of :class:`ValidationResult` objects.
    """
    results: List[ValidationResult] = []
    active_rules = [r for r in rules if r.severity >= min_severity]
    applied: set[str] = set()

    for resource in resources:
        if "resource_type" not in resource:
            continue

        for rule in active_rules:
            if rule.resource_type != "*" and resource.get("resource_type") != rule.resource_type:
                continue

            t0 = time.monotonic()
            if not rule.matches_resource(resource):
                continue

            applied.add(rule.id)
            assertion_results = rule.validate_assertions(resource)
            elapsed = time.monotonic() - t0

            all_passed = all(ar.passed for ar in assertion_results)
            if all_passed:
                message = "All checks passed"
            else:
                failed = [ar for ar in assertion_results if not ar.passed]
                if len(failed) == 1:
                    message = failed[0].message
                else:
                    paths = ", ".join(ar.property_path for ar in failed[:3])
                    extra = len(failed) - 3
                    message = (
                        f"Failed checks: {paths}, and {extra} more"
                        if extra > 0
                        else f"Failed checks: {paths}"
                    )

            results.append(
                ValidationResult(
                    rule=rule,
                    resource=resource,
                    passed=all_passed,
                    message=message,
                    assertion_results=assertion_results,
                    execution_time=elapsed,
                )
            )

    # Report rules that matched no resources
    for rule in active_rules:
        if rule.id not in applied:
            results.append(
                ValidationResult(
                    rule=rule,
                    resource={"resource_type": rule.resource_type, "id": "N/A"},
                    passed=False,
                    message="SKIPPED: No matching resources found for this rule",
                    assertion_results=[],
                    execution_time=0.0,
                )
            )

    return results
