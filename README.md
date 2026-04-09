# Riveter

[![CI](https://github.com/ScottRyanHoward/riveter/actions/workflows/ci.yml/badge.svg)](https://github.com/ScottRyanHoward/riveter/actions/workflows/ci.yml)

**Infrastructure Rule Enforcement as Code** — validate Terraform configurations against YAML rules before deployment.

Riveter catches security misconfigurations and compliance violations during development, not after. Define rules in plain YAML, use one of 15 built-in compliance packs, or do both.

---

## Installation

```bash
brew install ScottRyanHoward/riveter/riveter
```

---

## Quick Start

```bash
# Scan with a built-in rule pack
riveter scan -p aws-security -t main.tf

# Scan with a custom rules file
riveter scan -r my-rules.yml -t main.tf

# Combine multiple packs
riveter scan -p aws-security -p cis-aws -t main.tf

# Scan an entire directory
riveter scan -p aws-security -t ./infra/

# Save an HTML report and still see results in the terminal
riveter scan -p aws-security -t main.tf -f html -o report.html

# Validate deployed state (drift detection)
riveter scan-state -p aws-security -s terraform.tfstate

# Pipe remote state from any Terraform backend
terraform state pull | riveter scan-state -p aws-security -s -

# Generate rules for your Terraform files using AI (requires ANTHROPIC_API_KEY)
riveter generate-rules -t ./infra/ -o my-rules.yml
riveter scan -r my-rules.yml -t ./infra/

# See available rule packs
riveter list-rule-packs
```

---

## Commands

### `riveter scan`

Validates Terraform against rules and exits non-zero if any checks fail.

| Flag | Short | Description |
|------|-------|-------------|
| `--terraform PATH` | `-t` | **Required.** Path to a `.tf` file or directory |
| `--rule-pack NAME` | `-p` | Built-in rule pack (repeatable) |
| `--rules FILE` | `-r` | Custom rules YAML file |
| `--output-format FMT` | `-f` | `table` (default), `json`, `junit`, `sarif`, `html` |
| `--output FILE` | `-o` | Write output to a file; table summary still shown in terminal |
| `--include-rules PATTERN` | | Only run rules matching glob pattern (repeatable) |
| `--exclude-rules PATTERN` | | Skip rules matching glob pattern (repeatable) |
| `--config FILE` | `-c` | Config file path (auto-detected if omitted) |
| `--explain` | `-e` | Attach AI-generated explanations to violations (requires `ANTHROPIC_API_KEY`) |
| `--debug` | | Enable debug logging |

### `riveter scan-state`

Validates a Terraform **state file** against rules for drift detection.

| Flag | Short | Description |
|------|-------|-------------|
| `--state PATH` | `-s` | **Required.** Path to `terraform.tfstate`, or `-` for stdin |
| `--rule-pack NAME` | `-p` | Built-in rule pack (repeatable) |
| `--rules FILE` | `-r` | Custom rules YAML file |
| `--output-format FMT` | `-f` | `table` (default), `json`, `junit`, `sarif`, `html` |
| `--output FILE` | `-o` | Write output to a file; table summary still shown in terminal |
| `--include-rules PATTERN` | | Only run rules matching glob pattern (repeatable) |
| `--exclude-rules PATTERN` | | Skip rules matching glob pattern (repeatable) |
| `--config FILE` | `-c` | Config file path (auto-detected if omitted) |
| `--debug` | | Enable debug logging |

> **State format:** Requires Terraform state format v4 (Terraform 0.13+). Data sources are automatically excluded — only managed resources are validated.

### `riveter generate-rules`

Uses Claude to suggest 3–5 enforceable Riveter rules per resource type found in your Terraform files. Output is a valid rules YAML file you can review, customize, and pass to `riveter scan -r`. Requires `ANTHROPIC_API_KEY`.

| Flag | Short | Description |
|------|-------|-------------|
| `--terraform PATH` | `-t` | **Required.** Path to a `.tf` file or directory |
| `--output FILE` | `-o` | Write generated rules to a file (default: stdout) |
| `--focus TEXT` | | Guide the AI, e.g. `"PCI-DSS compliance"` or `"cost optimization"` |
| `--model MODEL` | | Override the Claude model |
| `--debug` | | Enable debug logging |

### `riveter list-rule-packs`

Lists all available rule packs with name, version, rule count, and description.

---

## Built-in Rule Packs

| Pack | Rules | Coverage |
|------|-------|----------|
| `aws-security` | 26 | EC2, S3, RDS, VPC, IAM, KMS, Lambda |
| `azure-security` | 28 | VMs, Storage, SQL, Key Vault, NSGs |
| `gcp-security` | 29 | Compute, Storage, SQL, VPC, IAM |
| `kubernetes-security` | 40 | EKS, AKS, GKE |
| `multi-cloud-security` | 40 | Cross-cloud patterns |
| `cis-aws` | 22 | CIS AWS Foundations Benchmark v3.0.0 |
| `cis-azure` | 34 | CIS Azure Foundations Benchmark v2.0.0 |
| `cis-gcp` | 43 | CIS GCP Foundations Benchmark v2.0.0 |
| `aws-well-architected` | 34 | AWS Well-Architected Framework |
| `azure-well-architected` | 35 | Azure Well-Architected Framework |
| `gcp-well-architected` | 30 | GCP Architecture Framework |
| `aws-hipaa` | 35 | HIPAA compliance |
| `azure-hipaa` | 30 | Azure HIPAA |
| `aws-pci-dss` | 40 | PCI-DSS v4.0 compliance |
| `soc2-security` | 28 | SOC 2 Trust Service Criteria |

---

## Writing Custom Rules

Create a YAML file with a `rules` key:

```yaml
rules:
  - id: ec2-must-be-encrypted
    resource_type: aws_instance
    description: All EC2 root volumes must be encrypted
    assert:
      root_block_device.encrypted: true

  - id: ec2-prod-approved-types
    resource_type: aws_instance
    description: Production EC2s must use approved instance types
    filter:
      tags.Environment: production
    assert:
      instance_type:
        regex: "^(t3|m5|c5)\\.(large|xlarge|2xlarge)$"

  - id: s3-versioning-enabled
    resource_type: aws_s3_bucket
    description: S3 buckets must have versioning enabled
    assert:
      versioning.enabled: true
      tags.Owner: present
```

### Rule Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique rule identifier |
| `resource_type` | Yes | Terraform resource type, or `"*"` for all |
| `assert` | Yes | Assertions that must all be true |
| `description` | No | Human-readable summary |
| `filter` | No | Conditions a resource must match for the rule to apply |
| `metadata` | No | Extra metadata (tags, references, etc.) |

### Assertion Operators

By default, `property: value` is an **equality check**. Use operator syntax for richer comparisons:

```yaml
assert:
  # Equality (default)
  instance_type: t3.large
  associate_public_ip_address: false

  # Presence check
  tags.Owner: present

  # Regex match
  instance_type:
    regex: "^(t3|m5)\\.(large|xlarge)$"

  # Numeric comparisons: gt, gte, lt, lte, ne, eq
  root_block_device.volume_size:
    gte: 100

  # List operations
  allowed_cidrs:
    contains: "10.0.0.0/8"
  ingress_rules:
    length:
      lte: 5
```

### Nested Properties

Use dot notation to access nested attributes:

```yaml
assert:
  root_block_device.encrypted: true
  tags.Environment: present
```

### Filters

Filters restrict which resources a rule applies to. A rule is only evaluated for resources where **all** filter conditions match:

```yaml
filter:
  tags.Environment: production
```

---

## Output Formats

### Table (default)

Rich terminal output with color-coded PASS/FAIL/SKIP status.

### JSON

```bash
riveter scan -p aws-security -t main.tf -f json > results.json
```

### JUnit XML (CI/CD)

```bash
riveter scan -p aws-security -t main.tf -f junit > results.xml
```

Compatible with GitHub Actions, Jenkins, GitLab CI, and any JUnit-aware CI system.

### SARIF

```bash
riveter scan -p aws-security -t main.tf -f sarif > results.sarif
```

Upload to GitHub Code Scanning for inline annotations.

### HTML

```bash
# Write report to file and see table summary in the terminal
riveter scan -p aws-security -t main.tf -f html -o report.html

# Or redirect stdout to a file (no terminal table)
riveter scan -p aws-security -t main.tf -f html > report.html
```

Generates a self-contained HTML report with no external dependencies. Open in any browser to explore results with interactive filtering by status and resource/rule name. Click any row to expand full assertion details. When `--explain` is used, AI-generated explanations appear in the expanded detail panel for each failure. Useful for sharing scan results with stakeholders and auditors who can't easily read JSON or SARIF.

> **Tip:** Use `-o report.html` instead of `> report.html` to write the HTML to a file while keeping the table summary visible in your terminal.

---

## AI Features (Optional)

Both AI features require an Anthropic API key (pay-as-you-go).
Get one at https://console.anthropic.com, then export it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Rule Generation

Don't know where to start with rules? Let Claude write a first draft based on your actual Terraform:

```bash
# Generate rules and print to stdout
riveter generate-rules -t ./infra/

# Save to a file and scan immediately
riveter generate-rules -t ./infra/ -o my-rules.yml
riveter scan -r my-rules.yml -t ./infra/

# Focus on a specific compliance framework
riveter generate-rules -t main.tf --focus "PCI-DSS compliance" -o pci-rules.yml
```

Riveter parses your Terraform, groups resources by type, and calls Claude once per type to suggest 3–5 enforceable rules. Each rule is validated against the rule schema before output — invalid suggestions are silently dropped. Always review and test generated rules before enforcing them in CI.

### Violation Explanations

Riveter can explain violations in plain English — why a rule matters, what the risk is, and
exactly how to fix it in your Terraform config.

Add `--explain` to any scan (cost: ~$0.001 per explanation):

```bash
riveter scan -p aws-security -t main.tf --explain
```

Or drill into a specific violation after the fact:

```bash
riveter explain ec2_no_public_ip \
    --resource aws_instance.web_server --terraform main.tf -p aws-security
```

To always enable explanations, add this to `riveter.yml`:

```yaml
ai:
  explain_on_fail: true
  model: claude-sonnet-4-20250514      # optional — overrides the default model
  generate_model: claude-sonnet-4-20250514  # optional — model used for generate-rules
```

> **Note:** `--explain` is available on `riveter scan` only, not `scan-state`.

---

## Config File

Create `riveter.yml` (or `.riveter.yml`) in your project root:

```yaml
rule_packs:
  - aws-security
  - cis-aws

rule_dirs:
  - ./my-custom-rules   # load rule packs from additional local directories

output_format: table
output_file: report.html  # optional — same as passing -o report.html

include_rules:
  - "*encryption*"

exclude_rules:
  - "*test*"

ai:
  explain_on_fail: true
  model: claude-sonnet-4-20250514        # optional — model for --explain
  generate_model: claude-sonnet-4-20250514  # optional — model for generate-rules
```

CLI flags always override config file values.

---

## CI/CD Integration

### GitHub Actions

```yaml
- name: Scan Terraform with Riveter
  run: |
    brew install ScottRyanHoward/riveter/riveter
    riveter scan -p aws-security -t main.tf -f junit > riveter-results.xml

- name: Publish test results
  uses: mikepenz/action-junit-report@v4
  with:
    report_paths: riveter-results.xml
  if: always()
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All checks passed |
| `1` | One or more checks failed (or a usage error occurred) |

---

## Documentation

- **[User Guide](docs/user-guide.md)** — detailed usage, configuration, and CI/CD recipes
- **[Developer Guide](docs/developer-guide.md)** — architecture, adding rule packs, contributing

---

## License

MIT — see [LICENSE](LICENSE).
