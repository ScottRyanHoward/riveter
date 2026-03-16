"""Riveter CLI entry point.

Commands:
    riveter scan             Validate Terraform files against rules.
    riveter list-rule-packs  List all available built-in rule packs.
"""

import fnmatch
import logging
import sys
from typing import Any, Dict, List, Optional, Tuple

import click
from rich import box
from rich.console import Console
from rich.table import Table

from ._version import get_version
from .config import ConfigManager
from .extract_config import extract_terraform_config
from .extract_state import extract_terraform_state
from .formatters import HTMLFormatter, JSONFormatter, JUnitXMLFormatter, SARIFFormatter
from .rule_packs import RulePackManager
from .rules import Rule, Severity, load_rules
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
    table.add_column("Severity", width=9)
    table.add_column("Rule ID", min_width=24)
    table.add_column("Resource", min_width=24)
    table.add_column("Message")

    sev_colors = {"error": "red", "warning": "yellow", "info": "blue"}

    for r in results:
        if r.message.startswith("SKIPPED:"):
            status = "[dim]SKIP[/dim]"
        elif r.passed:
            status = "[green]PASS[/green]"
        else:
            status = "[bold red]FAIL[/bold red]"

        color = sev_colors.get(r.severity.value, "white")
        sev = f"[{color}]{r.severity.value}[/{color}]"
        resource = f"{r.resource.get('resource_type', '')}.{r.resource.get('id', '')}"

        table.add_row(status, sev, r.rule.id, resource, r.message)

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
# CLI definition
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=get_version(), prog_name="riveter")
def main() -> None:
    """Riveter — Infrastructure Rule Enforcement as Code.

    Validate Terraform configurations against custom rules and pre-built
    compliance rule packs for AWS, Azure, GCP, and Kubernetes.

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
    "--min-severity",
    type=click.Choice(["info", "warning", "error"], case_sensitive=False),
    default=None,
    help="Minimum severity to report. Checks below this level are skipped.",
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
    "--debug",
    is_flag=True,
    help="Enable debug logging.",
)
def scan(
    rules_file: Optional[str],
    rule_packs: Tuple[str, ...],
    terraform_path: str,
    output_format: Optional[str],
    config_file: Optional[str],
    min_severity: Optional[str],
    include_rules: Tuple[str, ...],
    exclude_rules: Tuple[str, ...],
    debug: bool,
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

      # Only surface errors (skip warnings and info)
      riveter scan -p aws-security -t main.tf --min-severity error

      # Include/exclude rules by ID glob pattern
      riveter scan -p aws-security -t main.tf --include-rules "*s3*"
    """
    _setup_logging(debug)

    # -- Resolve configuration ------------------------------------------------
    cli_overrides: Dict[str, Any] = {}
    if output_format:
        cli_overrides["output_format"] = output_format
    if min_severity:
        cli_overrides["min_severity"] = min_severity
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
            console.print(
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
                console.print(
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
            console.print("[yellow]Warning:[/yellow] No rules remain after filtering.")
            sys.exit(0)

    # -- Parse Terraform -------------------------------------------------------
    try:
        tf_config = extract_terraform_config(terraform_path)
    except Exception as exc:
        err_console.print(f"[red]Error parsing Terraform:[/red] {exc}")
        sys.exit(1)

    resources = tf_config.get("resources", [])
    if not resources:
        console.print(
            "[yellow]Warning:[/yellow] No resources found in the Terraform configuration."
        )
        sys.exit(0)

    console.print(
        f"\nScanning [bold]{len(resources)}[/bold] resource(s) against "
        f"[bold]{len(all_rules)}[/bold] rule(s)...\n"
    )

    # -- Run validation -------------------------------------------------------
    results = validate_resources(all_rules, resources, Severity(config.min_severity))

    # -- Emit output ----------------------------------------------------------
    fmt = config.output_format
    if fmt == "json":
        click.echo(JSONFormatter().format(results))
    elif fmt == "junit":
        click.echo(JUnitXMLFormatter().format(results))
    elif fmt == "sarif":
        click.echo(SARIFFormatter().format(results))
    elif fmt == "html":
        click.echo(HTMLFormatter().format(results))
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
    "--min-severity",
    type=click.Choice(["info", "warning", "error"], case_sensitive=False),
    default=None,
    help="Minimum severity to report. Checks below this level are skipped.",
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
    "--debug",
    is_flag=True,
    help="Enable debug logging.",
)
def scan_state(
    state: str,
    rules_file: Optional[str],
    rule_packs: Tuple[str, ...],
    output_format: Optional[str],
    config_file: Optional[str],
    min_severity: Optional[str],
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
      riveter scan-state -p aws-security -s terraform.tfstate -f html > report.html

      # Side-by-side drift detection
      riveter scan       -p aws-security -t main.tf           -f json > hcl.json
      riveter scan-state -p aws-security -s terraform.tfstate -f json > state.json
    """
    _setup_logging(debug)

    # -- Resolve configuration ------------------------------------------------
    cli_overrides: Dict[str, Any] = {}
    if output_format:
        cli_overrides["output_format"] = output_format
    if min_severity:
        cli_overrides["min_severity"] = min_severity
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
            console.print(
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
                console.print(
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
            console.print("[yellow]Warning:[/yellow] No rules remain after filtering.")
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
        console.print(
            f"[yellow]Warning:[/yellow] No managed resources found in {source_label}."
        )
        sys.exit(0)

    console.print(
        f"\nScanning [bold]{len(resources)}[/bold] resource(s) from state against "
        f"[bold]{len(all_rules)}[/bold] rule(s)...\n"
    )

    # -- Run validation -------------------------------------------------------
    results = validate_resources(all_rules, resources, Severity(config.min_severity))

    # -- Emit output ----------------------------------------------------------
    fmt = config.output_format
    if fmt == "json":
        click.echo(JSONFormatter().format(results))
    elif fmt == "junit":
        click.echo(JUnitXMLFormatter().format(results))
    elif fmt == "sarif":
        click.echo(SARIFFormatter().format(results))
    elif fmt == "html":
        click.echo(HTMLFormatter().format(results))
    else:
        _display_table(results)
        _print_summary(results)

    # -- Exit code: non-zero on any failures ----------------------------------
    failed = sum(1 for r in results if not r.passed and not r.message.startswith("SKIPPED:"))
    if failed:
        sys.exit(1)


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
    console.print(f"\n[dim]Found {len(packs)} rule pack(s)[/dim]")
