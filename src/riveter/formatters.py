"""Output formatters for validation results.

Available formats:
    json   — machine-readable JSON
    junit  — JUnit XML (compatible with CI systems like GitHub Actions, Jenkins)
    sarif  — SARIF 2.1.0 (compatible with GitHub Code Scanning and other SAST tools)
    html   — self-contained HTML report with filterable results (audit / sharing)

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
                            "shortDescription": {"text": "Infrastructure Rule Enforcement as Code"},
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


class HTMLFormatter(OutputFormatter):
    """Self-contained HTML report with summary stats, filterable results, and expandable
    assertion details. Designed for sharing with non-engineers and audit documentation."""

    def format(self, results: List[ValidationResult]) -> str:
        summary = self._summary(results)
        failed_by_sev = self._failed_by_severity(results)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        data_json = json.dumps(self._to_js_data(results), ensure_ascii=False)

        html = _HTML_TEMPLATE
        html = html.replace("__VERSION__", __version__)
        html = html.replace("__TIMESTAMP__", ts)
        html = html.replace("__TOTAL__", str(summary["total"]))
        html = html.replace("__PASSED__", str(summary["passed"]))
        html = html.replace("__FAILED__", str(summary["failed"]))
        html = html.replace("__SKIPPED__", str(summary["skipped"]))
        html = html.replace("__ERR__", str(failed_by_sev["error"]))
        html = html.replace("__WARN__", str(failed_by_sev["warning"]))
        html = html.replace("__INFO__", str(failed_by_sev["info"]))
        html = html.replace("__DATA_JSON__", data_json)
        return html

    def _failed_by_severity(self, results: List[ValidationResult]) -> Dict[str, int]:
        counts: Dict[str, int] = {"error": 0, "warning": 0, "info": 0}
        for r in results:
            if not r.passed and not r.message.startswith("SKIPPED:"):
                counts[r.severity.value] = counts.get(r.severity.value, 0) + 1
        return counts

    def _to_js_data(self, results: List[ValidationResult]) -> List[Dict[str, Any]]:
        rows = []
        for r in results:
            is_skipped = r.message.startswith("SKIPPED:")
            status = "skip" if is_skipped else ("pass" if r.passed else "fail")
            rows.append(
                {
                    "status": status,
                    "severity": r.severity.value,
                    "rule_id": r.rule.id,
                    "description": r.rule.description,
                    "resource_type": r.rule.resource_type,
                    "resource_id": r.resource.get("id", ""),
                    "message": r.message,
                    "assertions": [
                        {
                            "property": ar.property_path,
                            "operator": ar.operator,
                            "expected": str(ar.expected),
                            "actual": str(ar.actual),
                            "passed": ar.passed,
                            "message": ar.message,
                        }
                        for ar in r.assertion_results
                    ],
                }
            )
        return rows


# ---------------------------------------------------------------------------
# HTML template — uses __PLACEHOLDER__ markers so CSS/JS braces are untouched
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Riveter Report — __TIMESTAMP__</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           font-size: 14px; color: #111827; background: #f1f5f9; min-height: 100vh; }

    /* ── Header ── */
    header { background: #1e293b; color: #fff; padding: 14px 24px;
             display: flex; align-items: center; gap: 12px; }
    header h1 { font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }
    header .subtitle { color: #94a3b8; font-size: 13px; flex: 1; }
    header .ts { color: #64748b; font-size: 12px; font-variant-numeric: tabular-nums; }

    /* ── Summary cards ── */
    .summary { display: flex; gap: 12px; padding: 20px 24px;
               background: #fff; border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }
    .card { flex: 1; min-width: 120px; padding: 14px 18px; border-radius: 8px;
            border: 1px solid #e2e8f0; }
    .card .count { font-size: 30px; font-weight: 700; line-height: 1; }
    .card .label { font-size: 11px; color: #6b7280; text-transform: uppercase;
                   letter-spacing: 0.6px; margin-top: 4px; }
    .card .sev { font-size: 11px; color: #9ca3af; margin-top: 6px; }
    .card.total { background: #f8fafc; }
    .card.pass  { background: #f0fdf4; border-color: #bbf7d0; }
    .card.pass .count { color: #16a34a; }
    .card.fail  { background: #fef2f2; border-color: #fecaca; }
    .card.fail .count { color: #dc2626; }
    .card.skip  { background: #f9fafb; border-color: #e5e7eb; }
    .card.skip .count { color: #6b7280; }

    /* ── Filters ── */
    .filters { display: flex; align-items: center; gap: 10px; padding: 12px 24px;
               background: #fff; border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }
    .filters select, .filters input {
      padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px;
      font-size: 13px; color: #374151; background: #fff; }
    .filters input { flex: 1; min-width: 160px; max-width: 300px; }
    .filters select:focus, .filters input:focus {
      outline: none; border-color: #6366f1;
      box-shadow: 0 0 0 3px rgba(99,102,241,0.12); }
    #resultCount { margin-left: auto; font-size: 12px; color: #9ca3af;
                   white-space: nowrap; }

    /* ── Table ── */
    .table-wrap { padding: 20px 24px 40px; }
    table { width: 100%; border-collapse: collapse; background: #fff;
            border-radius: 8px; overflow: hidden;
            border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
    thead th { padding: 9px 14px; text-align: left; font-size: 11px; font-weight: 600;
               text-transform: uppercase; letter-spacing: 0.5px; color: #6b7280;
               background: #f9fafb; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
    tbody td { padding: 10px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
    .result-row { cursor: pointer; user-select: none; }
    .result-row:hover td { background: #f8fafc; }
    .result-row td.mono { font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
                          font-size: 12px; }
    .result-row td.msg { color: #6b7280; font-size: 13px; max-width: 320px;
                         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .no-results { text-align: center; padding: 48px; color: #9ca3af; font-style: italic; }

    /* ── Badges ── */
    .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
             font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }
    .badge-pass    { background: #dcfce7; color: #15803d; }
    .badge-fail    { background: #fee2e2; color: #dc2626; }
    .badge-skip    { background: #f3f4f6; color: #6b7280; }
    .badge-error   { background: #fee2e2; color: #dc2626; }
    .badge-warning { background: #fef9c3; color: #b45309; }
    .badge-info    { background: #dbeafe; color: #2563eb; }

    /* ── Detail row ── */
    .detail-row td { background: #f8fafc; padding: 0; }
    .detail-inner { padding: 16px 20px 20px; border-top: 2px solid #e0e7ff; }
    .detail-meta { display: grid; grid-template-columns: max-content 1fr;
                   gap: 5px 18px; margin-bottom: 14px; font-size: 13px; }
    .detail-meta dt { color: #6b7280; font-weight: 500; }
    .detail-meta dd code { font-family: monospace; font-size: 12px;
                           background: #e5e7eb; padding: 1px 6px; border-radius: 3px; }
    .assert-title { font-size: 12px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.4px; color: #6b7280; margin-bottom: 8px; }
    .assert-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .assert-table th { padding: 5px 10px; text-align: left; background: #e5e7eb;
                       color: #374151; font-weight: 600; border: 1px solid #d1d5db; }
    .assert-table td { padding: 5px 10px; border: 1px solid #e5e7eb;
                       font-family: monospace; font-size: 12px; }
    .assert-pass td { background: #f0fdf4; }
    .assert-fail td { background: #fef2f2; }
    .no-assert { color: #9ca3af; font-size: 12px; font-style: italic; }

    /* ── Footer ── */
    footer { text-align: center; padding: 18px; color: #9ca3af; font-size: 12px;
             border-top: 1px solid #e2e8f0; background: #fff; }
  </style>
</head>
<body>

<header>
  <h1>&#x1F527; riveter</h1>
  <span class="subtitle">Infrastructure Rule Enforcement Report</span>
  <span class="ts">__TIMESTAMP__</span>
</header>

<section class="summary">
  <div class="card total">
    <div class="count">__TOTAL__</div>
    <div class="label">Total checks</div>
  </div>
  <div class="card pass">
    <div class="count">__PASSED__</div>
    <div class="label">Passed</div>
  </div>
  <div class="card fail">
    <div class="count">__FAILED__</div>
    <div class="label">Failed</div>
    <div class="sev">__ERR__ error &nbsp;&#x2022;&nbsp; __WARN__ warning &nbsp;&#x2022;&nbsp; __INFO__ info</div>
  </div>
  <div class="card skip">
    <div class="count">__SKIPPED__</div>
    <div class="label">Skipped</div>
  </div>
</section>

<div class="filters">
  <select id="statusFilter">
    <option value="all">All statuses</option>
    <option value="fail">Failed</option>
    <option value="pass">Passed</option>
    <option value="skip">Skipped</option>
  </select>
  <select id="severityFilter">
    <option value="all">All severities</option>
    <option value="error">Error</option>
    <option value="warning">Warning</option>
    <option value="info">Info</option>
  </select>
  <input id="search" type="search" placeholder="Search rule ID or resource&#x2026;">
  <span id="resultCount"></span>
</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Status</th>
        <th>Severity</th>
        <th>Rule ID</th>
        <th>Resource</th>
        <th>Message</th>
      </tr>
    </thead>
    <tbody id="results"></tbody>
  </table>
</div>

<footer>Generated by riveter v__VERSION__ &nbsp;&#x2022;&nbsp; __TIMESTAMP__</footer>

<script>
  const DATA = __DATA_JSON__;

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function statusBadge(s) {
    const labels = { pass: 'PASS', fail: 'FAIL', skip: 'SKIP' };
    return '<span class="badge badge-' + s + '">' + (labels[s] || s.toUpperCase()) + '</span>';
  }

  function severityBadge(s) {
    return '<span class="badge badge-' + s + '">' + s + '</span>';
  }

  function assertionDetail(assertions) {
    if (!assertions || !assertions.length) {
      return '<p class="no-assert">No assertion details available.</p>';
    }
    const rows = assertions.map(function(a) {
      var cls = a.passed ? 'assert-pass' : 'assert-fail';
      return '<tr class="' + cls + '">'
        + '<td>' + esc(a.property) + '</td>'
        + '<td>' + esc(a.operator) + '</td>'
        + '<td>' + esc(a.expected) + '</td>'
        + '<td>' + esc(a.actual)   + '</td>'
        + '<td>' + (a.passed ? '&#x2713;' : '&#x2717;') + '</td>'
        + '</tr>';
    }).join('');
    return '<p class="assert-title">Assertions</p>'
      + '<table class="assert-table">'
      + '<thead><tr><th>Property</th><th>Operator</th><th>Expected</th>'
      + '<th>Actual</th><th></th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>';
  }

  function renderTable(data) {
    var tbody = document.getElementById('results');
    var count = document.getElementById('resultCount');
    if (!data.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="no-results">No matching results.</td></tr>';
      count.textContent = '0 results';
      return;
    }
    tbody.innerHTML = data.map(function(r, i) {
      var detailHtml = '<div class="detail-inner">'
        + '<dl class="detail-meta">'
        + '<dt>Description</dt><dd>' + esc(r.description) + '</dd>'
        + '<dt>Resource type</dt><dd><code>' + esc(r.resource_type) + '</code></dd>'
        + '</dl>'
        + assertionDetail(r.assertions)
        + '</div>';

      return '<tr class="result-row" onclick="toggleDetail(' + i + ')">'
        + '<td>' + statusBadge(r.status) + '</td>'
        + '<td>' + severityBadge(r.severity) + '</td>'
        + '<td class="mono">' + esc(r.rule_id) + '</td>'
        + '<td class="mono">' + (r.resource_id ? esc(r.resource_id) : '<em style="color:#9ca3af">—</em>') + '</td>'
        + '<td class="msg" title="' + esc(r.message) + '">' + esc(r.message) + '</td>'
        + '</tr>'
        + '<tr id="detail-' + i + '" class="detail-row" style="display:none">'
        + '<td colspan="5">' + detailHtml + '</td>'
        + '</tr>';
    }).join('');
    var n = data.length;
    count.textContent = n + ' result' + (n !== 1 ? 's' : '');
  }

  function applyFilters() {
    var status   = document.getElementById('statusFilter').value;
    var severity = document.getElementById('severityFilter').value;
    var search   = document.getElementById('search').value.toLowerCase();
    var filtered = DATA.filter(function(r) {
      if (status !== 'all' && r.status !== status) return false;
      if (severity !== 'all' && r.severity !== severity) return false;
      if (search) {
        var haystack = (r.rule_id + ' ' + r.resource_id).toLowerCase();
        if (haystack.indexOf(search) === -1) return false;
      }
      return true;
    });
    renderTable(filtered);
  }

  function toggleDetail(i) {
    var row = document.getElementById('detail-' + i);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
  }

  document.getElementById('statusFilter').addEventListener('change', applyFilters);
  document.getElementById('severityFilter').addEventListener('change', applyFilters);
  document.getElementById('search').addEventListener('input', applyFilters);

  renderTable(DATA);
</script>
</body>
</html>
"""
