"""Integration tests for the ``riveter scan``, ``riveter list-rule-packs``,
``riveter explain``, and ``riveter generate-rules`` CLI commands.

Uses Click's ``CliRunner`` so tests exercise the full command pipeline
without spawning a subprocess.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from riveter.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rules(path: Path, rules_yaml: str) -> Path:
    rules_file = path / "rules.yml"
    rules_file.write_text(rules_yaml, encoding="utf-8")
    return rules_file


def _extract_json(output: str) -> dict:
    """Find and parse the JSON payload from CLI output (skipping Rich preamble)."""
    json_start = output.find("{")
    assert json_start >= 0, f"No JSON found in output: {output!r}"
    return json.loads(output[json_start:])


# Pre-built resource dicts (bypassing HCL parser quote issues in test environments)
_PASSING_RESOURCE = {"id": "web", "resource_type": "aws_instance", "instance_type": "t3.large"}
_FAILING_RESOURCE = {"id": "web", "resource_type": "aws_instance", "instance_type": "t2.micro"}
_S3_RESOURCE = {"id": "data", "resource_type": "aws_s3_bucket", "bucket": "my-company-data"}


def _write_tf(path: Path, content: str, filename: str = "main.tf") -> Path:
    tf_file = path / filename
    tf_file.write_text(content, encoding="utf-8")
    return tf_file


_INSTANCE_TF = """\
resource "aws_instance" "web" {
  instance_type = "t3.large"
  ami           = "ami-12345678"
}
"""

_WRONG_TYPE_TF = """\
resource "aws_instance" "web" {
  instance_type = "t2.micro"
  ami           = "ami-12345678"
}
"""

_MULTI_RESOURCE_TF = """\
resource "aws_instance" "web" {
  instance_type = "t3.large"
  ami           = "ami-12345678"
}

resource "aws_s3_bucket" "data" {
  bucket = "my-company-data"
}
"""

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
    description: Instance type must be m5.xlarge
    assert:
      instance_type: m5.xlarge
"""

_MULTI_RULES = """\
rules:
  - id: check-instance-type
    resource_type: aws_instance
    description: Instance type must be t3.large
    assert:
      instance_type: t3.large
  - id: check-bucket-present
    resource_type: aws_s3_bucket
    description: Bucket name must be present
    assert:
      bucket: present
"""


# ---------------------------------------------------------------------------
# scan — Basic pass / fail
# ---------------------------------------------------------------------------


class TestScanBasic:
    def test_passing_check_exits_zero(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf)])
        assert result.exit_code == 0, result.output

    def test_failing_check_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _WRONG_TYPE_TF)
        rules = _write_rules(tmp_path, _FAILING_RULES)
        runner = CliRunner()
        # Mock extraction to avoid HCL parser quote issues in test environments
        with patch("riveter.cli.extract_terraform_config") as mock_extract:
            mock_extract.return_value = {"resources": [_FAILING_RESOURCE]}
            result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf)])
        assert result.exit_code == 1

    def test_no_rule_source_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-t", str(tf)])
        assert result.exit_code != 0

    def test_multiple_resources_with_multiple_rules(self, tmp_path):
        tf = _write_tf(tmp_path, _MULTI_RESOURCE_TF)
        rules = _write_rules(tmp_path, _MULTI_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# scan — terraform path: single file vs directory
# ---------------------------------------------------------------------------


class TestScanTerraformPath:
    def test_single_tf_file(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf)])
        assert result.exit_code == 0

    def test_directory_of_tf_files(self, tmp_path):
        tf_dir = tmp_path / "infra"
        tf_dir.mkdir()
        _write_tf(tf_dir, _INSTANCE_TF, "a.tf")
        _write_tf(tf_dir, _INSTANCE_TF, "b.tf")
        rules_path = tmp_path / "rules.yml"
        rules_path.write_text(_PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules_path), "-t", str(tf_dir)])
        assert result.exit_code == 0

    def test_empty_directory_exits_zero(self, tmp_path):
        tf_dir = tmp_path / "infra"
        tf_dir.mkdir()
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf_dir)])
        # No resources found → warning and exit 0
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# scan — output formats
# ---------------------------------------------------------------------------


class TestScanOutputFormats:
    def test_json_output_is_valid_json(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        with patch("riveter.cli.extract_terraform_config") as mock_extract:
            mock_extract.return_value = {"resources": [_PASSING_RESOURCE]}
            result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf), "-f", "json"])
        assert result.exit_code == 0, result.output
        # Rich status messages precede the JSON payload — find the first "{"
        data = _extract_json(result.output)
        assert "results" in data

    def test_junit_output_contains_xml(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf), "-f", "junit"])
        assert result.exit_code == 0
        assert "<?xml" in result.output or "<testsuites" in result.output

    def test_sarif_output_contains_schema(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        with patch("riveter.cli.extract_terraform_config") as mock_extract:
            mock_extract.return_value = {"resources": [_PASSING_RESOURCE]}
            result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf), "-f", "sarif"])
        assert result.exit_code == 0
        data = _extract_json(result.output)
        assert data.get("version") == "2.1.0"

    def test_html_output_contains_html_tag(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf), "-f", "html"])
        assert result.exit_code == 0
        assert "<html" in result.output.lower()

    def test_output_file_written(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        out_file = tmp_path / "report.json"
        runner = CliRunner()
        with patch("riveter.cli.extract_terraform_config") as mock_extract:
            mock_extract.return_value = {"resources": [_PASSING_RESOURCE]}
            result = runner.invoke(
                main,
                ["scan", "-r", str(rules), "-t", str(tf), "-f", "json", "-o", str(out_file)],
            )
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "results" in data


# ---------------------------------------------------------------------------
# scan — rule-pack flag
# ---------------------------------------------------------------------------


class TestScanRulePack:
    def test_builtin_rule_pack_loads(self, tmp_path):
        # Use a minimal TF that matches something in aws-security
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-p", "aws-security", "-t", str(tf)])
        # May pass or fail depending on rules; just check it ran and loaded
        assert result.exit_code in (0, 1)

    def test_unknown_rule_pack_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-p", "nonexistent-pack", "-t", str(tf)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# scan — include/exclude rule filtering
# ---------------------------------------------------------------------------


class TestScanRuleFiltering:
    def test_include_rules_filters(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules_yaml = """\
rules:
  - id: check-instance-type
    resource_type: aws_instance
    description: Instance type must be t3.large
    assert:
      instance_type: t3.large
  - id: other-rule
    resource_type: aws_instance
    description: AMI check (will fail)
    assert:
      ami: ami-999999
"""
        rules = _write_rules(tmp_path, rules_yaml)
        runner = CliRunner()
        # Only include the passing rule → should exit 0
        result = runner.invoke(
            main,
            ["scan", "-r", str(rules), "-t", str(tf), "--include-rules", "check-*"],
        )
        assert result.exit_code == 0

    def test_exclude_rules_filters(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules_yaml = """\
rules:
  - id: check-instance-type
    resource_type: aws_instance
    description: Instance type must be t3.large
    assert:
      instance_type: t3.large
  - id: failing-rule
    resource_type: aws_instance
    description: Will always fail
    assert:
      ami: ami-999999
"""
        rules = _write_rules(tmp_path, rules_yaml)
        runner = CliRunner()
        # Exclude the failing rule → should exit 0
        result = runner.invoke(
            main,
            ["scan", "-r", str(rules), "-t", str(tf), "--exclude-rules", "failing-*"],
        )
        assert result.exit_code == 0

    def test_all_rules_excluded_exits_zero(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan", "-r", str(rules), "-t", str(tf), "--exclude-rules", "*"],
        )
        # No rules remain → warning + exit 0
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# scan — config file
# ---------------------------------------------------------------------------


class TestScanConfigFile:
    def test_config_file_sets_output_format(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        config_file = tmp_path / "riveter.yml"
        config_file.write_text("output_format: json\n")
        runner = CliRunner()
        with patch("riveter.cli.extract_terraform_config") as mock_extract:
            mock_extract.return_value = {"resources": [_PASSING_RESOURCE]}
            result = runner.invoke(
                main,
                ["scan", "-r", str(rules), "-t", str(tf), "-c", str(config_file)],
            )
        assert result.exit_code == 0
        data = _extract_json(result.output)
        assert "results" in data


# ---------------------------------------------------------------------------
# scan — error scenarios
# ---------------------------------------------------------------------------


class TestScanErrors:
    def test_invalid_hcl_exits_one(self, tmp_path):
        tf = tmp_path / "bad.tf"
        tf.write_text("this is { invalid hcl !!!\n")
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", str(tf)])
        assert result.exit_code == 1

    def test_invalid_rules_file_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        bad_rules = tmp_path / "rules.yml"
        bad_rules.write_text("[\ninvalid yaml")
        runner = CliRunner()
        result = runner.invoke(main, ["scan", "-r", str(bad_rules), "-t", str(tf)])
        assert result.exit_code == 1

    def test_missing_terraform_path_exits_nonzero(self, tmp_path):
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        # Click validates --terraform path exists, so missing path → error
        result = runner.invoke(main, ["scan", "-r", str(rules), "-t", "/nonexistent/path/main.tf"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# list-rule-packs
# ---------------------------------------------------------------------------


class TestListRulePacks:
    def test_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list-rule-packs"])
        assert result.exit_code == 0

    def test_shows_builtin_packs(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list-rule-packs"])
        assert result.exit_code == 0
        # At least one known built-in pack should appear in the output
        assert "aws-security" in result.output

    def test_shows_multiple_packs(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list-rule-packs"])
        assert result.exit_code == 0
        # Should show several packs
        for pack in ("azure-security", "gcp-security", "kubernetes-security"):
            assert pack in result.output


# ---------------------------------------------------------------------------
# explain
# ---------------------------------------------------------------------------


class TestExplainCommand:
    def test_no_rule_source_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "explain",
                "check-instance-type",
                "--resource",
                "aws_instance.web",
                "--terraform",
                str(tf),
            ],
        )
        assert result.exit_code == 1

    def test_rule_not_found_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "explain",
                "nonexistent-rule-id",
                "--resource",
                "aws_instance.web",
                "--terraform",
                str(tf),
                "--rules",
                str(rules),
            ],
        )
        assert result.exit_code == 1

    def test_resource_not_found_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "explain",
                "check-instance-type",
                "--resource",
                "aws_instance.nonexistent",
                "--terraform",
                str(tf),
                "--rules",
                str(rules),
            ],
        )
        assert result.exit_code == 1

    def test_no_api_key_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        runner = CliRunner()
        with patch.dict("os.environ", {}, clear=True):
            # Remove any API key from environment
            import os

            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            with patch.dict("os.environ", env, clear=True):
                result = runner.invoke(
                    main,
                    [
                        "explain",
                        "check-instance-type",
                        "--resource",
                        "aws_instance.web",
                        "--terraform",
                        str(tf),
                        "--rules",
                        str(rules),
                    ],
                )
        # Without API key, should exit 1
        assert result.exit_code == 1

    def test_with_mocked_explainer_prints_explanation(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        rules = _write_rules(tmp_path, _PASSING_RULES)
        mock_explainer = MagicMock()
        mock_explainer.is_available.return_value = True
        mock_explainer.explain.return_value = "This rule ensures instance type is t3.large."
        mock_explainer.get_scan_warning.return_value = None

        runner = CliRunner()
        # Also mock extraction so resource lookup succeeds regardless of HCL parser version
        with (
            patch("riveter.cli.Explainer", return_value=mock_explainer),
            patch("riveter.cli.extract_terraform_config") as mock_extract,
        ):
            mock_extract.return_value = {"resources": [_PASSING_RESOURCE]}
            result = runner.invoke(
                main,
                [
                    "explain",
                    "check-instance-type",
                    "--resource",
                    "aws_instance.web",
                    "--terraform",
                    str(tf),
                    "--rules",
                    str(rules),
                ],
            )
        assert result.exit_code == 0
        assert "t3.large" in result.output

    def test_unknown_rule_pack_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "explain",
                "some-rule",
                "--resource",
                "aws_instance.web",
                "--terraform",
                str(tf),
                "--rule-pack",
                "nonexistent-pack",
            ],
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# generate-rules
# ---------------------------------------------------------------------------


class TestGenerateRulesCommand:
    def test_no_api_key_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        runner = CliRunner()
        import os

        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            result = runner.invoke(main, ["generate-rules", "-t", str(tf)])
        assert result.exit_code == 1

    def test_empty_terraform_exits_zero(self, tmp_path):
        # No resources → warning + exit 0
        tf = tmp_path / "empty.tf"
        tf.write_text('terraform { required_version = ">= 1.0" }\n')
        runner = CliRunner()
        result = runner.invoke(main, ["generate-rules", "-t", str(tf)])
        assert result.exit_code == 0

    def test_with_mocked_generator_stdout(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        mock_gen = MagicMock()
        mock_gen.is_available.return_value = True
        mock_gen.generate_for_resource_type.return_value = [
            {
                "id": "generated-rule",
                "resource_type": "aws_instance",
                "description": "Generated rule",
                "assert": {"instance_type": "t3.large"},
            }
        ]
        mock_gen.get_warning.return_value = None

        runner = CliRunner()
        with patch("riveter.cli.RuleGenerator", return_value=mock_gen):
            result = runner.invoke(main, ["generate-rules", "-t", str(tf)])
        assert result.exit_code == 0
        assert "generated-rule" in result.output

    def test_with_mocked_generator_output_file(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        out_file = tmp_path / "generated.yml"
        mock_gen = MagicMock()
        mock_gen.is_available.return_value = True
        mock_gen.generate_for_resource_type.return_value = [
            {
                "id": "generated-rule",
                "resource_type": "aws_instance",
                "description": "Generated rule",
                "assert": {"instance_type": "t3.large"},
            }
        ]
        mock_gen.get_warning.return_value = None

        runner = CliRunner()
        with patch("riveter.cli.RuleGenerator", return_value=mock_gen):
            result = runner.invoke(main, ["generate-rules", "-t", str(tf), "-o", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "generated-rule" in content

    def test_with_mocked_generator_no_rules_exits_one(self, tmp_path):
        tf = _write_tf(tmp_path, _INSTANCE_TF)
        mock_gen = MagicMock()
        mock_gen.is_available.return_value = True
        mock_gen.generate_for_resource_type.return_value = []
        mock_gen.get_warning.return_value = None

        runner = CliRunner()
        with patch("riveter.cli.RuleGenerator", return_value=mock_gen):
            result = runner.invoke(main, ["generate-rules", "-t", str(tf)])
        assert result.exit_code == 1

    def test_invalid_terraform_path_exits_nonzero(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["generate-rules", "-t", "/nonexistent/path/main.tf"])
        assert result.exit_code != 0
