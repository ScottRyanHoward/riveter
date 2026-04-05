"""Tests for configuration loading and merging."""

import json

import pytest

from riveter.config import ConfigManager, RiveterConfig
from riveter.exceptions import ConfigurationError


class TestRiveterConfig:
    def test_defaults(self):
        cfg = RiveterConfig()
        assert cfg.output_format == "table"
        assert cfg.rule_dirs == []
        assert cfg.rule_packs == []
        assert cfg.debug is False
        assert cfg.output_file is None

    def test_to_dict_roundtrip(self):
        cfg = RiveterConfig(debug=True, rule_packs=["aws-security"])
        d = cfg.to_dict()
        assert d["debug"] is True
        assert d["rule_packs"] == ["aws-security"]

    def test_from_dict_ignores_unknown_keys(self):
        cfg = RiveterConfig.from_dict({"output_format": "json", "unknown_key": "ignored"})
        assert cfg.output_format == "json"

    def test_from_dict_skips_none(self):
        cfg = RiveterConfig.from_dict({"output_format": None, "debug": True})
        assert cfg.output_format == "table"  # default preserved
        assert cfg.debug is True

    def test_merge_scalar_override_wins(self):
        base = RiveterConfig(output_format="table")
        override = RiveterConfig(output_format="json")
        merged = base._merge_with_overrides(override)
        assert merged.output_format == "json"

    def test_merge_scalar_default_unchanged(self):
        base = RiveterConfig(output_format="json")
        override = RiveterConfig()  # override has default "table"
        merged = base._merge_with_overrides(override)
        assert merged.output_format == "json"

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
        assert cfg.output_format == "table"

    def test_loads_yaml_file(self, tmp_path):
        cfg_file = tmp_path / "riveter.yml"
        cfg_file.write_text("output_format: json\n")
        mgr = ConfigManager()
        cfg = mgr.load_config(config_file=str(cfg_file))
        assert cfg.output_format == "json"

    def test_loads_json_file(self, tmp_path):
        cfg_file = tmp_path / "riveter.json"
        cfg_file.write_text(json.dumps({"output_format": "sarif", "debug": True}))
        mgr = ConfigManager()
        cfg = mgr.load_config(config_file=str(cfg_file))
        assert cfg.output_format == "sarif"
        assert cfg.debug is True

    def test_auto_discovery(self, tmp_path, monkeypatch):
        (tmp_path / "riveter.yml").write_text("output_format: json\n")
        monkeypatch.chdir(tmp_path)
        mgr = ConfigManager()
        cfg = mgr.load_config()
        assert cfg.output_format == "json"

    def test_cli_overrides_file(self, tmp_path):
        cfg_file = tmp_path / "riveter.yml"
        cfg_file.write_text("output_format: json\n")
        mgr = ConfigManager()
        cfg = mgr.load_config(config_file=str(cfg_file), cli_overrides={"output_format": "sarif"})
        assert cfg.output_format == "sarif"

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
        errors = mgr.validate(RiveterConfig(output_format="json"))
        assert errors == []

    def test_validate_invalid_format(self):
        mgr = ConfigManager()
        errors = mgr.validate(RiveterConfig(output_format="csv"))
        assert any("output_format" in e for e in errors)
