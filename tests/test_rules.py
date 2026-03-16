"""Tests for rule parsing, validation, and assertion evaluation."""

import textwrap

import pytest

from riveter.exceptions import FileSystemError, RuleValidationError
from riveter.rules import Rule, Severity, load_rules


class TestSeverity:
    def test_ordering(self):
        assert Severity.ERROR > Severity.WARNING
        assert Severity.WARNING > Severity.INFO
        assert Severity.ERROR >= Severity.ERROR
        assert Severity.INFO < Severity.WARNING

    def test_values(self):
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"


class TestRuleValidation:
    def test_missing_id_raises(self):
        with pytest.raises(RuleValidationError, match="id"):
            Rule({"resource_type": "aws_instance", "assert": {"x": "y"}})

    def test_missing_resource_type_raises(self):
        with pytest.raises(RuleValidationError):
            Rule({"id": "r1", "assert": {"x": "y"}})

    def test_missing_assert_raises(self):
        with pytest.raises(RuleValidationError):
            Rule({"id": "r1", "resource_type": "aws_instance"})

    def test_empty_assert_raises(self):
        with pytest.raises(RuleValidationError):
            Rule({"id": "r1", "resource_type": "aws_instance", "assert": {}})

    def test_invalid_severity_raises(self):
        with pytest.raises(RuleValidationError, match="Invalid severity"):
            Rule(
                {
                    "id": "r1",
                    "resource_type": "aws_instance",
                    "assert": {"x": "y"},
                    "severity": "critical",
                }
            )

    def test_invalid_regex_raises(self):
        with pytest.raises(RuleValidationError, match="regex"):
            Rule(
                {
                    "id": "r1",
                    "resource_type": "aws_instance",
                    "assert": {"instance_type": {"regex": "[invalid"}},
                }
            )


class TestRuleAttributes:
    def test_default_severity_is_error(self):
        rule = Rule({"id": "r1", "resource_type": "aws_instance", "assert": {"x": "y"}})
        assert rule.severity == Severity.ERROR

    def test_severity_warning(self):
        rule = Rule(
            {
                "id": "r1",
                "resource_type": "aws_instance",
                "severity": "warning",
                "assert": {"x": "y"},
            }
        )
        assert rule.severity == Severity.WARNING

    def test_wildcard_resource_type(self):
        rule = Rule({"id": "r1", "resource_type": "*", "assert": {"x": "y"}})
        assert rule.resource_type == "*"

    def test_metadata_stored(self):
        rule = Rule(
            {
                "id": "r1",
                "resource_type": "aws_instance",
                "assert": {"x": "y"},
                "metadata": {"tags": ["security"]},
            }
        )
        assert rule.metadata["tags"] == ["security"]

    def test_filter_stored(self):
        rule = Rule(
            {
                "id": "r1",
                "resource_type": "aws_instance",
                "filter": {"tags.Environment": "production"},
                "assert": {"x": "y"},
            }
        )
        assert rule.filter["tags.Environment"] == "production"


class TestMatchesResource:
    def test_no_filter_matches_all(self, ec2_resource):
        rule = Rule(
            {"id": "r1", "resource_type": "aws_instance", "assert": {"instance_type": "t3.large"}}
        )
        assert rule.matches_resource(ec2_resource) is True

    def test_filter_matches(self, ec2_resource):
        rule = Rule(
            {
                "id": "r1",
                "resource_type": "aws_instance",
                "filter": {"tags.Environment": "production"},
                "assert": {"instance_type": "t3.large"},
            }
        )
        assert rule.matches_resource(ec2_resource) is True

    def test_filter_no_match(self, ec2_resource):
        rule = Rule(
            {
                "id": "r1",
                "resource_type": "aws_instance",
                "filter": {"tags.Environment": "staging"},
                "assert": {"instance_type": "t3.large"},
            }
        )
        assert rule.matches_resource(ec2_resource) is False

    def test_filter_missing_path_no_match(self, ec2_resource):
        rule = Rule(
            {
                "id": "r1",
                "resource_type": "aws_instance",
                "filter": {"nonexistent.path": "value"},
                "assert": {"instance_type": "t3.large"},
            }
        )
        assert rule.matches_resource(ec2_resource) is False


class TestValidateAssertions:
    def _make_rule(self, assert_dict, **kwargs):
        return Rule(
            {
                "id": "test",
                "resource_type": "aws_instance",
                "assert": assert_dict,
                **kwargs,
            }
        )

    def test_eq_passes(self, ec2_resource):
        rule = self._make_rule({"instance_type": "t3.large"})
        results = rule.validate_assertions(ec2_resource)
        assert all(r.passed for r in results)

    def test_eq_fails(self, ec2_resource):
        rule = self._make_rule({"instance_type": "m5.large"})
        results = rule.validate_assertions(ec2_resource)
        assert not all(r.passed for r in results)

    def test_present_passes(self, ec2_resource):
        rule = self._make_rule({"tags.Environment": "present"})
        results = rule.validate_assertions(ec2_resource)
        assert all(r.passed for r in results)

    def test_present_fails_missing(self, ec2_resource):
        rule = self._make_rule({"tags.MissingKey": "present"})
        results = rule.validate_assertions(ec2_resource)
        assert any(not r.passed for r in results)

    def test_bool_false(self, ec2_resource):
        rule = self._make_rule({"associate_public_ip_address": False})
        results = rule.validate_assertions(ec2_resource)
        assert all(r.passed for r in results)

    def test_bool_true_nested(self, ec2_resource):
        rule = self._make_rule({"root_block_device.encrypted": True})
        results = rule.validate_assertions(ec2_resource)
        assert all(r.passed for r in results)

    def test_regex_operator(self, ec2_resource):
        rule = self._make_rule({"instance_type": {"regex": r"^(t3|m5)\.(large|xlarge)$"}})
        results = rule.validate_assertions(ec2_resource)
        assert all(r.passed for r in results)

    def test_gte_operator(self, ec2_resource):
        rule = self._make_rule({"root_block_device.volume_size": {"gte": 50}})
        results = rule.validate_assertions(ec2_resource)
        assert all(r.passed for r in results)

    def test_gte_operator_fails(self, ec2_resource):
        rule = self._make_rule({"root_block_device.volume_size": {"gte": 500}})
        results = rule.validate_assertions(ec2_resource)
        assert any(not r.passed for r in results)

    def test_missing_path_fails(self, ec2_resource):
        rule = self._make_rule({"nonexistent_attribute": "value"})
        results = rule.validate_assertions(ec2_resource)
        assert any(not r.passed for r in results)

    def test_multiple_assertions_all_pass(self, ec2_resource):
        rule = self._make_rule(
            {
                "instance_type": "t3.large",
                "root_block_device.encrypted": True,
                "tags.Environment": "present",
            }
        )
        results = rule.validate_assertions(ec2_resource)
        assert len(results) == 3
        assert all(r.passed for r in results)


class TestLoadRules:
    def test_loads_valid_file(self, tmp_path):
        rules_file = tmp_path / "rules.yml"
        rules_file.write_text(textwrap.dedent("""\
                rules:
                  - id: test-rule
                    resource_type: aws_instance
                    description: Test
                    severity: error
                    assert:
                      instance_type: t3.large
                """))
        rules = load_rules(str(rules_file))
        assert len(rules) == 1
        assert rules[0].id == "test-rule"

    def test_missing_file_raises(self):
        with pytest.raises(FileSystemError):
            load_rules("/nonexistent/path/rules.yml")

    def test_missing_rules_key_raises(self, tmp_path):
        f = tmp_path / "bad.yml"
        f.write_text("not_rules:\n  - id: x\n")
        with pytest.raises(RuleValidationError, match="top-level 'rules' key"):
            load_rules(str(f))

    def test_invalid_yaml_raises(self, tmp_path):
        f = tmp_path / "bad.yml"
        f.write_text("rules:\n  - [\ninvalid yaml here")
        with pytest.raises(RuleValidationError):
            load_rules(str(f))
