# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

To report a vulnerability, email `ScottRyanHoward@users.noreply.github.com` with the subject line:

```
[SECURITY] riveter
```

Include as much of the following as possible:

- Riveter version (`riveter --version`)
- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any relevant Terraform snippets or rule pack files (sanitized of real credentials)

## Response Timeline

- **Acknowledgement:** within 72 hours
- **Assessment and timeline:** within 14 days

If you do not receive an acknowledgement within 72 hours, please follow up to ensure the original message was received.

## Disclosure Policy

Once a fix is ready:

1. A patched release will be published.
2. The vulnerability will be documented in the changelog.
3. Credit will be given to the reporter unless they prefer to remain anonymous.

We ask that you give us reasonable time to address the issue before any public disclosure.

## Known Issues in Dependencies

| CVE | Affected Package | Impact on riveter | Status |
|-----|-----------------|-------------------|--------|
| CVE-2026-3219 | `pip` (Python package manager) | None — affects the CI installer only, not riveter's code or runtime dependencies | No fix version available yet; will be resolved when pip releases a patch |

Users who install riveter via `pip install riveter` or run riveter in their own environment are **not exposed** to this vulnerability through riveter's code. The CVE affects pip itself and is only relevant to CI environments that run pip. This table will be updated as patches become available.
