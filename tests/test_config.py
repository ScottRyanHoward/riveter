"""Tests for configuration loading and merging."""

import json
from pathlib import Path

import pytest
import yaml

from riveter.config import ConfigManager, RiveterConfig
from riveter.exceptions import ConfigurationError


class TestRiveterConfig:
    def test_defaults(self):
        cfg = RiveterConfig()
        assert cfg.min_severity == "info"
        assert cfg.output_format == "table"
        assert cfg.rule_dirs == []
        assert cfg.rule_packs == []
        assert cfg.debug is False
        assert cfg.output_file is None

    def test_to_dict_roundtrip(self):
        cfg = RiveterConfig(min_severity="warning", debug=True, rule_packs=["aws-security"])
        d = cfg.to_dict()
        assert d["min_severity"] == "warning"
        assert d["debug"] is True
        assert d["rule_packs"] == ["aws-security"]

    def test_from_dict_ignores_unknown_keys(self):
        cfg = RiveterConfig.from_dict({"min_severity": "error", "unknown_key": "ignored"})
        assert cfg.min_severity == "error"

    def test_from_dict_skips_none(self):
        cfg = RiveterConfig.from_dict({"min_severity": None, "debug": True})
        assert cfg.min_severity == "info"  # default preserved
        assert cfg.debug is True

    def test_merge_scalar_override_wins(self):
        base = RiveterConfig(min_severity="info")
        override = RiveterConfig(min_severity="error")
        merged = base._merge_with_overrides(override)
        assert merged.min_severity == "error"

    def test_merge_scalar_default_unchanged(self):
        base = RiveterConfig(min_severity="warning")
        override = RiveterConfig()  # override has default "info"
        merged = base._merge_with_overrides(override)
        assert merged.min_severity == "warning"

    def test_merge_lists_combined_no_dupes(self):
        base = RiveterConfig(rule_packs=["aws-security"])
        override = RiveterConfig(rule_packs=["aws-security", "cis-aws"])
        merged = base._merge_with_overrides(override)
        assert merged.rule_packs == ["aws-security", "cis-aws"]

    def test_merge_output_file(self):
        base = RiveterConfig()
        override = RiveterConfig(output_file="out.json")
        merged = base._merge_with_overrides(override)
        assert merged.output_file == "out.json"

    def test_merge_debug_or(self):
        base = RiveterConfig(debug=True)
        override = RiveterConfig(debug=False)
        merged = base._merge_with_overrides(override)
        assert merged.debug is True


class TestConfigManager:
    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mgr = ConfigManager()
        cfg = mgr.load_config()
        assert cfg.min_severity == "info"
        assert cfg.output_format == "table"

    def test_loads_yaml_file(self, tmp_path):
        cfg_file = tmp_path / "riveter.yml"
        cfg_file.write_text("min_severity: warning\noutput_format: json\n")
        mgr = ConfigManager()
        cfg = mgr.load_config(config_file=str(cfg_file))
        assert cfg.min_severity == "warning"
        assert cfg.output_format == "json"

    def test_loads_json_file(self, tmp_path):
        cfg_file = tmp_path / "riveter.json"
        cfg_file.write_text(json.dumps({"min_severity": "error", "debug": True}))
        mgr = ConfigManager()
        cfg = mgr.load_config(config_file=str(cfg_file))
        assert cfg.min_severity == "error"
        assert cfg.debug is True

    def test_auto_discovery(self, tmp_path, monkeypatch):
        (tmp_path / "riveter.yml").write_text("min_severity: error\n")
        monkeypatch.chdir(tmp_path)
        mgr = ConfigManager()
        cfg = mgr.load_config()
        assert cfg.min_severity == "error"

    def test_cli_overrides_file(self, tmp_path):
        cfg_file = tmp_path / "riveter.yml"
        cfg_file.write_text("min_severity: warning\n")
        mgr = ConfigManager()
        cfg = mgr.load_config(config_file=str(cfg_file), cli_overrides={"min_severity": "error"})
        assert cfg.min_severity == "error"

    def test_missing_explicit_file_raises(self):
        mgr = ConfigManager()
        with pytest.raises(ConfigurationError, match="not found"):
            mgr.load_config(config_file="/nonexistent/path/riveter.yml")

    def test_invalid_yaml_raises(self, tmp_path):
        cfg_file = tmp_path / "riveter.yml"
        cfg_file.write_text("[invalid yaml\n")
        mgr = ConfigManager()
        with pytest.raises(ConfigurationError):
            mgr.load_config(config_file=str(cfg_file))

    def test_non_dict_yaml_raises(self, tmp_path):
        cfg_file = tmp_path / "riveter.yml"
        cfg_file.write_text("- just\n- a\n- list\n")
        mgr = ConfigManager()
        with pytest.raises(ConfigurationError, match="object"):
            mgr.load_config(config_file=str(cfg_file))

    def test_validate_valid(self):
        mgr = ConfigManager()
        errors = mgr.validate(RiveterConfig(min_severity="warning", output_format="json"))
        assert errors == []

    def test_validate_invalid_severity(self):
        mgr = ConfigManager()
        errors = mgr.validate(RiveterConfig(min_severity="critical"))
        assert any("min_severity" in e for e in errors)

    def test_validate_invalid_format(self):
        mgr = ConfigManager()
        errors = mgr.validate(RiveterConfig(output_format="csv"))
        assert any("output_format" in e for e in errors)
