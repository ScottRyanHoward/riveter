# Riveter Developer Guide

This guide is for contributors and maintainers. It covers the architecture, code organization, and how to extend Riveter.

---

## Architecture Overview

```
User runs: riveter scan -p aws-security -t main.tf

         cli.py                    (Click CLI, orchestration)
            │
            ├── config.py          (Load riveter.yml + CLI overrides)
            │
            ├── rule_packs.py      (Find & load rule pack YAML files)
            │       └── rules.py   (Parse individual rules, Severity enum)
            │               └── operators.py  (Comparison operators)
            │
            ├── extract_config.py  (Parse HCL → resource dicts via hcl2)
            │
            ├── scanner.py         (Apply rules to resources → ValidationResults)
            │
            └── formatters.py      (Serialize results → JSON / JUnit / SARIF)
```

### Data flow

1. **Config resolution**: `ConfigManager.load_config()` merges defaults → config file → CLI flags.
2. **Rule loading**: `RulePackManager.load_rule_pack()` finds and parses YAML rule packs. Each pack contains `Rule` objects built from the YAML definition.
3. **HCL parsing**: `extract_terraform_config()` uses `python-hcl2` to parse Terraform files into a list of resource dicts, each with an `id` and `resource_type` key plus all HCL attributes.
4. **Validation**: `validate_resources()` iterates over every (rule, resource) pair where the resource type matches and all filter conditions are satisfied. For each matching pair, `Rule.validate_assertions()` evaluates each assertion and returns `AssertionResult` objects.
5. **Output**: `ValidationResult` objects are passed to the appropriate formatter or rendered as a Rich table in the CLI.

---

## Module Reference

### `_version.py`

Single source of truth for the package version. Updated automatically by the release workflow.

```python
__version__ = "0.1.0"
def get_version() -> str: ...
```

### `exceptions.py`

Custom exception hierarchy rooted at `RiveterError`. All exceptions carry optional `suggestions` for user-facing error messages.

| Exception | When raised |
|-----------|-------------|
| `ConfigurationError` | Invalid config file or config values |
| `TerraformParsingError` | HCL parse failure |
| `RuleValidationError` | Malformed rule definition |
| `RulePackError` | Rule pack loading failure |
| `FileSystemError` | File not found, permission error, size limit |

### `operators.py`

Stateless comparison operators implementing `ComparisonOperator(ABC)`:

| Class | Operators |
|-------|-----------|
| `NumericOperator` | `eq`, `ne`, `gt`, `gte`, `lt`, `lte` |
| `RegexOperator` | `regex` |
| `ListOperator` | `contains`, `length`, `subset` |

`OperatorFactory.create_operator(name_or_dict)` returns the right operator.

`NestedAttributeResolver.resolve_path(obj, path)` traverses nested dicts using dot notation and `[n]` array indices.

### `rules.py`

- `Severity` — enum with `ERROR > WARNING > INFO` ordering.
- `AssertionResult` — dataclass holding the outcome of a single assertion.
- `Rule` — parses a rule dict, validates its structure and regex patterns, exposes `matches_resource()` and `validate_assertions()`.
- `load_rules(path)` — loads a YAML rules file into a `List[Rule]`.

### `scanner.py`

`validate_resources(rules, resources, min_severity)` — the core loop. Returns `List[ValidationResult]`. Rules that match no resources produce a `SKIPPED:` result.

`ValidationResult.to_dict()` produces a JSON-serializable dict for the JSON and SARIF formatters.

### `extract_config.py`

`extract_terraform_config(path)` handles files and directories. Security checks: symlink resolution, 10 MB size limit. Returns `{"resources": [...]}`.

### `rule_packs.py`

`RulePackManager` searches for pack files in:
1. `<package root>/../../rule_packs/` (dev install)
2. `~/.riveter/rule_packs/` (user override)
3. `/opt/homebrew/share/riveter/rule_packs/` (Homebrew, Apple Silicon)
4. `/usr/local/share/riveter/rule_packs/` (Homebrew, Intel/Linux)

Extra dirs can be added via the `extra_dirs` constructor arg or `config.rule_dirs`.

### `config.py`

`RiveterConfig` dataclass. `ConfigManager.load_config()` merges defaults → file → CLI overrides. File is auto-discovered by checking a list of well-known filenames in the CWD.

### `formatters.py`

Three formatter classes extending `OutputFormatter(ABC)`: `JSONFormatter`, `JUnitXMLFormatter`, `SARIFFormatter`. The table format is rendered directly in `cli.py` using Rich.

### `cli.py`

Click group with two commands: `scan` and `list-rule-packs`. Orchestrates all the other modules. Exits with code 1 on any check failure.

---

## Adding a New Rule Pack

1. Create `rule_packs/<my-pack>.yml` following the format in the [User Guide](user-guide.md#custom-rules).
2. Add a smoke test in `tests/test_rule_packs.py`:

   ```python
   def test_my_pack_loads(self):
       mgr = RulePackManager()
       pack = mgr.load_rule_pack("my-pack")
       assert len(pack.rules) > 0
   ```

3. Add the pack to the table in `README.md` and `docs/user-guide.md`.

---

## Adding a New Operator

1. In `operators.py`, add a class extending `ComparisonOperator` with `evaluate()` and `get_error_message()`.
2. Register it in `OperatorFactory.create_operator()`.
3. Add the operator name to `_VALID_OPERATORS` in `rules.py`.
4. Write tests in `tests/test_operators.py`.
5. Document the operator in `README.md` and `docs/user-guide.md`.

---

## Testing

```bash
make test        # Full suite with coverage
make test-fast   # No coverage (faster iteration)
```

Tests use `tmp_path` pytest fixtures for temporary YAML files. No real Terraform or cloud credentials required.

Coverage threshold: **60%** (enforced by `--cov-fail-under`).

---

## Building Binaries

```bash
# Install dev dependencies (includes PyInstaller)
make install-dev

# Build
make build
# Binary output: dist/riveter
```

The release workflow builds for:
- `macos-14` → macOS arm64
- `macos-13` → macOS Intel
- `ubuntu-latest` → Linux x86_64

---

## Release Process

Releases are fully automated via `.github/workflows/release.yml`. See [CONTRIBUTING.md](../CONTRIBUTING.md#release-process) for details.

**Required secret:** `HOMEBREW_TAP_TOKEN` — PAT with write access to `ScottRyanHoward/homebrew-riveter`.

---

## Dependency Philosophy

Runtime dependencies are kept minimal and strictly bounded:

| Package | Purpose |
|---------|---------|
| `pyyaml` | Parse YAML rule files and config files |
| `click` | CLI framework |
| `rich` | Terminal table output and color |
| `python-hcl2` | Parse Terraform HCL |

No `cryptography`, no `requests`, no network calls at runtime. Riveter is a local static analysis tool.
