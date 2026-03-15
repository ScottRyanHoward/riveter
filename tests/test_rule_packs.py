"""Tests for rule pack loading and management."""

import textwrap
from pathlib import Path

import pytest

from riveter.exceptions import RulePackError
from riveter.rule_packs import RulePack, RulePackManager, RulePackMetadata
from riveter.rules import Rule, Severity


def _write_pack(directory: Path, name: str, rules_yaml: str = "") -> Path:
    """Write a minimal valid rule pack to a temp directory."""
    if not rules_yaml:
        rules_yaml = (
            "- id: test-rule\n"
            "  resource_type: aws_instance\n"
            "  description: A test rule\n"
            "  severity: error\n"
            "  assert:\n"
            "    instance_type: t3.large\n"
        )
    indented_rules = "\n".join(f"  {line}" for line in rules_yaml.rstrip().splitlines())
    content = (
        f"metadata:\n"
        f"  name: {name}\n"
        f"  version: 1.0.0\n"
        f"  description: Test pack {name}\n"
        f"  author: Test Author\n"
        f"  created: 2024-01-01\n"
        f"  updated: 2024-01-01\n"
        f"  tags: [test]\n"
        f"  min_riveter_version: 0.1.0\n"
        f"\n"
        f"rules:\n"
        f"{indented_rules}\n"
    )
    pack_file = directory / f"{name}.yml"
    pack_file.write_text(content)
    return pack_file


class TestRulePackManager:
    def test_load_by_name(self, tmp_path):
        _write_pack(tmp_path, "my-pack")
        mgr = RulePackManager(extra_dirs=[str(tmp_path)])
        pack = mgr.load_rule_pack("my-pack")
        assert pack.metadata.name == "my-pack"
        assert len(pack.rules) == 1

    def test_load_not_found_raises(self, tmp_path):
        mgr = RulePackManager(extra_dirs=[str(tmp_path)])
        with pytest.raises(FileNotFoundError, match="not found"):
            mgr.load_rule_pack("nonexistent-pack")

    def test_load_from_file(self, tmp_path):
        f = _write_pack(tmp_path, "direct-pack")
        mgr = RulePackManager()
        pack = mgr.load_rule_pack_from_file(str(f))
        assert pack.metadata.name == "direct-pack"

    def test_list_available_packs(self, tmp_path):
        _write_pack(tmp_path, "pack-a")
        _write_pack(tmp_path, "pack-b")
        mgr = RulePackManager(extra_dirs=[str(tmp_path)])
        packs = mgr.list_available_packs()
        names = [p["name"] for p in packs]
        assert "pack-a" in names
        assert "pack-b" in names

    def test_invalid_yaml_raises(self, tmp_path):
        bad_file = tmp_path / "bad.yml"
        bad_file.write_text("[\ninvalid yaml")
        mgr = RulePackManager()
        with pytest.raises(RulePackError):
            mgr.load_rule_pack_from_file(str(bad_file))

    def test_missing_metadata_raises(self, tmp_path):
        f = tmp_path / "no-meta.yml"
        f.write_text("rules:\n  - id: x\n    resource_type: y\n    assert: {z: 1}\n")
        mgr = RulePackManager()
        with pytest.raises(RulePackError, match="metadata"):
            mgr.load_rule_pack_from_file(str(f))

    def test_validate_valid_pack(self, tmp_path):
        f = _write_pack(tmp_path, "valid-pack")
        mgr = RulePackManager()
        report = mgr.validate_rule_pack(str(f))
        assert report["valid"] is True
        assert report["rule_count"] == 1
        assert report["errors"] == []

    def test_validate_invalid_pack(self, tmp_path):
        f = tmp_path / "invalid.yml"
        f.write_text("totally: wrong: structure\n")
        mgr = RulePackManager()
        report = mgr.validate_rule_pack(str(f))
        assert report["valid"] is False
        assert len(report["errors"]) > 0


class TestRulePackBuiltIns:
    """Smoke tests for the built-in rule packs shipped with riveter."""

    PACKS_TO_TEST = [
        "aws-security",
        "azure-security",
        "gcp-security",
        "kubernetes-security",
        "cis-aws",
    ]

    def test_built_in_packs_loadable(self):
        """All listed packs should load without errors."""
        mgr = RulePackManager()
        for pack_name in self.PACKS_TO_TEST:
            pack = mgr.load_rule_pack(pack_name)
            assert len(pack.rules) > 0, f"{pack_name} has no rules"

    def test_aws_security_has_expected_rules(self):
        mgr = RulePackManager()
        pack = mgr.load_rule_pack("aws-security")
        rule_ids = {r.id for r in pack.rules}
        assert "ec2_encrypted_ebs_volumes" in rule_ids

    def test_rule_severities_valid(self):
        mgr = RulePackManager()
        for pack_name in self.PACKS_TO_TEST:
            pack = mgr.load_rule_pack(pack_name)
            for rule in pack.rules:
                assert isinstance(rule.severity, Severity)


class TestRulePackDuplicate:
    def test_duplicate_ids_raise(self, tmp_path):
        rules_yaml = textwrap.dedent(
            """\
            - id: duplicate-id
              resource_type: aws_instance
              assert:
                x: y
            - id: duplicate-id
              resource_type: aws_instance
              assert:
                x: z
            """
        )
        f = _write_pack(tmp_path, "dup-pack", rules_yaml)
        mgr = RulePackManager()
        with pytest.raises(RulePackError, match="[Dd]uplicate"):
            mgr.load_rule_pack_from_file(str(f))


class TestRulePackFilter:
    def test_filter_by_severity(self, tmp_path):
        rules_yaml = textwrap.dedent(
            """\
            - id: error-rule
              resource_type: aws_instance
              severity: error
              assert:
                x: y
            - id: warning-rule
              resource_type: aws_instance
              severity: warning
              assert:
                x: y
            - id: info-rule
              resource_type: aws_instance
              severity: info
              assert:
                x: y
            """
        )
        f = _write_pack(tmp_path, "multi-sev", rules_yaml)
        mgr = RulePackManager()
        pack = mgr.load_rule_pack_from_file(str(f))

        errors_only = pack.filter_by_severity(Severity.ERROR)
        assert len(errors_only.rules) == 1
        assert errors_only.rules[0].id == "error-rule"

        warnings_up = pack.filter_by_severity(Severity.WARNING)
        assert len(warnings_up.rules) == 2
