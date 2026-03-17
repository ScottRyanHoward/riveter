# Riveter

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

# Validate deployed state (drift detection)
riveter scan-state -p aws-security -s terraform.tfstate

# Pipe remote state from any Terraform backend
terraform state pull | riveter scan-state -p aws-security -s -

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
| `--min-severity LEVEL` | | `info` (default), `warning`, `error` |
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
| `--min-severity LEVEL` | | `info` (default), `warning`, `error` |
| `--include-rules PATTERN` | | Only run rules matching glob pattern (repeatable) |
| `--exclude-rules PATTERN` | | Skip rules matching glob pattern (repeatable) |
| `--config FILE` | `-c` | Config file path (auto-detected if omitted) |
| `--debug` | | Enable debug logging |

> **State format:** Requires Terraform state format v4 (Terraform 0.13+). Data sources are automatically excluded — only managed resources are validated.

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
| `cis-aws` | 22 | CIS AWS Foundations v1.4.0 |
| `cis-azure` | 34 | CIS Azure Foundations v1.3.0 |
| `cis-gcp` | 43 | CIS GCP Foundations v1.3.0 |
| `aws-well-architected` | 34 | AWS WAF (6 pillars) |
| `azure-well-architected` | 35 | Azure WAF (5 pillars) |
| `gcp-well-architected` | 30 | GCP WAF (5 pillars) |
| `aws-hipaa` | 35 | HIPAA compliance |
| `azure-hipaa` | 30 | Azure HIPAA |
| `aws-pci-dss` | 40 | PCI-DSS compliance |
| `soc2-security` | 28 | SOC 2 Trust Service Criteria |

---

## Writing Custom Rules

Create a YAML file with a `rules` key:

```yaml
rules:
  - id: ec2-must-be-encrypted
    resource_type: aws_instance
    description: All EC2 root volumes must be encrypted
    severity: error
    assert:
      root_block_device.encrypted: true

  - id: ec2-prod-approved-types
    resource_type: aws_instance
    description: Production EC2s must use approved instance types
    severity: warning
    filter:
      tags.Environment: production
    assert:
      instance_type:
        regex: "^(t3|m5|c5)\\.(large|xlarge|2xlarge)$"

  - id: s3-versioning-enabled
    resource_type: aws_s3_bucket
    description: S3 buckets must have versioning enabled
    severity: error
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
| `severity` | No | `error` (default), `warning`, `info` |
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
riveter scan -p aws-security -t main.tf -f html -o report.html
```

Generates a self-contained HTML report with no external dependencies. Open in any browser to explore results with interactive filtering by status, severity, and resource/rule name. Useful for sharing scan results with stakeholders and auditors who can't easily read JSON or SARIF.

---

## AI-Powered Explanations (Optional)

Riveter can explain violations in plain English — why a rule matters, what the risk is, and
exactly how to fix it in your Terraform config.

This feature requires an Anthropic API key (pay-as-you-go, ~$0.001 per explanation).
Get one at https://console.anthropic.com.

Once you have a key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Then add `--explain` to any scan:

```bash
riveter scan -p aws-security -t main.tf --explain
```

Or drill into a specific violation after the fact:

```bash
riveter explain ec2-imdsv2-required \
    --resource aws_instance.web_server --terraform main.tf -p aws-security
```

To always enable explanations, add this to `riveter.yml`:

```yaml
# ai:
#   explain_on_fail: true
#   model: claude-sonnet-4-20250514   # optional model override
```

---

## Config File

Create `riveter.yml` (or `.riveter.yml`) in your project root:

```yaml
rule_packs:
  - aws-security
  - cis-aws

min_severity: warning
output_format: table

include_rules:
  - "*encryption*"

exclude_rules:
  - "*test*"
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
