"""Integration tests for the ``riveter scan-state`` CLI command.

Uses Click's ``CliRunner`` so tests exercise the full command pipeline
(config loading, rule loading, state parsing, scanning, output formatting)
without spawning a subprocess.
"""

import json
from pathlib import Path
from typing import Any, Dict

from click.testing import CliRunner

from riveter.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rules(path: Path, rules_yaml: str) -> Path:
    rules_file = path / "rules.yml"
    rules_file.write_text(rules_yaml, encoding="utf-8")
    return rules_file


def _write_state(path: Path, payload: Dict[str, Any]) -> Path:
    state_file = path / "terraform.tfstate"
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    return state_file


def _minimal_state(*resources: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": 4,
        "terraform_version": "1.5.0",
        "serial": 1,
        "lineage": "abc-123",
        "outputs": {},
        "resources": list(resources),
    }


def _managed(
    resource_type: str,
    name: str,
    attributes: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "mode": "managed",
        "type": resource_type,
        "name": name,
        "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
        "instances": [{"schema_version": 0, "attributes": attributes or {}}],
    }


_PASSING_RULES = """\
rules:
  - id: check-instance-type
    resource_type: aws_instance
    description: Instance type must be t3.large
    assert:
      instance_type: t3.large
"""

_FAILING_RULES = """\
rules:
  - id: check-instance-type
    resource_type: aws_instance
    description: Instance type must be t3.large
    assert:
      instance_type: t3.large
"""


# ---------------------------------------------------------------------------
# Basic pass / fail
# ---------------------------------------------------------------------------


class TestBasicPassFail:
    def test_all_pass_exits_0(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(
            tmp_path,
            _minimal_state(_managed("aws_instance", "web", {"instance_type": "t3.large"})),
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file)],
        )
        assert result.exit_code == 0, result.output

    def test_failure_exits_1(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _FAILING_RULES)
        state_file = _write_state(
            tmp_path,
            _minimal_state(
                _managed("aws_instance", "web", {"instance_type": "t3.micro"})  # wrong type
            ),
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file)],
        )
        assert result.exit_code == 1

    def test_output_contains_resource_id(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(
            tmp_path,
            _minimal_state(_managed("aws_instance", "my_server", {"instance_type": "t3.large"})),
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file)],
        )
        assert "aws_instance.my_server" in result.output

    def test_scan_state_does_not_match_wrong_resource_type(self, tmp_path: Path) -> None:
        """Rules for aws_instance should SKIP when state has only s3 buckets."""
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(
            tmp_path,
            _minimal_state(_managed("aws_s3_bucket", "my_bucket", {"bucket": "test"})),
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file)],
        )
        assert result.exit_code == 0  # skipped rules → no failures
        assert "SKIP" in result.output


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


class TestOutputFormats:
    def test_json_output_is_valid(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(
            tmp_path,
            _minimal_state(_managed("aws_instance", "web", {"instance_type": "t3.large"})),
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file), "-f", "json"],
        )
        assert result.exit_code == 0, result.output
        # result.output may include Rich console status messages before the JSON object.
        # Find the JSON payload by locating the first '{'.
        json_start = result.output.find("{")
        assert json_start >= 0, f"No JSON found in output: {result.output!r}"
        data = json.loads(result.output[json_start:])
        assert "summary" in data
        assert "results" in data
        assert data["summary"]["total"] >= 1

    def test_junit_output_contains_xml(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(
            tmp_path,
            _minimal_state(_managed("aws_instance", "web", {"instance_type": "t3.large"})),
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file), "-f", "junit"],
        )
        assert result.exit_code == 0
        assert "<?xml" in result.output
        assert "testsuite" in result.output

    def test_html_output_is_self_contained(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(
            tmp_path,
            _minimal_state(_managed("aws_instance", "web", {"instance_type": "t3.large"})),
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file), "-f", "html"],
        )
        assert result.exit_code == 0
        assert "<!DOCTYPE html>" in result.output
        assert "<html" in result.output
        assert "</html>" in result.output


# ---------------------------------------------------------------------------
# Stdin support
# ---------------------------------------------------------------------------


class TestStdinInput:
    def test_stdin_with_dash(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_payload = json.dumps(
            _minimal_state(_managed("aws_instance", "web", {"instance_type": "t3.large"}))
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", "-"],
            input=state_payload,
        )
        assert result.exit_code == 0, result.output
        assert "aws_instance.web" in result.output

    def test_stdin_failure_exits_1(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _FAILING_RULES)
        state_payload = json.dumps(
            _minimal_state(_managed("aws_instance", "web", {"instance_type": "t3.micro"}))
        )
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", "-"],
            input=state_payload,
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_no_rule_source_exits_1(self, tmp_path: Path) -> None:
        state_file = _write_state(tmp_path, _minimal_state())
        runner = CliRunner()
        result = runner.invoke(main, ["scan-state", "-s", str(state_file)])
        assert result.exit_code == 1
        assert "rule source" in result.output.lower() or "rule" in result.output.lower()

    def test_file_not_found_exits_1(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(tmp_path / "nonexistent.tfstate")],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_invalid_json_state_exits_1(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        bad_state = tmp_path / "bad.tfstate"
        bad_state.write_text("{ not valid json }", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(bad_state)],
        )
        assert result.exit_code == 1

    def test_unsupported_state_version_exits_1(self, tmp_path: Path) -> None:
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(tmp_path, {"version": 3, "resources": []})
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file)],
        )
        assert result.exit_code == 1

    def test_empty_state_no_resources_exits_0(self, tmp_path: Path) -> None:
        """Empty state (no resources) → warning + exit 0, not an error."""
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        state_file = _write_state(tmp_path, _minimal_state())
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file)],
        )
        assert result.exit_code == 0

    def test_data_sources_only_exits_0(self, tmp_path: Path) -> None:
        """State with only data sources → no managed resources → warning + exit 0."""
        rules_file = _write_rules(tmp_path, _PASSING_RULES)
        data_source = {
            "mode": "data",
            "type": "aws_instance",
            "name": "lookup",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [{"schema_version": 0, "attributes": {"instance_type": "t3.micro"}}],
        }
        state_file = _write_state(tmp_path, _minimal_state(data_source))
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan-state", "-r", str(rules_file), "-s", str(state_file)],
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Filtering options
# ---------------------------------------------------------------------------


class TestFilteringOptions:
    def test_include_rules_pattern(self, tmp_path: Path) -> None:
        rules_yaml = """\
rules:
  - id: check-instance-type
    resource_type: aws_instance
    description: Instance type check
    assert:
      instance_type: t3.large
  - id: check-public-ip
    resource_type: aws_instance
    description: No public IP
    assert:
      associate_public_ip_address: false
"""
        rules_file = _write_rules(tmp_path, rules_yaml)
        state_file = _write_state(
            tmp_path,
            _minimal_state(
                _managed(
                    "aws_instance",
                    "web",
                    {"instance_type": "t3.large", "associate_public_ip_address": True},
                )
            ),
        )
        runner = CliRunner()
        # Only include the instance-type rule (which passes)
        result = runner.invoke(
            main,
            [
                "scan-state",
                "-r",
                str(rules_file),
                "-s",
                str(state_file),
                "--include-rules",
                "*instance*",
            ],
        )
        assert result.exit_code == 0, result.output
