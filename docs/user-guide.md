# Riveter User Guide

This guide covers everything you need to use Riveter to validate Terraform configurations.

---

## Table of Contents

1. [Installation](#installation)
2. [Basic Usage](#basic-usage)
3. [Rule Packs](#rule-packs)
4. [Custom Rules](#custom-rules)
5. [Configuration File](#configuration-file)
6. [Output Formats](#output-formats)
7. [Filtering](#filtering)
8. [State File Scanning](#state-file-scanning)
9. [AI Features](#ai-features)
10. [CI/CD Integration](#cicd-integration)
11. [Troubleshooting](#troubleshooting)

---

## Installation

### Homebrew (recommended)

```bash
brew install ScottRyanHoward/riveter/riveter
```

Homebrew installs a standalone binary with no Python dependency. Rule packs are included.

### Windows {#windows}

1. Go to the [Releases page](https://github.com/ScottRyanHoward/riveter/releases) and download `riveter-<version>-windows-x86_64.zip`.

2. Extract `riveter.exe` to a folder on your `PATH` (e.g. `C:\tools\riveter\`).

3. Rule packs are not bundled in the binary. Download them from the same release's source archive and copy the YAML files to `%USERPROFILE%\.riveter\rule_packs\`:

```powershell
# Replace with the version you downloaded
$version = "0.2.28"
$tag = "v$version"

New-Item -ItemType Directory -Force "$env:USERPROFILE\.riveter\rule_packs" | Out-Null

Invoke-WebRequest "https://github.com/ScottRyanHoward/riveter/archive/$tag.zip" -OutFile src.zip
Expand-Archive src.zip -DestinationPath src_tmp
Copy-Item "src_tmp\riveter-$version\rule_packs\*.yml" "$env:USERPROFILE\.riveter\rule_packs\" -Force
Remove-Item src.zip, src_tmp -Recurse -Force
```

4. Verify the installation:

```powershell
riveter --version
riveter list-rule-packs
```

### From Source (development)

```bash
git clone https://github.com/ScottRyanHoward/riveter.git
cd riveter
pip install -e ".[dev]"
pre-commit install
```

---

## Basic Usage

### Scan with a built-in rule pack

```bash
riveter scan -p aws-security -t main.tf
```

### Scan with a custom rules file

```bash
riveter scan -r my-rules.yml -t main.tf
```

### Combine both

```bash
riveter scan -p aws-security -r my-rules.yml -t main.tf
```

### Scan a directory of Terraform files

```bash
riveter scan -p aws-security -t ./infra/
```

Riveter recursively finds all `.tf` files in the directory.

### Multiple rule packs

```bash
riveter scan -p aws-security -p cis-aws -p aws-hipaa -t main.tf
```

---

## Rule Packs

### List available packs

```bash
riveter list-rule-packs
```

### Built-in packs

| Pack | Description |
|------|-------------|
| `aws-security` | AWS security best practices |
| `azure-security` | Azure security best practices |
| `gcp-security` | GCP security best practices |
| `kubernetes-security` | Kubernetes / managed K8s security |
| `multi-cloud-security` | Cross-cloud patterns |
| `cis-aws` | CIS AWS Foundations Benchmark v3.0.0 |
| `cis-azure` | CIS Azure Foundations Benchmark v2.0.0 |
| `cis-gcp` | CIS GCP Foundations Benchmark v2.0.0 |
| `aws-well-architected` | AWS Well-Architected Framework |
| `azure-well-architected` | Azure Well-Architected Framework |
| `gcp-well-architected` | GCP Architecture Framework |
| `aws-hipaa` | HIPAA compliance for AWS |
| `azure-hipaa` | HIPAA compliance for Azure |
| `aws-pci-dss` | PCI-DSS v4.0 for AWS |
| `soc2-security` | SOC 2 Trust Service Criteria |

### Custom rule pack directories

Add `rule_dirs` to your config file to point Riveter at additional directories:

```yaml
# riveter.yml
rule_dirs:
  - ./company-rule-packs
  - /shared/infra-policies
```

---

## Custom Rules

### Rule file format

```yaml
rules:
  - id: require-encryption           # unique ID
    resource_type: aws_instance      # Terraform resource type, or "*" for all
    description: EBS volumes must be encrypted
    filter:                          # optional — only apply rule when these match
      tags.Environment: production
    assert:                          # assertions that must ALL be true
      root_block_device.encrypted: true
    metadata:                        # optional extra info
      tags: [encryption, ec2]
      references:
        - https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSEncryption.html
```

### Assertion types

#### Equality (default)

```yaml
assert:
  instance_type: t3.large           # string equality
  multi_az: true                    # boolean equality
  min_tls_version: TLSv1_2         # any YAML scalar
```

#### Presence check

```yaml
assert:
  tags.Environment: present         # value must exist and be non-empty
  kms_key_id: present
```

#### Regex match

```yaml
assert:
  instance_type:
    regex: "^(t3|m5|c5)\\.(large|xlarge|2xlarge)$"
  engine_version:
    regex: "^8\\."
```

#### Numeric comparisons

```yaml
assert:
  backup_retention_period:
    gte: 7                  # greater than or equal
  allocated_storage:
    gte: 20
    lte: 500               # multiple operators on same property
  port:
    ne: 22                  # not equal
```

Operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`

#### List operations

```yaml
assert:
  security_groups:
    contains: "sg-12345678"    # list must contain value
  ingress_rules:
    length:
      lte: 5                   # list length must be ≤ 5
  required_tags:
    subset: ["Environment", "Owner", "Project"]
```

### Dot notation for nested attributes

```yaml
assert:
  root_block_device.encrypted: true
  server_side_encryption_configuration.rule.apply_server_side_encryption_by_default.sse_algorithm: aws:kms
  versioning.enabled: true
```

---

## Configuration File

Create `riveter.yml` in your project root to set defaults:

```yaml
# Rule sources
rule_packs:
  - aws-security
  - cis-aws
rule_dirs:
  - ./custom-packs

# Filtering
include_rules:
  - "*encryption*"
  - "*public*"
exclude_rules:
  - "*test*"

# Output
output_format: table
output_file: report.html  # optional — same as passing -o report.html

# AI features
ai:
  explain_on_fail: true
  model: claude-sonnet-4-20250514        # optional — model for --explain
  generate_model: claude-sonnet-4-20250514  # optional — model for generate-rules
```

Auto-detected filenames (in order): `riveter.yml`, `riveter.yaml`, `.riveter.yml`, `.riveter.yaml`, `riveter.json`, `.riveter.json`.

Or specify explicitly: `riveter scan -c path/to/config.yml -t main.tf`

**CLI flags always override config file values.**

---

## Output Formats

### Table (default)

Color-coded terminal output. PASS = green, FAIL = red, SKIP = dim. Columns: Status, Rule ID, Resource, Message.

```
Scanning 12 resource(s) against 26 rule(s)...

╭────────┬─────────────────────────────┬──────────────────────────┬──────────────────────────╮
│ Status │ Rule ID                     │ Resource                 │ Message                  │
├────────┼─────────────────────────────┼──────────────────────────┼──────────────────────────┤
│  PASS  │ ec2_encrypted_ebs_volumes   │ aws_instance.web         │ All checks passed        │
│  FAIL  │ ec2_no_public_ip            │ aws_instance.web         │ Expected 'associate_...  │
│  SKIP  │ rds_multi_az                │ aws_db_instance.N/A      │ SKIPPED: No matching...  │
╰────────┴─────────────────────────────┴──────────────────────────┴──────────────────────────╯

  Passed:  1
  Failed:  1
  Skipped: 1 (no matching resources found)

1 check(s) failed.
```

### JSON

```bash
riveter scan -p aws-security -t main.tf -f json | jq '.summary'
```

### JUnit XML

```bash
riveter scan -p aws-security -t main.tf -f junit > results.xml
```

### SARIF

```bash
riveter scan -p aws-security -t main.tf -f sarif > results.sarif
# Upload to GitHub Code Scanning, SonarQube, etc.
```

### HTML

Use `-o` to write the HTML report to a file while keeping the table summary visible in your terminal:

```bash
riveter scan -p aws-security -t main.tf -f html -o report.html
open report.html
```

To write to a file silently (no terminal table — useful in CI pipelines):

```bash
riveter scan -p aws-security -t main.tf -f html > report.html
```

> **Tip:** Use `-o` for interactive use, `>` for scripted/CI use where you don't need terminal feedback.

Produces a fully self-contained HTML report — CSS and JavaScript are embedded inline, so the file can be emailed or opened on any machine without an internet connection.

**Report features:**
- Summary cards showing total, passed, failed, and skipped counts
- Filter by status (All / Pass / Fail / Skip), or free-text search across resource and rule IDs
- Click any row to expand assertion details showing the property path, expected value, actual value, and operator for each check
- Riveter version and report timestamp embedded in the header

Ideal for sharing scan results with auditors or stakeholders who need a readable view of findings.

### Progress messages and stderr

Informational messages (rule loading, scanning progress, warnings) are always written to **stderr**, not stdout. This means non-table output formats (HTML, JSON, SARIF, JUnit) are clean on stdout and safe to pipe or redirect:

```bash
# HTML goes to the file; progress messages still appear in the terminal
riveter scan -p aws-security -t main.tf -f html > report.html

# JSON is clean — no progress noise mixed in
riveter scan -p aws-security -t main.tf -f json | jq .
```

---

## Filtering

### By rule ID pattern (glob)

Run only encryption-related rules:

```bash
riveter scan -p aws-security -t main.tf --include-rules "*encrypt*"
```

Exclude test/example rules:

```bash
riveter scan -p aws-security -t main.tf --exclude-rules "*example*" --exclude-rules "*test*"
```

---

## State File Scanning

`riveter scan-state` validates a **deployed** Terraform state file against the same YAML rules used by `riveter scan`. Where `scan` checks your *intended* configuration (`.tf` source files), `scan-state` checks what is *actually deployed* — making it the key tool for **drift detection**.

### What is drift?

Drift occurs when deployed infrastructure diverges from its IaC definition. Common causes:
- Manual changes made in a cloud console
- Out-of-band automation (scripts, third-party tools) modifying resources
- Partial applies or interrupted deployments

### Basic usage

```bash
riveter scan-state -p aws-security -s terraform.tfstate
```

### Remote state (any Terraform backend)

Use `terraform state pull` to export state from any backend (S3, Terraform Cloud, GCS, Azure Storage, etc.) and pipe it directly to Riveter:

```bash
# Terraform Cloud / HCP Terraform
terraform state pull | riveter scan-state -p aws-security -s -

# S3 backend (state is fetched by the Terraform CLI)
cd your-infra-dir && terraform state pull | riveter scan-state -p aws-security -s -
```

The `-s -` flag tells Riveter to read state JSON from stdin.

### Drift detection workflow

Run both commands with the same rule pack and compare results to identify drift:

```bash
# Check intended config
riveter scan -p aws-security -t main.tf -f json > hcl-results.json

# Check deployed state
terraform state pull | riveter scan-state -p aws-security -s - -f json > state-results.json

# Resources that pass in HCL but fail in state have drifted
```

Or generate shareable HTML reports for both:

```bash
riveter scan       -p aws-security -t main.tf           -f html -o hcl-report.html
riveter scan-state -p aws-security -s terraform.tfstate -f html -o state-report.html
```

### State format requirements

- Requires Terraform state format **version 4** (introduced in Terraform 0.13)
- **Data sources** (`data` blocks) are automatically excluded — only managed resources are validated
- Supports `count` and `for_each` resources: each instance is validated separately

### All `scan-state` flags

| Flag | Short | Description |
|------|-------|-------------|
| `--state PATH` | `-s` | **Required.** Path to `.tfstate` file, or `-` for stdin |
| `--rule-pack NAME` | `-p` | Built-in rule pack (repeatable) |
| `--rules FILE` | `-r` | Custom rules YAML file |
| `--output-format FMT` | `-f` | `table`, `json`, `junit`, `sarif`, `html` |
| `--output FILE` | `-o` | Write output to a file; table summary still shown in terminal |
| `--include-rules PATTERN` | | Only run matching rules (repeatable) |
| `--exclude-rules PATTERN` | | Skip matching rules (repeatable) |
| `--config FILE` | `-c` | Config file (auto-detected if omitted) |
| `--debug` | | Enable debug logging |

---

## AI Features

Both AI features require an [Anthropic API key](https://console.anthropic.com). The `anthropic` package is bundled in the Homebrew and standalone binary distributions. If you installed via pip, add it with:

```bash
pip install riveter[ai]
```

Then set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Riveter degrades gracefully when no key is set — scans and rule loading work normally, AI features are simply skipped.

---

### Rule Generation (`generate-rules`)

`riveter generate-rules` reads your Terraform files, groups resources by type, and asks Claude to suggest 3–5 enforceable rules per type. The output is a ready-to-use rules YAML file.

**Basic usage:**

```bash
# Print generated rules to stdout
riveter generate-rules -t main.tf

# Save to a file
riveter generate-rules -t ./infra/ -o my-rules.yml
```

**Scan with the generated rules:**

```bash
riveter scan -r my-rules.yml -t ./infra/
```

**Focus the AI on a specific area:**

The `--focus` flag guides Claude toward a particular concern. Without it, general security and operational best practices are used.

```bash
riveter generate-rules -t main.tf --focus "PCI-DSS compliance" -o pci-rules.yml
riveter generate-rules -t main.tf --focus "cost optimization" -o cost-rules.yml
riveter generate-rules -t main.tf --focus "CIS AWS Foundations Benchmark" -o cis-rules.yml
```

**All flags:**

| Flag | Short | Description |
|------|-------|-------------|
| `--terraform PATH` | `-t` | **Required.** `.tf` file or directory |
| `--output FILE` | `-o` | Write YAML to a file instead of stdout |
| `--focus TEXT` | | Plain-text guidance for the AI |
| `--model MODEL` | | Override the Claude model (default: `claude-sonnet-4-20250514`) |
| `--debug` | | Enable debug logging |

**Workflow tips:**

- Generated rules are validated against the rule schema before output. Invalid suggestions (bad operators, missing required fields) are silently dropped.
- Always review generated rules before enforcing them in CI — the AI may suggest rules based on attributes that are optional or environment-specific.
- Use `--focus` to get more targeted output. Broad prompts produce broad rules; specific compliance frameworks produce specific rules.
- Run `riveter scan -r generated.yml -t ./infra/` immediately after generating to see which rules have matches and which are SKIPPED.

---

### Violation Explanations (`--explain` / `explain`)

Riveter can explain each violation in plain English: why the rule matters, what an attacker could do, and the exact Terraform change needed to fix it.

**Inline during a scan:**

```bash
riveter scan -p aws-security -t main.tf --explain
```

Explanations appear underneath each failing row in the table. In JSON and HTML output, they are included in the structured result.

Cost: approximately $0.001 per explanation.

**Drill into a specific violation:**

```bash
riveter explain ec2_no_public_ip \
    --resource aws_instance.web_server \
    --terraform main.tf \
    -p aws-security
```

This is useful when you want to understand a rule before fixing it, without re-running a full scan.

**Always-on via config:**

```yaml
# riveter.yml
ai:
  explain_on_fail: true
  model: claude-sonnet-4-20250514        # optional — default model for explanations
  generate_model: claude-sonnet-4-20250514  # optional — model for generate-rules
```

> **Note:** `--explain` works on `riveter scan` only, not `scan-state`.

---

## CI/CD Integration

### GitHub Actions — basic

```yaml
name: Terraform Security
on: [push, pull_request]

jobs:
  riveter:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Riveter
        run: brew install ScottRyanHoward/riveter/riveter

      - name: Scan Terraform
        run: riveter scan -p aws-security -t main.tf
```

### GitHub Actions — with JUnit report

```yaml
      - name: Scan Terraform
        run: riveter scan -p aws-security -t main.tf -f junit > riveter-results.xml
        continue-on-error: true

      - name: Publish results
        uses: mikepenz/action-junit-report@v4
        with:
          report_paths: riveter-results.xml
        if: always()
```

### GitHub Actions — SARIF (Code Scanning)

```yaml
      - name: Scan Terraform
        run: riveter scan -p aws-security -t main.tf -f sarif > results.sarif

      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: results.sarif
        if: always()
```

### GitHub Actions — Windows

```yaml
jobs:
  riveter:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Riveter
        shell: pwsh
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $tag = (gh release list --repo ScottRyanHoward/riveter --limit 1 --json tagName | ConvertFrom-Json)[0].tagName
          $version = $tag.TrimStart('v')
          gh release download $tag --repo ScottRyanHoward/riveter --pattern "riveter-$version-windows-x86_64.zip"
          Expand-Archive "riveter-$version-windows-x86_64.zip" -DestinationPath .
          echo "$PWD" | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append

          New-Item -ItemType Directory -Force "$env:USERPROFILE\.riveter\rule_packs" | Out-Null
          Invoke-WebRequest "https://github.com/ScottRyanHoward/riveter/archive/$tag.zip" -OutFile src.zip
          Expand-Archive src.zip -DestinationPath src_tmp
          Copy-Item "src_tmp\riveter-$version\rule_packs\*.yml" "$env:USERPROFILE\.riveter\rule_packs\" -Force
          Remove-Item src.zip, src_tmp -Recurse -Force

      - name: Scan Terraform
        run: riveter scan -p aws-security -t main.tf
```

### GitLab CI

```yaml
riveter:
  image: ubuntu:latest
  script:
    - brew install ScottRyanHoward/riveter/riveter
    - riveter scan -p aws-security -t main.tf -f junit > riveter-results.xml
  artifacts:
    reports:
      junit: riveter-results.xml
```

---

## Troubleshooting

### "Rule pack not found"

```
Error: Rule pack 'aws-security' not found.
```

If you installed via Homebrew, rule packs should be at `/opt/homebrew/share/riveter/rule_packs/` (Apple Silicon) or `/usr/local/share/riveter/rule_packs/` (Intel). Verify:

```bash
ls $(brew --prefix)/share/riveter/rule_packs/
```

If running from source, ensure you're in the repo root and the `rule_packs/` directory exists.

### "Rule pack not found" on Windows

Rule packs are discovered from `%USERPROFILE%\.riveter\rule_packs\` on Windows. Verify the directory exists and contains YAML files:

```powershell
Get-ChildItem "$env:USERPROFILE\.riveter\rule_packs\"
```

If it's empty, re-run the rule pack install step from the [Windows installation instructions](#windows).

### "No resources found"

Riveter only processes `resource` blocks. `data`, `variable`, `output`, and `module` blocks are ignored. Verify your Terraform file has resource blocks:

```bash
grep -c 'resource "' main.tf
```

### HTML output looks garbled in the terminal

If you run `riveter scan -f html` without redirecting output, the raw HTML will print to your terminal. Use `-o` to write directly to a file instead:

```bash
# Correct — writes HTML to file, shows table in terminal
riveter scan -p aws-security -t main.tf -f html -o report.html

# Also works — HTML goes to the file, progress messages still visible in terminal
riveter scan -p aws-security -t main.tf -f html > report.html
```

### Debug mode

Add `--debug` to see detailed logging:

```bash
riveter scan -p aws-security -t main.tf --debug
```

### All rules show as SKIPPED

SKIPPED means the rule's `resource_type` didn't match any resource in your Terraform file. For example, `aws-security` rules apply to `aws_instance`, `aws_s3_bucket`, etc. If your Terraform only defines Azure resources, AWS rules will be SKIPPED.

Use the correct pack for your cloud provider:

```bash
riveter scan -p azure-security -t main.tf
```
