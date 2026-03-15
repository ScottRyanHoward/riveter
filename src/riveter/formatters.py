"""Output formatters for validation results.

Available formats:
    json   — machine-readable JSON
    junit  — JUnit XML (compatible with CI systems like GitHub Actions, Jenkins)
    sarif  — SARIF 2.1.0 (compatible with GitHub Code Scanning and other SAST tools)

The default ``table`` format is rendered by the CLI using Rich and is not
handled here.
"""

import json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List

from ._version import __version__
from .scanner import ValidationResult


class OutputFormatter(ABC):
    """Base class for structured output formatters."""

    @abstractmethod
    def format(self, results: List[ValidationResult]) -> str:
        """Serialize results to a string."""

    def _summary(self, results: List[ValidationResult]) -> Dict[str, int]:
        passed = sum(1 for r in results if r.passed)
        skipped = sum(1 for r in results if r.message.startswith("SKIPPED:"))
        failed = sum(1 for r in results if not r.passed and not r.message.startswith("SKIPPED:"))
        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        }


class JSONFormatter(OutputFormatter):
    """JSON output for programmatic consumption."""

    def format(self, results: List[ValidationResult]) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "riveter_version": __version__,
                "summary": self._summary(results),
                "results": [r.to_dict() for r in results],
            },
            indent=2,
            ensure_ascii=False,
        )


class JUnitXMLFormatter(OutputFormatter):
    """JUnit XML output for CI/CD integration."""

    def format(self, results: List[ValidationResult]) -> str:
        summary = self._summary(results)
        ts = ET.Element("testsuite")
        ts.set("name", "Riveter Infrastructure Rules")
        ts.set("tests", str(summary["total"] - summary["skipped"]))
        ts.set("failures", str(summary["failed"]))
        ts.set("skipped", str(summary["skipped"]))
        ts.set("time", str(sum(r.execution_time for r in results)))
        ts.set("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

        for result in results:
            if result.message.startswith("SKIPPED:"):
                continue

            tc = ET.SubElement(ts, "testcase")
            tc.set("classname", f"riveter.{result.resource.get('resource_type', 'unknown')}")
            tc.set("name", result.rule.id)
            tc.set("time", str(result.execution_time))

            props = ET.SubElement(tc, "properties")
            for name, value in [
                ("resource_id", result.resource.get("id", "")),
                ("severity", result.severity.value),
                ("description", result.rule.description),
            ]:
                p = ET.SubElement(props, "property")
                p.set("name", name)
                p.set("value", str(value))

            if not result.passed:
                failure = ET.SubElement(tc, "failure")
                failure.set("message", result.message)
                failure.set("type", "RuleViolation")
                details = []
                for ar in result.assertion_results:
                    if not ar.passed:
                        details.append(
                            f"Property: {ar.property_path}\n"
                            f"Operator: {ar.operator}\n"
                            f"Expected: {ar.expected}\n"
                            f"Actual:   {ar.actual}\n"
                            f"Message:  {ar.message}"
                        )
                failure.text = "\n\n".join(details) if details else result.message

        return ET.tostring(ts, encoding="unicode", xml_declaration=True)


class SARIFFormatter(OutputFormatter):
    """SARIF 2.1.0 output for GitHub Code Scanning and other security tools."""

    _LEVEL_MAP = {"error": "error", "warning": "warning", "info": "note"}

    def format(self, results: List[ValidationResult]) -> str:
        active = [r for r in results if not r.message.startswith("SKIPPED:")]

        sarif: Dict[str, Any] = {
            "version": "2.1.0",
            "$schema": (
                "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
                "master/Schemata/sarif-schema-2.1.0.json"
            ),
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Riveter",
                            "version": __version__,
                            "informationUri": "https://github.com/ScottRyanHoward/riveter",
                            "shortDescription": {
                                "text": "Infrastructure Rule Enforcement as Code"
                            },
                            "rules": self._sarif_rules(active),
                        }
                    },
                    "results": self._sarif_results(active),
                    "invocations": [
                        {
                            "executionSuccessful": all(r.passed for r in active),
                            "endTimeUtc": (
                                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                            ),
                        }
                    ],
                }
            ],
        }
        return json.dumps(sarif, indent=2, ensure_ascii=False)

    def _sarif_rules(self, results: List[ValidationResult]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        rules = []
        for r in results:
            if r.rule.id in seen:
                continue
            seen.add(r.rule.id)
            rules.append(
                {
                    "id": r.rule.id,
                    "shortDescription": {"text": r.rule.description},
                    "defaultConfiguration": {
                        "level": self._LEVEL_MAP.get(r.severity.value, "warning")
                    },
                    "properties": {"resource_type": r.rule.resource_type},
                }
            )
        return rules

    def _sarif_results(self, results: List[ValidationResult]) -> List[Dict[str, Any]]:
        output = []
        for r in results:
            if r.passed:
                continue
            entry: Dict[str, Any] = {
                "ruleId": r.rule.id,
                "level": self._LEVEL_MAP.get(r.severity.value, "warning"),
                "message": {"text": r.message},
                "locations": [
                    {
                        "logicalLocations": [
                            {
                                "name": r.resource.get("id", "unknown"),
                                "fullyQualifiedName": (
                                    f"{r.resource.get('resource_type', 'unknown')}"
                                    f".{r.resource.get('id', 'unknown')}"
                                ),
                                "kind": "resource",
                            }
                        ]
                    }
                ],
                "properties": {
                    "resource_type": r.resource.get("resource_type"),
                    "resource_id": r.resource.get("id"),
                },
            }
            failed_assertions = [ar for ar in r.assertion_results if not ar.passed]
            if failed_assertions:
                entry["properties"]["failed_assertions"] = [
                    {
                        "property_path": ar.property_path,
                        "operator": ar.operator,
                        "expected": str(ar.expected),
                        "actual": str(ar.actual),
                        "message": ar.message,
                    }
                    for ar in failed_assertions
                ]
            output.append(entry)
        return output
