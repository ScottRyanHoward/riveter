"""Tests for the core validation engine."""

from riveter.rules import Rule
from riveter.scanner import ValidationResult, validate_resources


def _make_rule(rule_id, resource_type, assert_dict, filter_dict=None):
    d = {
        "id": rule_id,
        "resource_type": resource_type,
        "assert": assert_dict,
    }
    if filter_dict:
        d["filter"] = filter_dict
    return Rule(d)


class TestValidationResult:
    def test_to_dict(self, simple_rule, ec2_resource):
        result = ValidationResult(
            rule=simple_rule,
            resource=ec2_resource,
            passed=True,
            message="All checks passed",
        )
        d = result.to_dict()
        assert d["rule_id"] == simple_rule.id
        assert d["passed"] is True
        assert d["resource_type"] == "aws_instance"


class TestValidateResources:
    def test_passing_check(self, simple_rule, ec2_resource):
        results = validate_resources([simple_rule], [ec2_resource])
        passing = [r for r in results if r.passed]
        assert len(passing) == 1

    def test_failing_check(self, ec2_resource):
        rule = _make_rule("bad-type", "aws_instance", {"instance_type": "m5.large"})
        results = validate_resources([rule], [ec2_resource])
        failed = [r for r in results if not r.passed and not r.message.startswith("SKIPPED:")]
        assert len(failed) == 1

    def test_resource_type_mismatch_skipped(self, ec2_resource):
        rule = _make_rule("s3-rule", "aws_s3_bucket", {"bucket": "present"})
        results = validate_resources([rule], [ec2_resource])
        skipped = [r for r in results if r.message.startswith("SKIPPED:")]
        assert len(skipped) == 1

    def test_wildcard_resource_type(self, ec2_resource):
        rule = _make_rule("any-rule", "*", {"id": "present"})
        results = validate_resources([rule], [ec2_resource])
        # Should match
        non_skipped = [r for r in results if not r.message.startswith("SKIPPED:")]
        assert len(non_skipped) >= 1

    def test_filter_applies(self, ec2_resource):
        rule = _make_rule(
            "prod-rule",
            "aws_instance",
            {"instance_type": "t3.large"},
            filter_dict={"tags.Environment": "production"},
        )
        results = validate_resources([rule], [ec2_resource])
        non_skipped = [r for r in results if not r.message.startswith("SKIPPED:")]
        assert len(non_skipped) == 1

    def test_filter_excludes_non_matching(self):
        resource = {
            "id": "dev_instance",
            "resource_type": "aws_instance",
            "instance_type": "t3.large",
            "tags": {"Environment": "development"},
        }
        rule = _make_rule(
            "prod-rule",
            "aws_instance",
            {"instance_type": "t3.large"},
            filter_dict={"tags.Environment": "production"},
        )
        results = validate_resources([rule], [resource])
        # Rule should not apply → should appear as SKIPPED
        skipped = [r for r in results if r.message.startswith("SKIPPED:")]
        assert len(skipped) == 1

    def test_multiple_resources(self, ec2_resource, s3_resource):
        ec2_rule = _make_rule("ec2-rule", "aws_instance", {"instance_type": "t3.large"})
        s3_rule = _make_rule("s3-rule", "aws_s3_bucket", {"bucket": "present"})
        results = validate_resources([ec2_rule, s3_rule], [ec2_resource, s3_resource])
        non_skipped = [r for r in results if not r.message.startswith("SKIPPED:")]
        assert len(non_skipped) == 2

    def test_resource_without_type_skipped(self):
        resource = {"id": "no_type", "instance_type": "t3.large"}
        rule = _make_rule("r1", "aws_instance", {"instance_type": "t3.large"})
        results = validate_resources([rule], [resource])
        # Resource with no type should be silently ignored; rule has no matches → SKIPPED
        skipped = [r for r in results if r.message.startswith("SKIPPED:")]
        assert len(skipped) == 1

    def test_execution_time_set(self, simple_rule, ec2_resource):
        results = validate_resources([simple_rule], [ec2_resource])
        for r in results:
            assert r.execution_time >= 0.0
