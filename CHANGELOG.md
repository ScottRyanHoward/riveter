# Changelog

## [0.2.22] - 2026-04-09

### Added
- Release v0.2.22

## [0.2.21] - 2026-04-05

### Added
- Release v0.2.21

## [0.2.20] - 2026-04-05

### Added
- Release v0.2.20

## [0.2.19] - 2026-04-05

### Added
- Release v0.2.19

## [0.2.18] - 2026-04-05

### Added
- **`--output / -o` flag** on `riveter scan` and `riveter scan-state`: writes formatted output (HTML, JSON, SARIF, JUnit) directly to a file while still showing the table summary in the terminal. Removes the need to choose between a file and terminal feedback.

### Changed
- **Severity column removed** from the terminal table. Output now shows Status, Rule ID, Resource, and Message — a cleaner view that focuses on actionable information.
- **Progress messages routed to stderr**: "Loaded X rule(s)" and "Scanning X resource(s)" messages now go to stderr instead of stdout, so piped and redirected output formats (HTML, JSON, SARIF, JUnit) are clean with no informational noise mixed in.
- **All 15 rule packs bumped to v1.1.0** with accuracy and currency fixes:
  - `cis-aws`: updated to CIS AWS Foundations Benchmark v3.0.0 (was v1.4.0); fixed root access key rule logic
  - `cis-azure`: updated to CIS Azure Foundations Benchmark v2.0.0 (was v1.3.0); updated Security Center references to Microsoft Defender for Cloud
  - `cis-gcp`: updated to CIS GCP Foundations Benchmark v2.0.0 (was v1.3.0); fixed 10+ mismatched rule descriptions and broken API key assertion
  - `aws-pci-dss`: updated to PCI-DSS v4.0 (was v3.2.1, which became non-compliant March 2024); corrected requirement numbers; replaced deprecated Inspector Classic with Inspector v2
  - `aws-hipaa`: fixed MFA rule (was checking wrong resource/attribute); updated Elasticsearch → OpenSearch resource type
  - `aws-security`: fixed `vpc_flow_logs` rule (was checking DNS settings on `aws_vpc` instead of `aws_flow_log`)
  - `aws-well-architected`: replaced tautological SNS and Lambda assertions with meaningful checks
  - `azure-hipaa`: replaced deprecated `azurerm_app_service` / `azurerm_function_app` resource types
  - `azure-well-architected`: replaced tag-based TDE and geo-replication assertions with actual resource properties; updated Front Door resource type
  - `azure-security`, `multi-cloud-security`: updated all `docs.microsoft.com` URLs to `learn.microsoft.com`
  - `gcp-security`: fixed service account key rotation assertion (was always-passing tautology)
  - `gcp-well-architected`: updated SQL machine type regex for current generations; replaced preemptible VM check with Spot VM check
  - `kubernetes-security`: updated annotation conventions to match real tooling (Trivy Operator)
  - `soc2-security`: replaced made-up tag assertion with actual Azure storage encryption properties

### Fixed
- Pre-commit hooks (`black`, `isort`, `ruff`, `mypy`, `bandit`, `pytest`) are now installed and active, catching formatting and lint issues locally before they reach CI.
- `.gitignore` now excludes `.claude/worktrees/` to prevent Claude Code worktrees from being accidentally staged.

---

## [0.2.17] - 2026-04-05

### Added
- Release v0.2.17

## [0.2.16] - 2026-04-05

### Added
- Release v0.2.16

## [0.2.15] - 2026-04-04

### Added
- Release v0.2.15

## [0.2.14] - 2026-04-04

### Added
- Release v0.2.14

## [0.2.13] - 2026-03-28

### Added
- Release v0.2.13

## [0.2.12] - 2026-03-19

### Added
- Release v0.2.12

## [0.2.11] - 2026-03-19

### Added
- Release v0.2.11

## [0.2.10] - 2026-03-19

### Added
- Release v0.2.10

## [0.2.9] - 2026-03-18

### Added
- Release v0.2.9

## [0.2.8] - 2026-03-18

### Added
- Release v0.2.8

## [0.2.7] - 2026-03-18

### Added
- Release v0.2.7

## [0.2.6] - 2026-03-18

### Added
- Release v0.2.6

## [0.2.5] - 2026-03-17

### Added
- Release v0.2.5

## [0.2.4] - 2026-03-16

### Added
- Release v0.2.4

---

## [0.2.3] - 2026-03-16

### Fixed
- `brew upgrade riveter` now correctly picks up the latest release after running `brew update` to sync the tap.

---

## [0.2.2] - 2026-03-16

### Added
- **HTML output format** (`-f html`): generates a fully self-contained HTML report with embedded CSS and JavaScript. Features include summary cards with pass/fail/skip/severity counts, client-side filtering by status, severity, and free-text search, and expandable rows showing per-assertion details. No external dependencies — the report can be emailed or opened offline.

### Fixed
- `Invalid output_format 'html'` error when using `-f html` via a `riveter.yml` config file. The `_VALID_FORMATS` constant in `config.py` now includes `html` to match the CLI's `click.Choice` list.

---

## [0.2.1] - 2026-03-16

### Fixed
- PyInstaller binary now correctly bundles the `hcl2.lark` grammar file required by `python-hcl2`. Previously the binary raised `FileNotFoundError: hcl2/hcl2.lark` at runtime. Fixed by adding `--collect-data hcl2` and `--collect-data lark` to the PyInstaller build arguments.

---

## [0.2.0] - 2026-03-16

### Changed
- Release workflow now builds binaries for **macOS Apple Silicon** (`macos-14`) and **Linux x86_64** (`ubuntu-latest`) only. The retired `macos-13` (Intel) GitHub Actions runner has been removed. Intel Mac users can run the Apple Silicon binary transparently via Rosetta 2.

### Fixed
- Release workflow: `KeyError: 'REPO'` in the Homebrew formula generation step. The `REPO` variable is now passed via the step's `env:` block so it is visible to `os.environ` inside the Python script.
- Release workflow: `SyntaxWarning: invalid escape sequence '\#'` on Python 3.12+. Ruby interpolation sequences (`#{share}`, `#{bin}`) are now stored as plain Python string variables to avoid the invalid escape.

---

## [0.1.0] - 2026-03-15

### Added
- Initial release of the rebuilt Riveter tool
- `riveter scan` command with support for custom rules files and built-in rule packs
- `riveter list-rule-packs` command
- 15 built-in rule packs: aws-security, azure-security, gcp-security, kubernetes-security,
  multi-cloud-security, cis-aws, cis-azure, cis-gcp, aws-well-architected, azure-well-architected,
  gcp-well-architected, aws-hipaa, azure-hipaa, aws-pci-dss, soc2-security
- Assertion operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `regex`, `contains`, `length`,
  `subset`, `present`
- Output formats: table (Rich terminal), JSON, JUnit XML, SARIF 2.1.0
- Dot-notation nested attribute resolution (e.g. `root_block_device.encrypted`)
- Rule filters to scope rules to specific resource subsets
- Config file support (`riveter.yml` / `.riveter.yml`)
- `--min-severity`, `--include-rules`, `--exclude-rules` flags
- Directory scanning (recursively finds all `.tf` files)
- Homebrew distribution via `ScottRyanHoward/riveter/riveter`
- GitHub Actions CI/CD pipeline with automated binary releases and Homebrew formula updates

---

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).
