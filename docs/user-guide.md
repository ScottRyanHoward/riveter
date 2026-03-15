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
8. [CI/CD Integration](#cicd-integration)
9. [Troubleshooting](#troubleshooting)

---

## Installation

### Homebrew (recommended)

```bash
brew install ScottRyanHoward/riveter/riveter
```

Homebrew installs a standalone binary with no Python dependency. Rule packs are included.

### From Source (development)

```bash
git clone https://github.com/ScottRyanHoward/riveter.git
cd riveter
pip install -e ".[dev]"
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
| `cis-aws` | CIS AWS Foundations Benchmark v1.4.0 |
| `cis-azure` | CIS Azure Foundations Benchmark v1.3.0 |
| `cis-gcp` | CIS GCP Foundations Benchmark v1.3.0 |
| `aws-well-architected` | AWS Well-Architected Framework |
| `azure-well-architected` | Azure Well-Architected Framework |
| `gcp-well-architected` | GCP Architecture Framework |
| `aws-hipaa` | HIPAA compliance for AWS |
| `azure-hipaa` | HIPAA compliance for Azure |
| `aws-pci-dss` | PCI-DSS for AWS |
| `soc2-security` | SOC 2 Trust Service Criteria |

### Custom rule pack directories

Add `rule_dirs` to your config file or use `--rule-dirs` to point Riveter at additional directories:

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
    severity: error                  # error | warning | info (default: error)
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
min_severity: warning
include_rules:
  - "*encryption*"
  - "*public*"
exclude_rules:
  - "*test*"

# Output
output_format: table
```

Auto-detected filenames (in order): `riveter.yml`, `riveter.yaml`, `.riveter.yml`, `.riveter.yaml`, `riveter.json`, `.riveter.json`.

Or specify explicitly: `riveter scan -c path/to/config.yml -t main.tf`

**CLI flags always override config file values.**

---

## Output Formats

### Table (default)

Color-coded terminal output. PASS = green, FAIL = red, SKIP = dim.

```
Scanning 12 resource(s) against 26 rule(s)...

╭────────┬──────────┬─────────────────────────────┬──────────────────────────┬──────────────────────────╮
│ Status │ Severity │ Rule ID                     │ Resource                 │ Message                  │
├────────┼──────────┼─────────────────────────────┼──────────────────────────┼──────────────────────────┤
│  PASS  │ error    │ ec2_encrypted_ebs_volumes   │ aws_instance.web         │ All checks passed        │
│  FAIL  │ error    │ ec2_no_public_ip            │ aws_instance.web         │ Expected 'associate_...  │
│  SKIP  │ warning  │ rds_multi_az                │ aws_db_instance.N/A      │ SKIPPED: No matching...  │
╰────────┴──────────┴─────────────────────────────┴──────────────────────────┴──────────────────────────╯

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

---

## Filtering

### By severity

Only report warnings and errors (skip info-level):

```bash
riveter scan -p aws-security -t main.tf --min-severity warning
```

Only report errors:

```bash
riveter scan -p aws-security -t main.tf --min-severity error
```

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

### "No resources found"

Riveter only processes `resource` blocks. `data`, `variable`, `output`, and `module` blocks are ignored. Verify your Terraform file has resource blocks:

```bash
grep -c 'resource "' main.tf
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
