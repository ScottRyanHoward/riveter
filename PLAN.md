# AI-Powered Violation Explanations — Implementation Plan

## Overview
Add optional `--explain` flag to `riveter scan` and a `riveter explain` subcommand. Uses the Anthropic API to generate plain-English explanations of rule violations. Fully opt-in — no API key means no change to existing behaviour.

---

## Files to Create
1. `src/riveter/explainer.py` — Explainer class
2. `tests/test_explainer.py` — 5 unit tests

## Files to Modify
3. `src/riveter/scanner.py` — add `explanation` field to ValidationResult
4. `src/riveter/config.py` — add AI config fields, handle nested `ai:` YAML block
5. `src/riveter/cli.py` — add `--explain` to scan, add `riveter explain` subcommand, add `_fetch_explanations` helper, update `_display_table`
6. `src/riveter/formatters.py` — update JUnit and SARIF to include explanation (JSON flows automatically via to_dict)
7. `pyproject.toml` — add `anthropic` optional dep, add mypy override
8. `README.md` — add AI section after Output Formats

---

## Step-by-Step Changes

### 1. `src/riveter/scanner.py`
- Add `explanation: Optional[str] = None` as an instance attribute in `__init__` (not a constructor param — set after construction by the CLI)
- Add `"explanation": self.explanation` to `to_dict()` — this automatically flows into JSONFormatter since it calls `r.to_dict()`
- Add `from typing import Optional` (already imported as List, Any, Dict — extend it)

### 2. `src/riveter/config.py`
- Add two new fields to `RiveterConfig` dataclass:
  ```python
  ai_explain_on_fail: bool = False
  ai_model: str = "claude-sonnet-4-20250514"
  ```
- Update `from_dict()` to flatten the nested `ai:` block before field filtering:
  ```python
  ai_block = data.pop("ai", None)  # work on a copy
  if isinstance(ai_block, dict):
      if "explain_on_fail" in ai_block:
          data["ai_explain_on_fail"] = ai_block["explain_on_fail"]
      if "model" in ai_block:
          data["ai_model"] = ai_block["model"]
  ```
- Update `to_dict()` to include the new fields
- Update `_merge_with_overrides()` for the new scalar fields:
  ```python
  merged.ai_explain_on_fail = overrides.ai_explain_on_fail or self.ai_explain_on_fail
  merged.ai_model = (
      overrides.ai_model if overrides.ai_model != defaults.ai_model else self.ai_model
  )
  ```

### 3. `src/riveter/explainer.py` (new file)
```
Key design points:
- __init__ checks ANTHROPIC_API_KEY, lazy-imports anthropic only if key present
- is_available() -> bool
- explain(rule, resource_name, resource_type, resource_attrs, failed_assertions) -> Optional[str]
- warn_fn callback for "warn once" pattern — CLI passes lambda msg: console.print(msg)
- _warned: set[str] to track which warning types have already fired
- _warn_once(key, msg) helper
- Uses model stored at init time (passed from config.ai_model)
- max_tokens=300
- Catches all exceptions, returns None, never raises
- Truncates resource_attrs YAML to 600 chars to stay under 500 input tokens
```

Prompt template sent to Claude:
```
You are a Terraform security expert. Explain this rule violation in 3-4 sentences.

Rule ID: {rule_id}
Description: {description}
Severity: {severity}
Failed assertion: {failed_assertion}

Resource type: {resource_type}
Resource name: {resource_name}
Attributes:
{attrs_yaml}

Explain: (1) why this is a security risk, (2) what an attacker could do, (3) the exact Terraform change to fix it. Be concise and specific.
```

Error handling — catch and _warn_once for:
- `anthropic.AuthenticationError` → key "auth" → "✗ Anthropic API key is invalid or expired. Check your key at console.anthropic.com"
- `anthropic.RateLimitError` → key "rate" → "✗ Anthropic rate limit hit. Explanations skipped for this scan."
- `anthropic.APITimeoutError` / network errors → key "timeout" → "✗ Could not reach Anthropic API. Scan results shown without explanations."
- Any other Exception → return None silently

### 4. `src/riveter/cli.py`

#### `_fetch_explanations` helper (new function, near top with other helpers):
```python
def _fetch_explanations(
    explainer: "Explainer",
    results: List[ValidationResult],
    model: str,
) -> None:
    """Fetch AI explanations in parallel for failing results (mutates results in-place)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    failures = [
        r for r in results
        if not r.passed and not r.message.startswith("SKIPPED:")
    ]
    if not failures:
        return
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_result = {
            executor.submit(
                explainer.explain,
                rule={"id": r.rule.id, "description": r.rule.description, "severity": r.rule.severity.value},
                resource_name=r.resource.get("id", ""),
                resource_type=r.resource.get("resource_type", ""),
                resource_attrs=r.resource,
                failed_assertions=[ar for ar in r.assertion_results if not ar.passed],
            ): r
            for r in failures
        }
        for future in as_completed(future_to_result):
            result = future_to_result[future]
            result.explanation = future.result()
```

#### `_display_table` update:
After `table.add_row(status, sev, r.rule.id, resource, r.message)`, if the result has an explanation, add a continuation row:
```python
if not r.passed and not r.message.startswith("SKIPPED:") and getattr(r, "explanation", None):
    table.add_row("", "", "", "", f"[dim]ⓘ  {r.explanation}[/dim]")
```

#### Missing API key warning (new helper `_print_no_key_warning`):
```python
def _print_no_key_warning() -> None:
    console.print()
    console.print("⚠  AI explanations require an Anthropic API key.")
    console.print()
    console.print("   Set it with:")
    console.print("       export ANTHROPIC_API_KEY=sk-ant-...")
    console.print()
    console.print("   Get a key at: https://console.anthropic.com")
    console.print("   Cost: ~$0.001 per explanation.")
    console.print()
    console.print("   Scan results are shown below without explanations.")
    console.print()
```

#### `scan` command changes:
- Add `--explain / -e` boolean flag (is_flag=True)
- Add `explain` param to function signature
- After `results = validate_resources(...)`, add:
  ```python
  effective_explain = explain or config.ai_explain_on_fail
  if effective_explain:
      from .explainer import Explainer
      exp = Explainer(
          model=config.ai_model,
          warn_fn=lambda msg: console.print(msg),
      )
      if not exp.is_available():
          _print_no_key_warning()
      else:
          _fetch_explanations(exp, results, config.ai_model)
  ```
- Do NOT add explain to cli_overrides (it's a boolean flag, handled separately from config merge)

#### `riveter explain` subcommand (new, insert between scan-state and list-rule-packs):
```
riveter explain <rule-id> --resource <resource_type.resource_name> --terraform <path>
Options (same pattern as scan): --rules, --rule-pack, --config
```
Logic:
1. Load rules same as scan
2. Find rule by ID — if not found: print "Rule 'X' not found. Run 'riveter list-rule-packs'..." and exit 1
3. Parse terraform path with extract_terraform_config
4. Parse --resource as "resource_type.resource_name" (split on first ".")
5. Find matching resource — if not found: print "Resource 'X' not found in <path>." and exit 1
6. Check explainer availability — if not available: print no-key warning and exit 1
7. Call explainer.explain(), print result or "No explanation available."

### 5. `src/riveter/formatters.py`

#### JSONFormatter — no changes needed (explanation flows via to_dict())

#### JUnitXMLFormatter — update failure message:
```python
# current:
failure.set("message", result.message)
# new:
msg = result.message
if getattr(result, "explanation", None):
    msg = f"{msg}\n\nExplanation: {result.explanation}"
failure.set("message", msg)
```

Also update `failure.text` to append explanation after the assertion details.

#### SARIFFormatter — update message.text in _sarif_results:
```python
# current:
"message": {"text": r.message},
# new:
msg = r.message
if getattr(result, "explanation", None):
    msg = f"{r.message}\n\nExplanation: {r.explanation}"
"message": {"text": msg},
```

### 6. `pyproject.toml`
- Add `ai` optional dep group:
  ```toml
  [project.optional-dependencies]
  ai = ["anthropic>=0.40.0"]
  ```
- Add mypy override:
  ```toml
  [[tool.mypy.overrides]]
  module = "anthropic"
  ignore_missing_imports = true
  ```
- Also add mypy override for explainer.py since it uses dynamic imports:
  ```toml
  [[tool.mypy.overrides]]
  module = "riveter.explainer"
  disable_error_code = ["misc"]
  ```

### 7. `README.md`
Add after the `## Output Formats` section and before `## Config File`:
```markdown
## AI-Powered Explanations (Optional)

Riveter can explain violations in plain English — why a rule matters, what
the risk is, and exactly how to fix it in your config.

This feature requires an Anthropic API key (pay-as-you-go, ~$0.001 per
explanation). Get one at https://console.anthropic.com.

Once you have a key:

    export ANTHROPIC_API_KEY=sk-ant-...

Then add `--explain` to any scan:

    riveter scan -p aws-security -t main.tf --explain

Or drill into a specific violation after the fact:

    riveter explain ec2-imdsv2-required --resource aws_instance.web_server --terraform main.tf

To always enable explanations, add this to `riveter.yml`:

    # ai:
    #   explain_on_fail: true
```

### 8. `tests/test_explainer.py` (new file)
5 tests as specified, all mocking the Anthropic client:

- `test_is_available_returns_false_without_env_var` — unset ANTHROPIC_API_KEY, assert is_available() is False
- `test_explain_returns_none_on_api_error` — monkeypatch ANTHROPIC_API_KEY, mock anthropic.Anthropic to raise Exception, assert explain() returns None
- `test_prompt_contains_rule_id` — capture prompt passed to mock client, assert rule_id in prompt
- `test_prompt_contains_resource_name` — assert resource_name in prompt
- `test_prompt_contains_failed_assertion` — assert failed assertion property path in prompt

---

## Key Design Decisions

1. **`explanation` not in constructor** — Set as `result.explanation = value` after construction. This avoids changing `validate_resources()` signature and keeps scanner.py clean.

2. **Config flattening** — The nested `ai:` YAML block is flattened to `ai_explain_on_fail` / `ai_model` scalar fields in `from_dict()`. This follows the existing pattern (no nested dataclasses).

3. **`warn_fn` callback** — Explainer takes an optional callable so CLI controls display (Rich) while explainer.py stays Rich-free. "Warn once" is enforced via `_warned: set[str]` on the Explainer instance.

4. **`--explain` vs config** — The CLI `--explain` flag is handled separately from `cli_overrides` (not merged into config). `effective_explain = explain or config.ai_explain_on_fail` combines both.

5. **Lazy import** — `from .explainer import Explainer` is inside the if-block in scan, so the anthropic package is never touched unless `--explain` is active. explainer.py itself also lazy-imports anthropic.

6. **`riveter init` does not exist** — skip requirement 10.

7. **mypy** — Add `ignore_missing_imports = true` override for `anthropic` module. Use `Any` type for the client object in explainer.py since we can't import anthropic types at module level.

---

## Order of Implementation

1. scanner.py — add explanation field (foundational, everything depends on it)
2. config.py — add AI config fields
3. explainer.py — new module
4. cli.py — add --explain, _fetch_explanations, _print_no_key_warning, riveter explain
5. formatters.py — update JUnit and SARIF
6. pyproject.toml — add dep + mypy overrides
7. README.md — add AI section
8. tests/test_explainer.py — new tests
9. Run tests + linters, fix any issues
