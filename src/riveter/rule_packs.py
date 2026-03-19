# Copyright (c) 2026 Scott Howard
# SPDX-License-Identifier: MIT

"""Rule pack management.

Rule packs are YAML files that bundle related rules together under a metadata
header. They live in well-known directories and can be referenced by name.

Rule pack file format:
    metadata:
      name: aws-security
      version: 1.0.0
      description: AWS Security Best Practices
      author: Riveter Team
      created: 2024-01-01
      updated: 2024-01-01
      tags: [security, aws]
      min_riveter_version: 0.1.0

    rules:
      - id: ...
        ...
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import yaml

from .exceptions import RulePackError
from .rules import Rule, Severity

log = logging.getLogger(__name__)


def _default_search_dirs() -> List[str]:
    """Return the ordered list of directories to search for rule packs."""
    dirs: List[str] = []

    # When running as a PyInstaller binary, sys._MEIPASS is the temp extraction dir.
    # Rule packs are not bundled into the binary; they are installed separately.

    # Relative to this source file (development installs)
    src_relative = os.path.join(os.path.dirname(__file__), "..", "..", "rule_packs")
    dirs.append(os.path.normpath(src_relative))

    # User-local override directory
    dirs.append(os.path.expanduser("~/.riveter/rule_packs"))

    # Homebrew system install locations
    dirs.append("/opt/homebrew/share/riveter/rule_packs")  # Apple Silicon
    dirs.append("/usr/local/share/riveter/rule_packs")  # Intel / Linux

    return [d for d in dirs if os.path.isdir(d)]


@dataclass
class RulePackMetadata:
    name: str
    version: str
    description: str
    author: str = "Unknown"
    created: str = ""
    updated: str = ""
    tags: List[str] = field(default_factory=list)
    min_riveter_version: str = "0.1.0"


@dataclass
class RulePack:
    """A named collection of rules with associated metadata."""

    metadata: RulePackMetadata
    rules: List[Rule]

    def __post_init__(self) -> None:
        ids = [r.id for r in self.rules]
        duplicates = {rid for rid in ids if ids.count(rid) > 1}
        if duplicates:
            raise RulePackError(
                f"Duplicate rule IDs in pack '{self.metadata.name}': {', '.join(duplicates)}",
                pack_name=self.metadata.name,
            )

    def filter_by_severity(self, min_severity: Severity) -> "RulePack":
        """Return a new RulePack containing only rules at or above min_severity."""
        return RulePack(
            metadata=self.metadata,
            rules=[r for r in self.rules if r.severity >= min_severity],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": {
                "name": self.metadata.name,
                "version": self.metadata.version,
                "description": self.metadata.description,
                "author": self.metadata.author,
                "tags": self.metadata.tags,
            },
            "rule_count": len(self.rules),
            "rules": [r.id for r in self.rules],
        }


class RulePackManager:
    """Loads, validates, and lists rule packs from well-known directories.

    Extra directories can be passed at construction time or added to
    :attr:`rule_pack_dirs` before calling :meth:`load_rule_pack`.
    """

    def __init__(self, extra_dirs: Optional[List[str]] = None) -> None:
        self.rule_pack_dirs: List[str] = _default_search_dirs()
        if extra_dirs:
            for d in extra_dirs:
                if d not in self.rule_pack_dirs:
                    self.rule_pack_dirs.append(d)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_rule_pack(self, pack_name: str) -> RulePack:
        """Load a rule pack by name from the search directories.

        Args:
            pack_name: The pack name (e.g. ``"aws-security"``).

        Returns:
            Parsed :class:`RulePack`.

        Raises:
            FileNotFoundError: When the pack is not found in any search directory.
            RulePackError: When the pack file is malformed.
        """
        path = self._find(pack_name)
        if path is None:
            searched = ", ".join(self.rule_pack_dirs) or "(none)"
            raise FileNotFoundError(f"Rule pack '{pack_name}' not found. Searched: {searched}")
        return self._load_file(path)

    def load_rule_pack_from_file(self, file_path: str) -> RulePack:
        """Load a rule pack directly from a file path."""
        return self._load_file(file_path)

    def list_available_packs(self) -> List[Dict[str, Union[str, int]]]:
        """Return metadata for every rule pack found in the search directories."""
        packs: List[Dict[str, Union[str, int]]] = []
        seen: set[str] = set()

        for directory in self.rule_pack_dirs:
            if not os.path.isdir(directory):
                continue
            for filename in sorted(os.listdir(directory)):
                if not (filename.endswith(".yml") or filename.endswith(".yaml")):
                    continue
                file_path = os.path.join(directory, filename)
                if not os.path.isfile(file_path):
                    continue
                if file_path in seen:
                    continue
                seen.add(file_path)
                try:
                    pack = self._load_file(file_path)
                    packs.append(
                        {
                            "name": pack.metadata.name,
                            "version": pack.metadata.version,
                            "description": pack.metadata.description,
                            "author": pack.metadata.author,
                            "rule_count": len(pack.rules),
                            "file_path": file_path,
                        }
                    )
                except Exception as exc:
                    log.debug("Could not load %s: %s", file_path, exc)
                    # Still list it with limited info
                    base = filename.rsplit(".", 1)[0]
                    packs.append(
                        {
                            "name": base,
                            "version": "unknown",
                            "description": f"(failed to load: {exc})",
                            "author": "unknown",
                            "rule_count": 0,
                            "file_path": file_path,
                        }
                    )

        return sorted(packs, key=lambda p: str(p["name"]))

    def validate_rule_pack(self, file_path: str) -> Dict[str, Any]:
        """Validate a rule pack file and return a report dict."""
        report: Dict[str, Any] = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "rule_count": 0,
            "metadata": None,
        }
        try:
            pack = self._load_file(file_path)
            report["valid"] = True
            report["rule_count"] = len(pack.rules)
            report["metadata"] = {
                "name": pack.metadata.name,
                "version": pack.metadata.version,
            }
            if not pack.rules:
                report["warnings"].append("Rule pack contains no rules")
            if not re.match(r"^\d+\.\d+\.\d+$", pack.metadata.version):
                report["warnings"].append(
                    f"Version '{pack.metadata.version}' does not follow semantic versioning"
                )
        except Exception as exc:
            report["errors"].append(str(exc))
        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find(self, pack_name: str) -> Optional[str]:
        for directory in self.rule_pack_dirs:
            for ext in (".yml", ".yaml"):
                candidate = os.path.join(directory, f"{pack_name}{ext}")
                if os.path.isfile(candidate):
                    return candidate
        return None

    def _load_file(self, file_path: str) -> RulePack:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise RulePackError(
                f"Invalid YAML in rule pack '{file_path}': {exc}",
                pack_name=os.path.basename(file_path),
            ) from exc

        if not isinstance(data, dict):
            raise RulePackError(f"Rule pack must be a YAML dict: {file_path}")
        if "metadata" not in data or "rules" not in data:
            raise RulePackError(f"Rule pack must have 'metadata' and 'rules' sections: {file_path}")

        md = data["metadata"]
        try:
            metadata = RulePackMetadata(
                name=md["name"],
                version=md["version"],
                description=md["description"],
                author=md.get("author", "Unknown"),
                created=md.get("created", ""),
                updated=md.get("updated", ""),
                tags=md.get("tags", []),
                min_riveter_version=md.get("min_riveter_version", "0.1.0"),
            )
        except KeyError as exc:
            raise RulePackError(f"Missing required metadata field {exc} in '{file_path}'") from exc

        from .rules import Rule  # local import to avoid circular

        rules: List[Rule] = []
        for rule_dict in data["rules"]:
            if not isinstance(rule_dict, dict):
                raise RulePackError(f"Each rule must be a dict in '{file_path}'")
            rules.append(Rule(rule_dict))

        return RulePack(metadata=metadata, rules=rules)
