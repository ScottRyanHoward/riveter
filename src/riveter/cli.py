# Copyright (c) 2026 Scott Howard
# SPDX-License-Identifier: MIT

"""Riveter CLI entry point.

Commands:
    riveter scan             Validate Terraform files against rules.
    riveter scan-state       Validate a Terraform state file (drift detection).
    riveter explain          AI-powered explanation of a single rule violation.
    riveter generate-rules   AI-powered rule generation from Terraform files.
    riveter list-rule-packs  List all available built-in rule packs.
"""

import fnmatch
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import click
import yaml
from rich import box
from rich.console import Console
from rich.table import Table

from ._version import get_version
from .config import ConfigManager
from .explainer import Explainer
from .extract_config import extract_terraform_config
from .extract_state import extract_terraform_state
from .formatters import HTMLFormatter, JSONFormatter, JUnitXMLFormatter, SARIFFormatter
from .generator import RuleGenerator
from .rule_packs import RulePackManager
from .rules import Rule, load_rules
from .scanner import ValidationResult, validate_resources

console = Console()
err_console = Console(stderr=True)


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _filter_by_pattern(
    rules: List[Rule],
    include: List[str],
    exclude: List[str],
) -> List[Rule]:
    """Filter rules by glob patterns applied to rule IDs."""
    if include:
        rules = [r for r in rules if any(fnmatch.fnmatch(r.id, p) for p in include)]
    if exclude:
        rules = [r for r in rules if not any(fnmatch.fnmatch(r.id, p) for p in exclude)]
    return rules


def _display_table(results: List[ValidationResult]) -> None:
    """Render results as a Rich table."""
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold", expand=False)
    table.add_column("Status", width=6, justify="center")
    table.add_column("Rule ID", min_width=24)
    table.add_column("Resource", min_width=24)
    table.add_column("Message")

    for r in results:
        if r.message.startswith("SKIPPED:"):
            status = "[dim]SKIP[/dim]"
        elif r.passed:
            status = "[green]PASS[/green]"
        else:
            status = "[bold red]FAIL[/bold red]"

        resource = f"{r.resource.get('resource_type', '')}.{r.resource.get('id', '')}"

        msg = r.message
        if r.explanation:
            msg = f"{r.message}\n  [dim]\u24d8[/dim]  [dim]{r.explanation}[/dim]"

        table.add_row(status, r.rule.id, resource, msg)

    console.print(table)


def _print_summary(results: List[ValidationResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and not r.message.startswith("SKIPPED:"))
    skipped = sum(1 for r in results if r.message.startswith("SKIPPED:"))

    console.print()
    console.print(f"  [green]Passed:[/green]  {passed}")
    console.print(f"  [red]Failed:[/red]  {failed}")
    if skipped:
        console.print(f"  [dim]Skipped:[/dim] {skipped} (no matching resources found)")
    console.print()

    if failed == 0:
        console.print("[bold green]All checks passed.[/bold green]")
    else:
        console.print(f"[bold red]{failed} check(s) failed.[/bold red]")


# ---------------------------------------------------------------------------
# AI explanation helpers
# ---------------------------------------------------------------------------

_AI_MISSING_WARNING = """\
\u26a0  AI explanations require an Anthropic API key.
   Set it with:
       export ANTHROPIC_API_KEY=sk-ant-...
   Get a key at: https://console.anthropic.com
   Cost: ~$0.001 per explanation.
   Scan results are shown below without explanations."""


def _attach_explanations(results: List[ValidationResult], model: Optional[str] = None) -> None:
    """Fetch AI explanations in parallel and attach them to failing results."""
    explainer = Explainer(model=model)

    if not explainer.is_available():
        err_console.print(_AI_MISSING_WARNING)
        return

    failing = [r for r in results if not r.passed and not r.message.startswith("SKIPPED:")]
    if not failing:
        return

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                explainer.explain,
                {
                    "id": r.rule.id,
                    "description": r.rule.description,
                    "assert": r.rule.assert_conditions,
                },
                r.resource.get("id", ""),
                r.resource.get("resource_type", ""),
                r.resource,
            ): r
            for r in failing
        }
        for future in as_completed(futures):
            result = futures[future]
            try:
                result.explanation = future.result()
            except Exception:  # noqa: BLE001
                pass

    warning = explainer.get_scan_warning()
    if warning:
        err_console.print(warning)


# ---------------------------------------------------------------------------
# CLI definition
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=get_version(), prog_name="riveter")
def main() -> None:
    """Riveter — Infrastructure Rule Enforcement as Code.

    Validate Terraform configurations against custom rules and pre-built
    compliance rule packs for AWS, Azure, GCP, Kubernetes, and SOC2.

    \b
    Quick start:
      riveter scan -p aws-security -t ./infra/
      riveter scan-state -p aws-security -s terraform.tfstate
      riveter list-rule-packs

    \b
    Built-in rule packs (15 total):
      AWS:    aws-security, aws-well-architected, aws-hipaa, aws-pci-dss, cis-aws
      Azure:  azure-security, azure-well-architected, azure-hipaa, cis-azure
      GCP:    gcp-security, gcp-well-architected, cis-gcp
      Other:  kubernetes-security, multi-cloud-security, soc2-security

    \b
    Output formats:
      table (default)  Rich terminal table with color-coded results
      json             Structured JSON for scripting and pipelines
      junit            JUnit XML for CI/CD systems (GitHub Actions, Jenkins)
      sarif            SARIF for GitHub Code Scanning
      html             Self-contained HTML report with interactive filtering

    \b
    Config file (auto-detected in working directory):
      riveter.yml / .riveter.yml / riveter.yaml / .riveter.yaml
      riveter.json / .riveter.json
      Override with: --config FILE

    \b
    Environment variables:
      ANTHROPIC_API_KEY    Required to use --explain or the explain command

    \b
    Exit codes:
      0    All checks passed
      1    One or more checks failed

    Run 'riveter COMMAND --help' for details on a specific command.
    """


@main.command()
@click.option(
    "--rules",
    "-r",
    "rules_file",
    type=click.Path(exists=True),
    help="Path to a custom rules YAML file.",
)
@click.option(
    "--rule-pack",
    "-p",
    "rule_packs",
    multiple=True,
    help="Built-in rule pack to use (can be repeated). Example: -p aws-security -p cis-aws",
)
@click.option(
    "--terraform",
    "-t",
    "terraform_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to a Terraform .tf file or directory of .tf files.",
)
@click.option(
    "--output-format",
    "-f",
    type=click.Choice(["table", "json", "junit", "sarif", "html"], case_sensitive=False),
    default=None,
    help="Output format. Defaults to 'table'. Use 'html' for a shareable report.",
)
@click.option(
    "--config",
    "-c",
    "config_file",
    type=click.Path(exists=True),
    help="Path to a Riveter config file (YAML or JSON). Auto-detected if not specified.",
)
@click.option(
    "--include-rules",
    multiple=True,
    metavar="PATTERN",
    help="Only run rules whose ID matches this glob pattern (can be repeated).",
)
@click.option(
    "--exclude-rules",
    multiple=True,
    metavar="PATTERN",
    help="Skip rules whose ID matches this glob pattern (can be repeated).",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    default=None,
    help="Write output to this file (e.g. report.html). The table summary is still shown in the terminal.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging.",
)
@click.option(
    "--explain",
    "-e",
    is_flag=True,
    default=False,
    help="Attach AI-generated plain-English explanations to each violation (requires ANTHROPIC_API_KEY).",
)
def scan(
    rules_file: Optional[str],
    rule_packs: Tuple[str, ...],
    terraform_path: str,
    output_format: Optional[str],
    output_file: Optional[str],
    config_file: Optional[str],
    include_rules: Tuple[str, ...],
    exclude_rules: Tuple[str, ...],
    debug: bool,
    explain: bool,
) -> None:
    """Validate Terraform configuration against rules.

    \b
    Examples:
      # Scan with a custom rules file
      riveter scan -r rules.yml -t main.tf

      # Scan with a built-in rule pack
      riveter scan -p aws-security -t main.tf

      # Combine multiple rule packs
      riveter scan -p aws-security -p cis-aws -t main.tf

      # Scan an entire directory of .tf files
      riveter scan -p aws-security -t ./infra/

      # Output as JSON (piped to a file)
      riveter scan -p aws-security -t main.tf -f json > results.json

      # JUnit XML for CI/CD
      riveter scan -p aws-security -t main.tf -f junit > results.xml

      # Include/exclude rules by ID glob pattern
      riveter scan -p aws-security -t main.tf --include-rules "*s3*"
    """
    _setup_logging(debug)

    # -- Resolve configuration ------------------------------------------------
    cli_overrides: Dict[str, Any] = {}
    if output_format:
        cli_overrides["output_format"] = output_format
    if include_rules:
        cli_overrides["include_rules"] = list(include_rules)
    if exclude_rules:
        cli_overrides["exclude_rules"] = list(exclude_rules)
    if rule_packs:
        cli_overrides["rule_packs"] = list(rule_packs)
    if debug:
        cli_overrides["debug"] = True

    try:
        mgr = ConfigManager()
        config = mgr.load_config(config_file=config_file, cli_overrides=cli_overrides)
        errors = mgr.validate(config)
        if errors:
            for e in errors:
                err_console.print(f"[red]Config error:[/red] {e}")
            sys.exit(1)
    except Exception as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)

    # -- Validate that we have at least one rule source -----------------------
    has_rules_file = bool(rules_file)
    has_packs = bool(config.rule_packs)
    if not has_rules_file and not has_packs:
        err_console.print(
            "[red]Error:[/red] Specify at least one rule source: "
            "--rules <file> or --rule-pack <name>"
        )
        sys.exit(1)

    # -- Load rules -----------------------------------------------------------
    all_rules: List[Rule] = []

    if rules_file:
        try:
            loaded = load_rules(rules_file)
            all_rules.extend(loaded)
            err_console.print(
                f"Loaded [bold]{len(loaded)}[/bold] rule(s) from [cyan]{rules_file}[/cyan]"
            )
        except Exception as exc:
            err_console.print(f"[red]Error loading rules file:[/red] {exc}")
            sys.exit(1)

    if config.rule_packs:
        pack_mgr = RulePackManager(extra_dirs=config.rule_dirs or None)
        for pack_name in config.rule_packs:
            try:
                pack = pack_mgr.load_rule_pack(pack_name)
                all_rules.extend(pack.rules)
                err_console.print(
                    f"Loaded [bold]{len(pack.rules)}[/bold] rule(s) from pack "
                    f"[cyan]{pack_name}[/cyan]"
                )
            except FileNotFoundError:
                err_console.print(
                    f"[red]Error:[/red] Rule pack '{pack_name}' not found. "
                    "Run 'riveter list-rule-packs' to see available packs."
                )
                sys.exit(1)
            except Exception as exc:
                err_console.print(f"[red]Error loading rule pack '{pack_name}':[/red] {exc}")
                sys.exit(1)

    if not all_rules:
        err_console.print("[red]Error:[/red] No rules were loaded.")
        sys.exit(1)

    # -- Apply include/exclude filters ----------------------------------------
    if config.include_rules or config.exclude_rules:
        all_rules = _filter_by_pattern(all_rules, config.include_rules, config.exclude_rules)
        if not all_rules:
            err_console.print("[yellow]Warning:[/yellow] No rules remain after filtering.")
            sys.exit(0)

    # -- Parse Terraform -------------------------------------------------------
    try:
        tf_config = extract_terraform_config(terraform_path)
    except Exception as exc:
        err_console.print(f"[red]Error parsing Terraform:[/red] {exc}")
        sys.exit(1)

    resources = tf_config.get("resources", [])
    if not resources:
        err_console.print(
            "[yellow]Warning:[/yellow] No resources found in the Terraform configuration."
        )
        sys.exit(0)

    err_console.print(
        f"\nScanning [bold]{len(resources)}[/bold] resource(s) against "
        f"[bold]{len(all_rules)}[/bold] rule(s)...\n"
    )

    # -- Run validation -------------------------------------------------------
    results = validate_resources(all_rules, resources)

    # -- AI explanations (optional) -------------------------------------------
    effective_explain = explain or config.ai_explain_on_fail
    if effective_explain:
        _attach_explanations(results, config.ai_model)

    # -- Emit output ----------------------------------------------------------
    fmt = config.output_format
    formatter_map = {
        "json": JSONFormatter(),
        "junit": JUnitXMLFormatter(),
        "sarif": SARIFFormatter(),
        "html": HTMLFormatter(),
    }
    if fmt in formatter_map:
        rendered = formatter_map[fmt].format(results)
        if output_file:
            with open(output_file, "w", encoding="utf-8") as fh:
                fh.write(rendered)
            err_console.print(f"[green]Report saved to[/green] {output_file}")
            _display_table(results)
            _print_summary(results)
        else:
            click.echo(rendered)
    else:
        _display_table(results)
        _print_summary(results)

    # -- Exit code: non-zero on any failures ----------------------------------
    failed = sum(1 for r in results if not r.passed and not r.message.startswith("SKIPPED:"))
    if failed:
        sys.exit(1)


@main.command(name="scan-state")
@click.option(
    "--state",
    "-s",
    required=True,
    help=(
        "Path to a Terraform state file (terraform.tfstate), "
        "or '-' to read from stdin (e.g. piped from 'terraform state pull')."
    ),
)
@click.option(
    "--rules",
    "-r",
    "rules_file",
    type=click.Path(exists=True),
    help="Path to a custom rules YAML file.",
)
@click.option(
    "--rule-pack",
    "-p",
    "rule_packs",
    multiple=True,
    help="Built-in rule pack to use (can be repeated). Example: -p aws-security -p cis-aws",
)
@click.option(
    "--output-format",
    "-f",
    type=click.Choice(["table", "json", "junit", "sarif", "html"], case_sensitive=False),
    default=None,
    help="Output format. Defaults to 'table'. Use 'html' for a shareable report.",
)
@click.option(
    "--config",
    "-c",
    "config_file",
    type=click.Path(exists=True),
    help="Path to a Riveter config file (YAML or JSON). Auto-detected if not specified.",
)
@click.option(
    "--include-rules",
    multiple=True,
    metavar="PATTERN",
    help="Only run rules whose ID matches this glob pattern (can be repeated).",
)
@click.option(
    "--exclude-rules",
    multiple=True,
    metavar="PATTERN",
    help="Skip rules whose ID matches this glob pattern (can be repeated).",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    default=None,
    help="Write output to this file (e.g. report.html). The table summary is still shown in the terminal.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging.",
)
def scan_state(
    state: str,
    rules_file: Optional[str],
    rule_packs: Tuple[str, ...],
    output_format: Optional[str],
    output_file: Optional[str],
    config_file: Optional[str],
    include_rules: Tuple[str, ...],
    exclude_rules: Tuple[str, ...],
    debug: bool,
) -> None:
    """Validate a Terraform state file against rules (drift detection).

    \b
    Examples:
      # Scan a local state file
      riveter scan-state -r rules.yml -s terraform.tfstate

      # Use a built-in rule pack
      riveter scan-state -p aws-security -s terraform.tfstate

      # Pipe remote state from any Terraform backend
      terraform state pull | riveter scan-state -p aws-security -s -

      # Generate an HTML report
      riveter scan-state -p aws-security -s terraform.tfstate -f html -o report.html

      # Side-by-side drift detection
      riveter scan       -p aws-security -t main.tf           -f json > hcl.json
      riveter scan-state -p aws-security -s terraform.tfstate -f json > state.json
    """
    _setup_logging(debug)

    # -- Resolve configuration ------------------------------------------------
    cli_overrides: Dict[str, Any] = {}
    if output_format:
        cli_overrides["output_format"] = output_format
    if include_rules:
        cli_overrides["include_rules"] = list(include_rules)
    if exclude_rules:
        cli_overrides["exclude_rules"] = list(exclude_rules)
    if rule_packs:
        cli_overrides["rule_packs"] = list(rule_packs)
    if debug:
        cli_overrides["debug"] = True

    try:
        mgr = ConfigManager()
        config = mgr.load_config(config_file=config_file, cli_overrides=cli_overrides)
        errors = mgr.validate(config)
        if errors:
            for e in errors:
                err_console.print(f"[red]Config error:[/red] {e}")
            sys.exit(1)
    except Exception as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)

    # -- Validate that we have at least one rule source -----------------------
    has_rules_file = bool(rules_file)
    has_packs = bool(config.rule_packs)
    if not has_rules_file and not has_packs:
        err_console.print(
            "[red]Error:[/red] Specify at least one rule source: "
            "--rules <file> or --rule-pack <name>"
        )
        sys.exit(1)

    # -- Load rules -----------------------------------------------------------
    all_rules: List[Rule] = []

    if rules_file:
        try:
            loaded = load_rules(rules_file)
            all_rules.extend(loaded)
            err_console.print(
                f"Loaded [bold]{len(loaded)}[/bold] rule(s) from [cyan]{rules_file}[/cyan]"
            )
        except Exception as exc:
            err_console.print(f"[red]Error loading rules file:[/red] {exc}")
            sys.exit(1)

    if config.rule_packs:
        pack_mgr = RulePackManager(extra_dirs=config.rule_dirs or None)
        for pack_name in config.rule_packs:
            try:
                pack = pack_mgr.load_rule_pack(pack_name)
                all_rules.extend(pack.rules)
                err_console.print(
                    f"Loaded [bold]{len(pack.rules)}[/bold] rule(s) from pack "
                    f"[cyan]{pack_name}[/cyan]"
                )
            except FileNotFoundError:
                err_console.print(
                    f"[red]Error:[/red] Rule pack '{pack_name}' not found. "
                    "Run 'riveter list-rule-packs' to see available packs."
                )
                sys.exit(1)
            except Exception as exc:
                err_console.print(f"[red]Error loading rule pack '{pack_name}':[/red] {exc}")
                sys.exit(1)

    if not all_rules:
        err_console.print("[red]Error:[/red] No rules were loaded.")
        sys.exit(1)

    # -- Apply include/exclude filters ----------------------------------------
    if config.include_rules or config.exclude_rules:
        all_rules = _filter_by_pattern(all_rules, config.include_rules, config.exclude_rules)
        if not all_rules:
            err_console.print("[yellow]Warning:[/yellow] No rules remain after filtering.")
            sys.exit(0)

    # -- Parse state file -----------------------------------------------------
    source_label = "stdin" if state == "-" else state
    try:
        state_config = extract_terraform_state(state)
    except Exception as exc:
        err_console.print(f"[red]Error parsing state file:[/red] {exc}")
        sys.exit(1)

    resources = state_config.get("resources", [])
    if not resources:
        err_console.print(
            f"[yellow]Warning:[/yellow] No managed resources found in {source_label}."
        )
        sys.exit(0)

    err_console.print(
        f"\nScanning [bold]{len(resources)}[/bold] resource(s) from state against "
        f"[bold]{len(all_rules)}[/bold] rule(s)...\n"
    )

    # -- Run validation -------------------------------------------------------
    results = validate_resources(all_rules, resources)

    # -- Emit output ----------------------------------------------------------
    fmt = config.output_format
    formatter_map = {
        "json": JSONFormatter(),
        "junit": JUnitXMLFormatter(),
        "sarif": SARIFFormatter(),
        "html": HTMLFormatter(),
    }
    if fmt in formatter_map:
        rendered = formatter_map[fmt].format(results)
        if output_file:
            with open(output_file, "w", encoding="utf-8") as fh:
                fh.write(rendered)
            err_console.print(f"[green]Report saved to[/green] {output_file}")
            _display_table(results)
            _print_summary(results)
        else:
            click.echo(rendered)
    else:
        _display_table(results)
        _print_summary(results)

    # -- Exit code: non-zero on any failures ----------------------------------
    failed = sum(1 for r in results if not r.passed and not r.message.startswith("SKIPPED:"))
    if failed:
        sys.exit(1)


@main.command(name="explain")
@click.argument("rule_id")
@click.option(
    "--resource",
    "-r",
    required=True,
    metavar="TYPE.NAME",
    help="Resource address to explain (e.g. aws_instance.web_server).",
)
@click.option(
    "--terraform",
    "-t",
    "terraform_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to a Terraform .tf file or directory.",
)
@click.option(
    "--rules",
    "rules_file",
    type=click.Path(exists=True),
    help="Custom rules YAML file to search for the rule.",
)
@click.option(
    "--rule-pack",
    "-p",
    "rule_packs",
    multiple=True,
    help="Built-in rule pack to search (can be repeated).",
)
def explain_cmd(
    rule_id: str,
    resource: str,
    terraform_path: str,
    rules_file: Optional[str],
    rule_packs: Tuple[str, ...],
) -> None:
    """Explain a rule violation in plain English using AI.

    \b
    Examples:
      riveter explain ec2_no_public_ip \\
          --resource aws_instance.web_server --terraform main.tf -p aws-security

      riveter explain s3_bucket_public_access_block \\
          --resource aws_s3_bucket.uploads --terraform main.tf -r rules.yml
    """
    # -- Validate that there is at least one rule source ---------------------
    if not rules_file and not rule_packs:
        err_console.print(
            "[red]Error:[/red] Specify at least one rule source: "
            "--rules <file> or --rule-pack <name>"
        )
        sys.exit(1)

    # -- Load rules and find the target rule ---------------------------------
    all_rules: List[Rule] = []

    if rules_file:
        try:
            all_rules.extend(load_rules(rules_file))
        except Exception as exc:
            err_console.print(f"[red]Error loading rules file:[/red] {exc}")
            sys.exit(1)

    if rule_packs:
        pack_mgr = RulePackManager()
        for pack_name in rule_packs:
            try:
                pack = pack_mgr.load_rule_pack(pack_name)
                all_rules.extend(pack.rules)
            except FileNotFoundError:
                err_console.print(
                    f"[red]Error:[/red] Rule pack '{pack_name}' not found. "
                    "Run 'riveter list-rule-packs' to see available packs."
                )
                sys.exit(1)
            except Exception as exc:
                err_console.print(f"[red]Error loading rule pack '{pack_name}':[/red] {exc}")
                sys.exit(1)

    target_rule = next((r for r in all_rules if r.id == rule_id), None)
    if target_rule is None:
        err_console.print(
            f"[red]Error:[/red] Rule '{rule_id}' not found in the specified rule sources. "
            "Check the rule ID spelling or add the correct --rule-pack / --rules option."
        )
        sys.exit(1)

    # -- Parse Terraform and find the target resource ------------------------
    try:
        tf_config = extract_terraform_config(terraform_path)
    except Exception as exc:
        err_console.print(f"[red]Error parsing Terraform:[/red] {exc}")
        sys.exit(1)

    # Resource address may be "type.name" or just "name"
    if "." in resource:
        res_type, res_name = resource.split(".", 1)
    else:
        res_type, res_name = "", resource

    target_resource = None
    for res in tf_config.get("resources", []):
        name_match = res.get("id") == res_name
        type_match = not res_type or res.get("resource_type") == res_type
        if name_match and type_match:
            target_resource = res
            break

    if target_resource is None:
        err_console.print(
            f"[red]Error:[/red] Resource '{resource}' not found in '{terraform_path}'. "
            "Check the resource name and type, or verify the Terraform path."
        )
        sys.exit(1)

    # -- Check AI availability -----------------------------------------------
    explainer = Explainer()
    if not explainer.is_available():
        err_console.print(_AI_MISSING_WARNING)
        sys.exit(1)

    # -- Fetch and print explanation -----------------------------------------
    explanation = explainer.explain(
        rule={
            "id": target_rule.id,
            "description": target_rule.description,
            "assert": target_rule.assert_conditions,
        },
        resource_name=target_resource.get("id", ""),
        resource_type=target_resource.get("resource_type", ""),
        resource_attrs=target_resource,
    )

    if explanation is None:
        warning = explainer.get_scan_warning()
        if warning:
            err_console.print(warning)
        else:
            err_console.print("[red]Error:[/red] Failed to get explanation from Anthropic API.")
        sys.exit(1)

    console.print(explanation)


@main.command(name="list-rule-packs")
def list_rule_packs() -> None:
    """List all available built-in rule packs.

    \b
    Rule packs are searched in these directories (in order):
      1. <install>/rule_packs/        (development or pip install)
      2. ~/.riveter/rule_packs/       (user-local overrides)
      3. /opt/homebrew/share/riveter/rule_packs/   (Homebrew, Apple Silicon)
      4. /usr/local/share/riveter/rule_packs/       (Homebrew, Intel / Linux)
    """
    pack_mgr = RulePackManager()
    packs = pack_mgr.list_available_packs()

    if not packs:
        console.print("[yellow]No rule packs found.[/yellow]")
        console.print("\nSearched directories:")
        for d in pack_mgr.rule_pack_dirs:
            console.print(f"  [dim]{d}[/dim]")
        return

    table = Table(title="Available Rule Packs", box=box.ROUNDED, show_header=True)
    table.add_column("Name", style="cyan", min_width=28)
    table.add_column("Version", width=10)
    table.add_column("Rules", width=6, justify="right")
    table.add_column("Description")

    for pack in packs:
        table.add_row(
            str(pack["name"]),
            str(pack["version"]),
            str(pack["rule_count"]),
            str(pack["description"]),
        )

    console.print(table)


@main.command(name="generate-rules")
@click.option(
    "--terraform",
    "-t",
    "terraform_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to a Terraform .tf file or directory of .tf files.",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    default=None,
    help="Write generated rules to this file instead of stdout.",
)
@click.option(
    "--focus",
    default=None,
    metavar="TEXT",
    help=(
        "Optional guidance for the AI, e.g. 'PCI-DSS compliance', "
        "'cost optimization', or 'security hardening'."
    ),
)
@click.option(
    "--model",
    default=None,
    metavar="MODEL",
    help="Override the Claude model used for generation.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging.",
)
@click.option(
    "--config",
    "-c",
    "config_file",
    type=click.Path(exists=True),
    help="Path to a Riveter config file (YAML or JSON). Auto-detected if not specified.",
)
def generate_rules(
    terraform_path: str,
    output_file: Optional[str],
    focus: Optional[str],
    model: Optional[str],
    debug: bool,
    config_file: Optional[str],
) -> None:
    """Generate Riveter rules for your Terraform resources using AI.

    Parses Terraform files, groups resources by type, and asks Claude to
    suggest 3–5 enforceable rules per resource type.  The resulting YAML
    can be passed directly to 'riveter scan -r <file>'.

    Requires ANTHROPIC_API_KEY to be set in the environment.

    \b
    Examples:
      # Print generated rules to stdout
      riveter generate-rules -t main.tf

      # Save to a file and scan immediately
      riveter generate-rules -t ./infra/ -o my-rules.yml
      riveter scan -r my-rules.yml -t ./infra/

      # Focus on a specific compliance framework
      riveter generate-rules -t main.tf --focus "PCI-DSS compliance" -o pci-rules.yml
    """
    _setup_logging(debug)

    # -- Resolve configuration ------------------------------------------------
    cli_overrides: Dict[str, Any] = {}
    if debug:
        cli_overrides["debug"] = True

    try:
        mgr = ConfigManager()
        config = mgr.load_config(config_file=config_file, cli_overrides=cli_overrides)
    except Exception as exc:
        err_console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)

    # CLI --model flag takes precedence; fall back to config file ai.generate_model
    effective_model = model or config.ai_generate_model

    # -- Parse Terraform -------------------------------------------------------
    try:
        tf_config = extract_terraform_config(terraform_path)
    except Exception as exc:
        err_console.print(f"[red]Error parsing Terraform:[/red] {exc}")
        sys.exit(1)

    resources = tf_config.get("resources", [])
    if not resources:
        console.print("[yellow]Warning:[/yellow] No resources found in the Terraform path.")
        sys.exit(0)

    # -- Check AI availability -------------------------------------------------
    generator = RuleGenerator(model=effective_model)
    if not generator.is_available():
        err_console.print(
            "\u26a0  AI rule generation requires an Anthropic API key.\n"
            "   Set it with:\n"
            "       export ANTHROPIC_API_KEY=sk-ant-...\n"
            "   Get a key at: https://console.anthropic.com"
        )
        sys.exit(1)

    # -- Group resources by type -----------------------------------------------
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for res in resources:
        rt = res.get("resource_type", "unknown")
        by_type.setdefault(rt, []).append(res)

    resource_types = list(by_type.keys())
    console.print(
        f"\nGenerating rules for [bold]{len(resource_types)}[/bold] resource type(s) "
        f"across [bold]{len(resources)}[/bold] resource(s)...\n"
    )

    # -- Generate rules concurrently per resource type -------------------------
    all_rules: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                generator.generate_for_resource_type,
                rt,
                by_type[rt][0],  # use first instance as representative sample
                focus,
            ): rt
            for rt in resource_types
        }
        for future in as_completed(futures):
            rt = futures[future]
            try:
                rules = future.result()
                if rules:
                    all_rules.extend(rules)
                    console.print(f"  [green]\u2713[/green] {rt}: {len(rules)} rule(s) generated")
                else:
                    console.print(f"  [yellow]\u2013[/yellow] {rt}: no valid rules returned")
            except Exception:  # noqa: BLE001
                console.print(f"  [red]\u2717[/red] {rt}: generation failed")

    warning = generator.get_warning()
    if warning:
        err_console.print(warning)

    if not all_rules:
        err_console.print(
            "\n[red]No rules were generated.[/red] " "Try running with --debug for more details."
        )
        sys.exit(1)

    # -- Serialise to YAML -----------------------------------------------------
    header = (
        "# Generated by riveter generate-rules\n"
        "# Review and customize before use:\n"
        "#   riveter scan -r <this-file> -t <terraform-path>\n\n"
    )
    rules_yaml = yaml.dump({"rules": all_rules}, default_flow_style=False, sort_keys=False)
    output = header + rules_yaml

    if output_file:
        try:
            with open(output_file, "w") as fh:
                fh.write(output)
            console.print(
                f"\n[bold green]Generated {len(all_rules)} rule(s)[/bold green] "
                f"written to [bold]{output_file}[/bold]"
            )
        except OSError as exc:
            err_console.print(f"[red]Error writing output file:[/red] {exc}")
            sys.exit(1)
    else:
        console.print()
        click.echo(output)
