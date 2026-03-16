# Changelog

## [0.2.0] - 2026-03-16

### Added
- Release v0.2.0

All notable changes to Riveter are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

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
