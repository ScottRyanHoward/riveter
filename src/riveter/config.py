"""Configuration management for Riveter.

Priority order (highest to lowest):
    1. CLI flags
    2. Config file (riveter.yml / .riveter.yml / riveter.json in CWD, or --config path)
    3. Built-in defaults

Config file format (YAML example):

    rule_dirs:
      - ./my-custom-rules
    rule_packs:
      - aws-security
      - cis-aws
    min_severity: warning
    output_format: table
    include_rules:
      - "*encryption*"
    exclude_rules:
      - "*test*"
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from .exceptions import ConfigurationError

log = logging.getLogger(__name__)

_DEFAULT_CONFIG_FILES = [
    "riveter.yml",
    "riveter.yaml",
    ".riveter.yml",
    ".riveter.yaml",
    "riveter.json",
    ".riveter.json",
]

_VALID_SEVERITIES = ("info", "warning", "error")
_VALID_FORMATS = ("table", "json", "junit", "sarif")


@dataclass
class RiveterConfig:
    """All configuration options for a Riveter scan."""

    # Rule sources
    rule_dirs: List[str] = field(default_factory=list)
    rule_packs: List[str] = field(default_factory=list)

    # Filtering
    include_rules: List[str] = field(default_factory=list)
    exclude_rules: List[str] = field(default_factory=list)
    min_severity: str = "info"

    # Output
    output_format: str = "table"
    output_file: Optional[str] = None

    # Debugging
    debug: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_dirs": self.rule_dirs,
            "rule_packs": self.rule_packs,
            "include_rules": self.include_rules,
            "exclude_rules": self.exclude_rules,
            "min_severity": self.min_severity,
            "output_format": self.output_format,
            "output_file": self.output_file,
            "debug": self.debug,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiveterConfig":
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid and v is not None}
        return cls(**filtered)

    def _merge_with_overrides(self, overrides: "RiveterConfig") -> "RiveterConfig":
        """Return a new config with overrides applied (overrides win for scalars)."""
        merged = RiveterConfig()

        # Scalars: override wins only if it differs from default
        defaults = RiveterConfig()
        merged.min_severity = (
            overrides.min_severity
            if overrides.min_severity != defaults.min_severity
            else self.min_severity
        )
        merged.output_format = (
            overrides.output_format
            if overrides.output_format != defaults.output_format
            else self.output_format
        )
        merged.output_file = overrides.output_file or self.output_file
        merged.debug = overrides.debug or self.debug

        # Lists: extend base with override additions
        merged.rule_dirs = self.rule_dirs + [d for d in overrides.rule_dirs if d not in self.rule_dirs]
        merged.rule_packs = self.rule_packs + [p for p in overrides.rule_packs if p not in self.rule_packs]
        merged.include_rules = self.include_rules + [r for r in overrides.include_rules if r not in self.include_rules]
        merged.exclude_rules = self.exclude_rules + [r for r in overrides.exclude_rules if r not in self.exclude_rules]

        return merged


class ConfigManager:
    """Loads and validates Riveter configuration."""

    def load_config(
        self,
        config_file: Optional[str] = None,
        cli_overrides: Optional[Dict[str, Any]] = None,
    ) -> RiveterConfig:
        """Build a resolved config from file + CLI overrides.

        Args:
            config_file:   Explicit path to a config file, or None to auto-discover.
            cli_overrides: Dict of CLI flag values (None means not provided).

        Returns:
            Resolved :class:`RiveterConfig`.
        """
        config = RiveterConfig()  # start with defaults

        file_config = self._load_file(config_file)
        if file_config:
            config = config._merge_with_overrides(file_config)

        if cli_overrides:
            cli_config = RiveterConfig.from_dict(cli_overrides)
            config = config._merge_with_overrides(cli_config)

        return config

    def validate(self, config: RiveterConfig) -> List[str]:
        """Return a list of validation error messages (empty = valid)."""
        errors: List[str] = []
        if config.min_severity not in _VALID_SEVERITIES:
            errors.append(
                f"Invalid min_severity {config.min_severity!r}. Must be one of: {_VALID_SEVERITIES}"
            )
        if config.output_format not in _VALID_FORMATS:
            errors.append(
                f"Invalid output_format {config.output_format!r}. Must be one of: {_VALID_FORMATS}"
            )
        return errors

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_file(self, config_file: Optional[str]) -> Optional[RiveterConfig]:
        if config_file:
            resolved = os.path.realpath(os.path.abspath(config_file))
            if not os.path.isfile(resolved):
                raise ConfigurationError(f"Config file not found: {config_file}")
            return self._parse(resolved)

        for name in _DEFAULT_CONFIG_FILES:
            if os.path.isfile(name):
                log.debug("Using config file: %s", name)
                return self._parse(name)

        return None

    def _parse(self, path: str) -> RiveterConfig:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) if path.endswith(".json") else yaml.safe_load(fh)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise ConfigurationError(f"Invalid config file {path!r}: {exc}", config_file=path)
        except OSError as exc:
            raise ConfigurationError(f"Cannot read config file {path!r}: {exc}", config_file=path)

        if not isinstance(data, dict):
            raise ConfigurationError(
                f"Config file must contain a YAML/JSON object: {path}", config_file=path
            )

        return RiveterConfig.from_dict(data)
