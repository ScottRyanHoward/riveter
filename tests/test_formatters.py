"""Tests for output formatters."""

import json
import xml.etree.ElementTree as ET

from riveter.formatters import HTMLFormatter, JSONFormatter, JUnitXMLFormatter, SARIFFormatter
from riveter.rules import Rule
from riveter.scanner import ValidationResult


def _make_result(passed, rule_id="test-rule", resource_type="aws_instance", severity="error"):
    rule = Rule(
        {
            "id": rule_id,
            "resource_type": resource_type,
            "description": "Test rule",
            "severity": severity,
            "assert": {"x": "y"},
        }
    )
    resource = {"id": "my_resource", "resource_type": resource_type}
    return ValidationResult(
        rule=rule,
        resource=resource,
        passed=passed,
        message="All checks passed" if passed else "Assertion failed",
        assertion_results=[],
        execution_time=0.001,
    )


def _make_skipped(rule_id="skipped-rule"):
    rule = Rule(
        {
            "id": rule_id,
            "resource_type": "aws_instance",
            "assert": {"x": "y"},
        }
    )
    return ValidationResult(
        rule=rule,
        resource={"resource_type": "aws_instance", "id": "N/A"},
        passed=False,
        message="SKIPPED: No matching resources found for this rule",
        assertion_results=[],
    )


class TestJSONFormatter:
    def test_output_is_valid_json(self):
        results = [_make_result(True), _make_result(False)]
        output = JSONFormatter().format(results)
        data = json.loads(output)
        assert "results" in data
        assert "summary" in data
        assert "timestamp" in data

    def test_summary_counts(self):
        results = [_make_result(True), _make_result(False), _make_skipped()]
        data = json.loads(JSONFormatter().format(results))
        assert data["summary"]["passed"] == 1
        assert data["summary"]["failed"] == 1
        assert data["summary"]["skipped"] == 1

    def test_empty_results(self):
        data = json.loads(JSONFormatter().format([]))
        assert data["summary"]["total"] == 0


class TestJUnitXMLFormatter:
    def test_output_is_valid_xml(self):
        results = [_make_result(True), _make_result(False, rule_id="failing-rule")]
        output = JUnitXMLFormatter().format(results)
        root = ET.fromstring(output)
        assert root.tag == "testsuite"

    def test_failure_element_present(self):
        results = [_make_result(False, rule_id="bad-rule")]
        output = JUnitXMLFormatter().format(results)
        root = ET.fromstring(output)
        failures = root.findall(".//failure")
        assert len(failures) == 1

    def test_skipped_not_in_output(self):
        results = [_make_skipped()]
        output = JUnitXMLFormatter().format(results)
        root = ET.fromstring(output)
        testcases = root.findall("testcase")
        assert len(testcases) == 0

    def test_passed_has_no_failure_element(self):
        results = [_make_result(True)]
        output = JUnitXMLFormatter().format(results)
        root = ET.fromstring(output)
        failures = root.findall(".//failure")
        assert len(failures) == 0


class TestSARIFFormatter:
    def test_output_is_valid_sarif(self):
        results = [_make_result(False, rule_id="s3-public")]
        data = json.loads(SARIFFormatter().format(results))
        assert data["version"] == "2.1.0"
        assert len(data["runs"]) == 1

    def test_passed_not_in_results(self):
        results = [_make_result(True)]
        data = json.loads(SARIFFormatter().format(results))
        sarif_results = data["runs"][0]["results"]
        assert len(sarif_results) == 0

    def test_failed_in_results(self):
        results = [_make_result(False, rule_id="fail-rule")]
        data = json.loads(SARIFFormatter().format(results))
        sarif_results = data["runs"][0]["results"]
        assert len(sarif_results) == 1
        assert sarif_results[0]["ruleId"] == "fail-rule"

    def test_severity_mapping(self):
        error_result = _make_result(False, rule_id="err", severity="error")
        warning_result = _make_result(False, rule_id="warn", severity="warning")
        info_result = _make_result(False, rule_id="info", severity="info")
        data = json.loads(SARIFFormatter().format([error_result, warning_result, info_result]))
        sarif_results = {r["ruleId"]: r["level"] for r in data["runs"][0]["results"]}
        assert sarif_results["err"] == "error"
        assert sarif_results["warn"] == "warning"
        assert sarif_results["info"] == "note"

    def test_skipped_excluded(self):
        results = [_make_skipped()]
        data = json.loads(SARIFFormatter().format(results))
        assert data["runs"][0]["results"] == []


class TestHTMLFormatter:
    def test_output_is_valid_html(self):
        results = [_make_result(True), _make_result(False)]
        output = HTMLFormatter().format(results)
        assert "<!DOCTYPE html>" in output
        assert "<html" in output
        assert "</html>" in output

    def test_summary_counts_in_output(self):
        results = [_make_result(True), _make_result(False), _make_skipped()]
        output = HTMLFormatter().format(results)
        # Summary card placeholders are replaced with real counts
        assert ">3<" in output  # total
        assert ">1<" in output  # passed (also failed and skipped each appear once)

    def test_failed_result_present(self):
        results = [_make_result(False, rule_id="ec2-no-public-ip")]
        output = HTMLFormatter().format(results)
        assert "ec2-no-public-ip" in output

    def test_passed_result_present(self):
        results = [_make_result(True, rule_id="s3-encrypted")]
        output = HTMLFormatter().format(results)
        assert "s3-encrypted" in output

    def test_resource_id_in_output(self):
        results = [_make_result(False)]
        output = HTMLFormatter().format(results)
        assert "my_resource" in output

    def test_rule_ids_present(self):
        results = [
            _make_result(False, rule_id="e", severity="error"),
            _make_result(False, rule_id="w", severity="warning"),
            _make_result(False, rule_id="i", severity="info"),
        ]
        output = HTMLFormatter().format(results)
        assert '"e"' in output
        assert '"w"' in output
        assert '"i"' in output

    def test_skipped_count_correct(self):
        results = [_make_skipped(), _make_skipped("skipped-2")]
        output = HTMLFormatter().format(results)
        # 0 failed, 2 skipped total — zero failure counts should appear
        assert ">0<" in output

    def test_empty_results_valid_html(self):
        output = HTMLFormatter().format([])
        assert "<!DOCTYPE html>" in output
        assert ">0<" in output

    def test_version_in_output(self):
        output = HTMLFormatter().format([])
        from riveter._version import __version__

        assert __version__ in output

    def test_data_json_embedded(self):
        results = [_make_result(False, rule_id="my-rule")]
        output = HTMLFormatter().format(results)
        # The JS data constant should contain the rule id
        assert '"my-rule"' in output

    def test_js_and_css_present(self):
        output = HTMLFormatter().format([])
        assert "<style>" in output
        assert "<script>" in output
        assert "applyFilters" in output
