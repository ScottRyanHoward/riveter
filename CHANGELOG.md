# Changelog

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

All notable changes to Riveter are documented here.

## [Unreleased]

### Added
- **`riveter scan-state` command**: validates a `terraform.tfstate` file against the same YAML rule packs used by `riveter scan`, enabling drift detection. Supports all output formats (`table`, `json`, `junit`, `sarif`, `html`), all filtering flags, and reading state from stdin (`-s -`) for use with any remote Terraform backend via `terraform state pull`.
- New `extract_state.py` module: parses Terraform state format v4+ JSON into the same resource dict shape as `extract_config.py`, so the scanner and all formatters work without modification. Handles `count`/`for_each` multi-instance resources, module-prefixed addresses, data source exclusion, and a 50 MB size guard.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

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
