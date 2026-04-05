# Contributing to Riveter

Thank you for your interest in contributing! This document covers how to set up a development environment, run tests, and submit changes.

---

## Development Setup

**Requirements:** Python 3.12+, pip, git.

```bash
git clone https://github.com/ScottRyanHoward/riveter.git
cd riveter

# Install with development dependencies and pre-commit hooks
make install-dev
```

This installs:
- The `riveter` package in editable mode
- All dev dependencies (pytest, black, ruff, mypy, etc.)
- Pre-commit hooks that run formatting, linting, and type checks on every commit

---

## Running Tests

```bash
make test          # Full test suite with coverage
make test-fast     # Tests without coverage (faster)
```

---

## Code Quality

All code must pass these checks before merging. Pre-commit hooks run them automatically:

```bash
make format        # Auto-format with black + isort
make lint          # Ruff linter
make type-check    # mypy strict type checking
make security      # bandit security scan
make pre-commit    # Run all hooks
```

---

## Project Structure

```
riveter/
├── src/riveter/          # Python package
│   ├── _version.py       # Version string
│   ├── cli.py            # CLI entry point (Click)
│   ├── config.py         # Config file loading
│   ├── exceptions.py     # Custom exception hierarchy
│   ├── extract_config.py # Terraform HCL → resource dicts
│   ├── formatters.py     # Output formatters (JSON, JUnit, SARIF)
│   ├── operators.py      # Comparison operators
│   ├── rule_packs.py     # Rule pack loading and management
│   ├── rules.py          # Rule class, load_rules()
│   └── scanner.py        # Core validation engine
├── rule_packs/           # Built-in YAML rule packs
├── tests/                # Pytest test suite
├── docs/                 # User and developer documentation
├── examples/             # Example Terraform and rules files
├── .github/workflows/    # CI/CD (ci.yml, release.yml)
├── build_binary.py       # PyInstaller build script
└── pyproject.toml        # Project metadata and tool config
```

---

## Adding or Updating Rule Packs

Rule pack files live in `rule_packs/` and use this structure:

```yaml
metadata:
  name: my-pack
  version: 1.0.0
  description: My custom rule pack
  author: Your Name
  created: 2024-01-01
  updated: 2024-01-01
  tags: [security, aws]
  min_riveter_version: 0.1.0

rules:
  - id: my-unique-rule-id
    resource_type: aws_instance
    description: What this rule checks
    filter:                   # optional — restricts which resources the rule applies to
      tags.Environment: production
    assert:
      root_block_device.encrypted: true
    metadata:
      tags: [encryption]
      references:
        - https://docs.aws.amazon.com/...
```

**Guidelines:**
- Rule IDs must be unique across the entire pack.
- Use descriptive IDs: `ec2_encrypted_ebs_volumes`, not `rule_42`.
- Add a `references` field pointing to official documentation.
- Include at least one test that loads the pack in `tests/test_rule_packs.py`.

---

## Submitting Changes

1. Fork the repository and create a feature branch.
2. Make your changes with tests.
3. Run `make pre-commit` to ensure all checks pass.
4. Open a pull request against `main` with a clear description of the change.

---

## Release Process

Releases are created by the maintainer via the **Release** GitHub Actions workflow:

1. Navigate to **Actions → Release → Run workflow**.
2. Choose the version bump type: `patch`, `minor`, or `major`.
3. The workflow automatically:
   - Bumps the version in `_version.py` and `pyproject.toml`
   - Updates `CHANGELOG.md`
   - Creates a git tag and GitHub release (draft)
   - Builds standalone binaries for macOS (arm64 + Intel) and Linux
   - Attaches binaries to the release
   - Updates the Homebrew formula in `homebrew-riveter`
   - Publishes the release

**Required GitHub secrets:**
- `HOMEBREW_TAP_TOKEN` — a Personal Access Token with write access to the `homebrew-riveter` repo
