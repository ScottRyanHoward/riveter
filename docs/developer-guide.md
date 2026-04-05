# Riveter Developer Guide

This guide is for contributors and maintainers. It covers the architecture, code organization, and how to extend Riveter.

---

## Architecture Overview

```
User runs: riveter scan -p aws-security -t main.tf
           riveter scan-state -p aws-security -s terraform.tfstate

         cli.py                    (Click CLI, orchestration)
            │
            ├── config.py          (Load riveter.yml + CLI overrides)
            │
            ├── rule_packs.py      (Find & load rule pack YAML files)
            │       └── rules.py   (Parse individual rules, Severity enum)
            │               └── operators.py  (Comparison operators)
            │
            ├── extract_config.py  (Parse HCL → resource dicts via hcl2)     ← scan
            ├── extract_state.py   (Parse .tfstate JSON → resource dicts)    ← scan-state
            │
            ├── scanner.py         (Apply rules to resources → ValidationResults)
            │
            └── formatters.py      (Serialize results → JSON / JUnit / SARIF / HTML)
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
__version__ = "0.2.18"
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

### `extract_state.py`

`extract_terraform_state(path)` parses a `terraform.tfstate` JSON file (format v4+) into the same `{"resources": [...]}` shape as `extract_config.py`, so the scanner and formatters consume both without modification. Pass `path="-"` to read from stdin (enables piping from `terraform state pull`).

Only managed resources (`"mode": "managed"`) are included. Data sources are skipped. Each `count` / `for_each` instance produces a separate resource dict. The resource `id` encodes the full address including module prefix and instance index: e.g. `module.vpc.aws_instance.web[0]`.

Size limit: 50 MB (larger than the per-HCL-file limit because state files aggregate all resources in a workspace).

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

Four formatter classes extending `OutputFormatter(ABC)`: `JSONFormatter`, `JUnitXMLFormatter`, `SARIFFormatter`, `HTMLFormatter`. The table format is rendered directly in `cli.py` using Rich.

`HTMLFormatter` produces a fully self-contained HTML report with embedded CSS and JavaScript. It serialises all result data as a JSON constant inside a `<script>` tag, which the page's JS reads to power client-side filtering (status, severity, free-text search) and expandable assertion-detail rows. Python templating uses `__PLACEHOLDER__` string replacement rather than `str.format()` to avoid escaping every CSS/JS `{` and `}` brace.

#### Adding a new output formatter

1. Add a class extending `OutputFormatter` with a `format(results: List[ValidationResult]) -> str` method.
2. Add the format name to `click.Choice` in `cli.py` and wire up the new class in the format-dispatch block.
3. Add the format name to `_VALID_FORMATS` in `config.py`.
4. Write tests in `tests/test_formatters.py` following the existing pattern.
5. Document the format in `README.md` and `docs/user-guide.md`.

### `cli.py`

Click group with five commands: `scan`, `scan-state`, `explain`, `generate-rules`, and `list-rule-packs`. Orchestrates all the other modules. Exits with code 1 on any check failure.

`scan` and `scan-state` share the same pipeline — config loading, rule loading, filtering, validation, and output — differing only in the parsing step (`extract_config.py` vs `extract_state.py`). All helper functions (`_display_table`, `_print_summary`, `_filter_by_pattern`) are shared.

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
- `macos-14` → macOS Apple Silicon (arm64)
- `ubuntu-latest` → Linux x86_64

> **Note:** Intel Mac binaries are not published separately. Intel Mac users can run the Apple Silicon binary via Rosetta 2, which macOS installs automatically on first use.

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
