# Complex Terraform configuration for Riveter scanning demos.
#
# Covers a realistic multi-cloud stack (AWS, GCP, Kubernetes) with intentional
# violations mixed in alongside correctly-configured resources.
#
# Good test commands:
#   riveter scan -p aws-security -t examples/complex.tf
#   riveter scan -p gcp-security -t examples/complex.tf
#   riveter scan -p kubernetes-security -t examples/complex.tf
#   riveter scan -p aws-security -p cis-aws -t examples/complex.tf
#   riveter scan -p aws-security -t examples/complex.tf -f html -o report.html
#   riveter scan -p aws-security -t examples/complex.tf --include-rules "*s3*"

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

provider "google" {
  project = "my-gcp-project"
  region  = "us-central1"
}

provider "kubernetes" {
  config_path = "~/.kube/config"
}

# -----------------------------------------------------------------------------
# VPC & Networking
# -----------------------------------------------------------------------------

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "main-vpc"
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true  # VIOLATION: auto-assigns public IPs

  tags = {
    Name        = "public-a"
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_subnet" "private_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.10.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = false  # OK

  tags = {
    Name        = "private-a"
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

# -----------------------------------------------------------------------------
# Security Groups
# -----------------------------------------------------------------------------

resource "aws_security_group" "alb_sg" {
  name        = "alb-sg"
  description = "Security group for the application load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_security_group" "app_sg" {
  name        = "app-sg"
  description = "Security group for application servers"
  vpc_id      = aws_vpc.main.id

  # VIOLATION: SSH open to the entire internet
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # VIOLATION: RDP open to the entire internet
  ingress {
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = "production"
    Owner       = "team-app"
    Project     = "core-infra"
  }
}

resource "aws_security_group" "db_sg" {
  name        = "db-sg"
  description = "Security group for RDS"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app_sg.id]  # OK: locked to app tier
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = "production"
    Owner       = "team-data"
    Project     = "core-infra"
  }
}

# -----------------------------------------------------------------------------
# EC2 Instances
# -----------------------------------------------------------------------------

resource "aws_instance" "bastion" {
  ami                         = "ami-0c55b159cbfafe1f0"
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public_a.id
  associate_public_ip_address = true  # OK for a bastion

  root_block_device {
    volume_size = 20
    encrypted   = true  # OK
  }

  metadata_options {
    http_tokens = "required"  # OK: IMDSv2 enforced
  }

  tags = {
    Name        = "bastion"
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_instance" "app_server_1" {
  ami                         = "ami-0c55b159cbfafe1f0"
  instance_type               = "t3.large"
  subnet_id                   = aws_subnet.private_a.id
  associate_public_ip_address = false

  root_block_device {
    volume_size = 100
    encrypted   = false  # VIOLATION: unencrypted root volume
  }

  # VIOLATION: IMDSv1 allowed (http_tokens not set to "required")
  metadata_options {
    http_tokens = "optional"
  }

  tags = {
    Name        = "app-server-1"
    Environment = "production"
    Owner       = "team-app"
    Project     = "ecommerce"
  }
}

resource "aws_instance" "app_server_2" {
  ami                         = "ami-0c55b159cbfafe1f0"
  instance_type               = "t3.large"
  subnet_id                   = aws_subnet.private_a.id
  associate_public_ip_address = false

  root_block_device {
    volume_size = 100
    encrypted   = true  # OK
  }

  metadata_options {
    http_tokens = "required"  # OK
  }

  # VIOLATION: missing required tags (Owner, Project)
  tags = {
    Name        = "app-server-2"
    Environment = "production"
  }
}

# -----------------------------------------------------------------------------
# S3 Buckets
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "assets" {
  bucket = "my-company-static-assets"

  tags = {
    Environment = "production"
    Owner       = "team-frontend"
    Project     = "ecommerce"
  }
}

resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id
  versioning_configuration {
    status = "Enabled"  # OK
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"  # OK
    }
  }
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket                  = aws_s3_bucket.assets.id
  block_public_acls       = true   # OK
  block_public_policy     = true   # OK
  ignore_public_acls      = true   # OK
  restrict_public_buckets = true   # OK
}

resource "aws_s3_bucket" "data_lake" {
  bucket = "my-company-data-lake"

  tags = {
    Environment = "production"
    Owner       = "team-data"
    Project     = "analytics"
  }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration {
    status = "Suspended"  # VIOLATION: versioning disabled on data bucket
  }
}

# VIOLATION: no encryption configuration on data_lake bucket
# VIOLATION: no public access block on data_lake bucket

resource "aws_s3_bucket" "logs" {
  bucket = "my-company-access-logs"

  # VIOLATION: missing required tags (Owner, Project)
  tags = {
    Environment = "production"
  }
}

# -----------------------------------------------------------------------------
# RDS
# -----------------------------------------------------------------------------

resource "aws_db_instance" "primary" {
  identifier        = "prod-postgres-primary"
  engine            = "postgres"
  engine_version    = "15.4"
  instance_class    = "db.t3.medium"
  allocated_storage = 100

  db_name  = "appdb"
  username = "dbadmin"
  password = "changeme123!"  # VIOLATION: hardcoded password

  multi_az               = true   # OK
  storage_encrypted      = true   # OK
  deletion_protection    = true   # OK
  skip_final_snapshot    = false  # OK
  publicly_accessible    = false  # OK
  backup_retention_period = 7     # OK

  db_subnet_group_name   = "prod-db-subnet-group"
  vpc_security_group_ids = [aws_security_group.db_sg.id]

  tags = {
    Environment = "production"
    Owner       = "team-data"
    Project     = "ecommerce"
  }
}

resource "aws_db_instance" "analytics" {
  identifier        = "prod-postgres-analytics"
  engine            = "postgres"
  engine_version    = "14.8"
  instance_class    = "db.t3.large"
  allocated_storage = 500

  db_name  = "analyticsdb"
  username = "analyticsadmin"
  password = "anotherpassword!"  # VIOLATION: hardcoded password

  multi_az               = false  # VIOLATION: no multi-AZ for analytics DB
  storage_encrypted      = false  # VIOLATION: unencrypted storage
  deletion_protection    = false  # VIOLATION: no deletion protection
  skip_final_snapshot    = true   # VIOLATION: skipping final snapshot
  publicly_accessible    = true   # VIOLATION: publicly accessible database
  backup_retention_period = 0     # VIOLATION: no backups

  db_subnet_group_name   = "prod-db-subnet-group"
  vpc_security_group_ids = [aws_security_group.db_sg.id]

  tags = {
    Environment = "production"
    Owner       = "team-data"
    Project     = "analytics"
  }
}

# -----------------------------------------------------------------------------
# IAM
# -----------------------------------------------------------------------------

resource "aws_iam_role" "app_role" {
  name = "app-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_iam_policy" "app_policy" {
  name        = "app-policy"
  description = "Policy for the application EC2 role"

  # VIOLATION: overly permissive wildcard actions and resources
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = "*"
      Effect   = "Allow"
      Resource = "*"
    }]
  })
}

resource "aws_iam_policy" "scoped_policy" {
  name        = "scoped-s3-policy"
  description = "Scoped read-only policy for the assets bucket"

  # OK: scoped to specific actions and resource
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Effect   = "Allow"
      Resource = [
        "arn:aws:s3:::my-company-static-assets",
        "arn:aws:s3:::my-company-static-assets/*"
      ]
    }]
  })
}

# -----------------------------------------------------------------------------
# KMS
# -----------------------------------------------------------------------------

resource "aws_kms_key" "app_key" {
  description             = "KMS key for application secrets"
  deletion_window_in_days = 30   # OK
  enable_key_rotation     = true # OK

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_kms_key" "log_key" {
  description             = "KMS key for log encryption"
  deletion_window_in_days = 7    # VIOLATION: too short a deletion window
  enable_key_rotation     = false  # VIOLATION: key rotation disabled

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

# -----------------------------------------------------------------------------
# ALB
# -----------------------------------------------------------------------------

resource "aws_lb" "app_alb" {
  name               = "app-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = [aws_subnet.public_a.id]

  drop_invalid_header_fields = true  # OK
  enable_deletion_protection = true  # OK

  access_logs {
    bucket  = aws_s3_bucket.logs.bucket
    enabled = true  # OK
  }

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "ecommerce"
  }
}

resource "aws_lb" "internal_alb" {
  name               = "internal-alb"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.app_sg.id]
  subnets            = [aws_subnet.private_a.id]

  drop_invalid_header_fields = false  # VIOLATION: invalid headers not dropped
  enable_deletion_protection = false  # VIOLATION: no deletion protection

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

# -----------------------------------------------------------------------------
# Lambda
# -----------------------------------------------------------------------------

resource "aws_lambda_function" "processor" {
  function_name = "order-processor"
  role          = aws_iam_role.app_role.arn
  handler       = "index.handler"
  runtime       = "python3.12"
  filename      = "processor.zip"

  tracing_config {
    mode = "Active"  # OK: X-Ray tracing enabled
  }

  environment {
    variables = {
      LOG_LEVEL  = "INFO"
      QUEUE_URL  = "https://sqs.us-east-1.amazonaws.com/123456789/orders"
    }
  }

  tags = {
    Environment = "production"
    Owner       = "team-app"
    Project     = "ecommerce"
  }
}

resource "aws_lambda_function" "notifier" {
  function_name = "order-notifier"
  role          = aws_iam_role.app_role.arn
  handler       = "index.handler"
  runtime       = "nodejs18.x"
  filename      = "notifier.zip"

  # VIOLATION: X-Ray tracing not enabled
  # VIOLATION: no reserved_concurrent_executions (unbounded concurrency)

  environment {
    variables = {
      # VIOLATION: secret stored as plaintext env var
      SENDGRID_API_KEY = "SG.abc123secretkey"
      REGION           = "us-east-1"
    }
  }

  tags = {
    Environment = "production"
    Owner       = "team-app"
    Project     = "ecommerce"
  }
}

# -----------------------------------------------------------------------------
# CloudTrail
# -----------------------------------------------------------------------------

resource "aws_cloudtrail" "org_trail" {
  name                          = "org-trail"
  s3_bucket_name                = aws_s3_bucket.logs.bucket
  include_global_service_events = true   # OK
  is_multi_region_trail         = true   # OK
  enable_log_file_validation    = true   # OK
  kms_key_id                    = aws_kms_key.app_key.arn  # OK

  tags = {
    Environment = "production"
    Owner       = "team-security"
    Project     = "core-infra"
  }
}

resource "aws_cloudtrail" "dev_trail" {
  name                          = "dev-trail"
  s3_bucket_name                = aws_s3_bucket.logs.bucket
  include_global_service_events = false  # VIOLATION
  is_multi_region_trail         = false  # VIOLATION
  enable_log_file_validation    = false  # VIOLATION: log tampering not detected

  # VIOLATION: no KMS encryption

  tags = {
    Environment = "development"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

# -----------------------------------------------------------------------------
# SQS
# -----------------------------------------------------------------------------

resource "aws_sqs_queue" "orders" {
  name                       = "orders-queue"
  message_retention_seconds  = 86400
  visibility_timeout_seconds = 30
  kms_master_key_id          = aws_kms_key.app_key.id  # OK: encrypted

  tags = {
    Environment = "production"
    Owner       = "team-app"
    Project     = "ecommerce"
  }
}

resource "aws_sqs_queue" "dead_letter" {
  name                      = "orders-dlq"
  message_retention_seconds = 1209600

  # VIOLATION: no KMS encryption on DLQ

  tags = {
    Environment = "production"
    Owner       = "team-app"
    Project     = "ecommerce"
  }
}

# -----------------------------------------------------------------------------
# EKS Cluster
# -----------------------------------------------------------------------------

resource "aws_eks_cluster" "main" {
  name     = "prod-cluster"
  role_arn = aws_iam_role.app_role.arn
  version  = "1.29"

  vpc_config {
    subnet_ids              = [aws_subnet.private_a.id]
    endpoint_private_access = true   # OK
    endpoint_public_access  = false  # OK: fully private
  }

  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = aws_kms_key.app_key.arn  # OK
    }
  }

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_eks_cluster" "staging" {
  name     = "staging-cluster"
  role_arn = aws_iam_role.app_role.arn
  version  = "1.27"  # VIOLATION: outdated Kubernetes version

  vpc_config {
    subnet_ids              = [aws_subnet.public_a.id]
    endpoint_private_access = false  # VIOLATION
    endpoint_public_access  = true   # VIOLATION: public API server endpoint
  }

  # VIOLATION: no secrets encryption

  tags = {
    Environment = "staging"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

# -----------------------------------------------------------------------------
# ElastiCache (Redis)
# -----------------------------------------------------------------------------

resource "aws_elasticache_cluster" "session_cache" {
  cluster_id           = "session-cache"
  engine               = "redis"
  node_type            = "cache.t3.medium"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = "prod-cache-subnet-group"
  security_group_ids   = [aws_security_group.app_sg.id]

  # VIOLATION: at_rest_encryption_enabled not set (defaults to false)
  # VIOLATION: transit_encryption_enabled not set (defaults to false)

  tags = {
    Environment = "production"
    Owner       = "team-app"
    Project     = "ecommerce"
  }
}

# -----------------------------------------------------------------------------
# SNS
# -----------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name              = "platform-alerts"
  kms_master_key_id = aws_kms_key.app_key.id  # OK

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "core-infra"
  }
}

resource "aws_sns_topic" "notifications" {
  name = "order-notifications"
  # VIOLATION: no KMS encryption

  tags = {
    Environment = "production"
    Owner       = "team-app"
    Project     = "ecommerce"
  }
}

# =============================================================================
# GCP Resources
# =============================================================================

# -----------------------------------------------------------------------------
# GCP Project Metadata
# -----------------------------------------------------------------------------

resource "google_compute_project_metadata" "default" {
  metadata = {
    enable-oslogin = "TRUE"  # OK: OS Login enforced project-wide
  }
}

# -----------------------------------------------------------------------------
# GCP KMS
# -----------------------------------------------------------------------------

resource "google_kms_key_ring" "main" {
  name     = "main-keyring"
  location = "us-central1"
}

resource "google_kms_crypto_key" "app_key" {
  name            = "app-key"
  key_ring        = google_kms_key_ring.main.id
  purpose         = "ENCRYPT_DECRYPT"  # OK: valid purpose
  rotation_period = "7776000s"         # OK: 90-day rotation

  lifecycle {
    prevent_destroy = true  # OK
  }
}

resource "google_kms_crypto_key" "legacy_key" {
  name     = "legacy-key"
  key_ring = google_kms_key_ring.main.id
  purpose  = "ENCRYPT_DECRYPT"

  # VIOLATION: no rotation_period (gcp_kms_key_rotation)
  # VIOLATION: no lifecycle.prevent_destroy (gcp_kms_prevent_destroy)
}

# -----------------------------------------------------------------------------
# GCP VPC & Networking
# -----------------------------------------------------------------------------

resource "google_compute_network" "main" {
  name                    = "main-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "private" {
  name          = "private-subnet"
  ip_cidr_range = "10.1.0.0/24"
  region        = "us-central1"
  network       = google_compute_network.main.id

  private_ip_google_access = true  # OK

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"  # OK: flow logs enabled
  }
}

resource "google_compute_subnetwork" "dmz" {
  name          = "dmz-subnet"
  ip_cidr_range = "10.1.1.0/24"
  region        = "us-central1"
  network       = google_compute_network.main.id

  # VIOLATION: no log_config (gcp_vpc_flow_logs)
  # VIOLATION: private_ip_google_access not set (gcp_vpc_private_google_access)
}

resource "google_compute_firewall" "allow_https" {
  name      = "allow-https-ingress"
  network   = google_compute_network.main.id
  direction = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  source_ranges = ["0.0.0.0/0"]

  log_config {
    metadata = "INCLUDE_ALL_METADATA"  # OK: firewall logging enabled
  }
}

resource "google_compute_firewall" "allow_ssh_open" {
  name      = "allow-ssh-all"
  network   = google_compute_network.main.id
  direction = "INGRESS"

  # VIOLATION: SSH open to the internet (gcp_firewall_no_wide_open_ingress)
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]

  # VIOLATION: no log_config (gcp_firewall_logging)
}

resource "google_compute_router" "main" {
  name    = "main-router"
  region  = "us-central1"
  network = google_compute_network.main.id
}

resource "google_compute_router_nat" "main" {
  name                               = "main-nat"
  router                             = google_compute_router.main.name
  region                             = "us-central1"
  nat_ip_allocate_option             = "AUTO_ONLY"                       # OK
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"  # OK
}

# -----------------------------------------------------------------------------
# GCP Compute Instances
# -----------------------------------------------------------------------------

resource "google_compute_disk" "data_disk" {
  name = "app-data-disk"
  type = "pd-ssd"
  zone = "us-central1-a"
  size = 100

  disk_encryption_key {
    kms_key_self_link = google_kms_crypto_key.app_key.id  # OK: CMEK
  }
}

resource "google_compute_disk" "unencrypted_disk" {
  name = "legacy-disk"
  type = "pd-standard"
  zone = "us-central1-a"
  size = 500

  # VIOLATION: no disk_encryption_key (gcp_compute_disk_encryption)
}

resource "google_compute_instance" "app_server" {
  name         = "app-server"
  machine_type = "n2-standard-4"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params { image = "debian-cloud/debian-12" }
  }

  network_interface {
    network    = google_compute_network.main.id
    subnetwork = google_compute_subnetwork.private.id
  }

  shielded_instance_config {
    enable_secure_boot          = true  # OK
    enable_vtpm                 = true  # OK
    enable_integrity_monitoring = true  # OK
  }

  labels = {
    environment = "production"
    owner       = "team-platform"
    project     = "core-infra"
  }
}

resource "google_compute_instance" "bastion" {
  name         = "bastion"
  machine_type = "e2-micro"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params { image = "debian-cloud/debian-12" }
  }

  network_interface {
    network    = google_compute_network.main.id
    subnetwork = google_compute_subnetwork.dmz.id

    # VIOLATION: external IP on production instance (gcp_compute_no_external_ip_prod)
    access_config {}
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  # VIOLATION: missing owner and project labels (gcp_compute_required_labels)
  labels = {
    environment = "production"
  }
}

resource "google_compute_instance" "analytics_worker" {
  name         = "analytics-worker"
  machine_type = "n2-highcpu-8"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params { image = "debian-cloud/debian-12" }
  }

  network_interface {
    network    = google_compute_network.main.id
    subnetwork = google_compute_subnetwork.private.id
  }

  # VIOLATION: Shielded VM not configured (gcp_compute_shielded_vm)

  labels = {
    environment = "production"
    owner       = "team-data"
    project     = "analytics"
  }
}

# -----------------------------------------------------------------------------
# GCP Cloud Storage
# -----------------------------------------------------------------------------

resource "google_storage_bucket" "secure_assets" {
  name                        = "my-company-secure-assets"
  location                    = "US"
  uniform_bucket_level_access = true       # OK
  public_access_prevention    = "enforced" # OK

  versioning {
    enabled = true  # OK
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.app_key.id  # OK: CMEK
  }

  logging {
    log_bucket = "my-company-access-logs"  # OK
  }

  lifecycle_rule {
    condition { age = 90 }
    action { type = "Delete" }
  }
}

resource "google_storage_bucket" "data_pipeline" {
  name     = "my-company-data-pipeline"
  location = "US"

  # VIOLATION: no uniform_bucket_level_access (gcp_storage_uniform_access)
  # VIOLATION: no public_access_prevention (gcp_storage_public_access_prevention)
  # VIOLATION: no versioning (gcp_storage_versioning)
  # VIOLATION: no encryption (gcp_storage_encryption)
  # VIOLATION: no logging (gcp_storage_access_logging)
  # VIOLATION: no lifecycle_rule (gcp_storage_lifecycle_policy)
}

# -----------------------------------------------------------------------------
# GCP Cloud SQL
# -----------------------------------------------------------------------------

resource "google_sql_database_instance" "primary" {
  name             = "prod-postgres-primary"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  encryption_key_name = google_kms_crypto_key.app_key.id  # OK: CMEK

  settings {
    tier = "db-n1-standard-4"

    ip_configuration {
      require_ssl  = true   # OK
      ipv4_enabled = false  # OK: no public IP
    }

    backup_configuration {
      enabled                        = true  # OK
      point_in_time_recovery_enabled = true  # OK
    }

    availability_type = "REGIONAL"  # OK: HA enabled

    user_labels = {
      environment = "production"
      owner       = "team-data"
    }
  }
}

resource "google_sql_database_instance" "analytics_db" {
  name             = "analytics-postgres"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    tier = "db-n1-standard-8"

    ip_configuration {
      require_ssl  = false  # VIOLATION: SSL not required (gcp_sql_ssl_required)
      ipv4_enabled = true   # VIOLATION: public IP enabled (gcp_sql_no_public_ip)
    }

    backup_configuration {
      enabled                        = false  # VIOLATION: no backups (gcp_sql_automated_backups)
      point_in_time_recovery_enabled = false  # VIOLATION
    }

    user_labels = {
      environment = "production"
    }
  }
}

# -----------------------------------------------------------------------------
# GCP IAM
# -----------------------------------------------------------------------------

resource "google_service_account" "app_sa" {
  account_id   = "app-service-account"
  display_name = "Application Service Account"  # OK
}

resource "google_service_account" "worker_sa" {
  account_id   = "worker-sa"
  # VIOLATION: display_name too short (gcp_service_account_display_name)
  display_name = "SA"
}

resource "google_service_account_key" "app_key" {
  service_account_id = google_service_account.app_sa.name
  # VIOLATION: user-managed key (gcp_service_account_no_user_managed_keys)
  key_type = "USER_MANAGED"
}

resource "google_project_iam_binding" "storage_viewer" {
  project = "my-gcp-project"
  role    = "roles/storage.objectViewer"  # OK: scoped role

  members = ["serviceAccount:${google_service_account.app_sa.email}"]
}

resource "google_project_iam_binding" "owner_binding" {
  project = "my-gcp-project"
  # VIOLATION: primitive Owner role (gcp_iam_no_primitive_roles)
  role = "roles/owner"

  members = ["user:admin@example.com"]
}

# -----------------------------------------------------------------------------
# GKE
# -----------------------------------------------------------------------------

resource "google_container_cluster" "prod" {
  name     = "prod-gke"
  location = "us-central1"

  remove_default_node_pool = true
  initial_node_count       = 1

  workload_identity_config {
    workload_pool = "my-gcp-project.svc.id.goog"  # OK: Workload Identity enabled
  }
}

resource "google_container_cluster" "staging" {
  name     = "staging-gke"
  location = "us-central1"

  remove_default_node_pool = true
  initial_node_count       = 1

  # VIOLATION: no workload_identity_config (gcp_gke_workload_identity)
}

# =============================================================================
# Kubernetes Resources
# =============================================================================

# -----------------------------------------------------------------------------
# Service Accounts
# -----------------------------------------------------------------------------

resource "kubernetes_service_account" "api_sa" {
  metadata {
    name      = "api-service-account"
    namespace = "app"  # OK: non-default namespace

    annotations = {
      "eks.amazonaws.com/role-arn" = "arn:aws:iam::123456789012:role/api-role"
    }
  }

  automount_service_account_token = false  # OK
}

resource "kubernetes_service_account" "legacy_sa" {
  metadata {
    name      = "legacy-worker"
    namespace = "default"  # VIOLATION (k8s_rbac_service_account_namespace)
  }

  # VIOLATION: automount_service_account_token not set (k8s_service_account_automount_token)
}

# -----------------------------------------------------------------------------
# RBAC
# -----------------------------------------------------------------------------

resource "kubernetes_cluster_role" "app_reader" {
  metadata { name = "app-reader" }

  rule {
    api_groups = [""]
    resources  = ["pods", "services", "configmaps"]
    verbs      = ["get", "list", "watch"]  # OK: specific verbs and resources
  }
}

resource "kubernetes_cluster_role" "broad_operator" {
  metadata { name = "broad-operator" }

  # VIOLATION: wildcard verbs and resources (k8s_rbac_no_wildcard_verbs, k8s_rbac_no_wildcard_resources)
  rule {
    api_groups = ["*"]
    resources  = ["*"]
    verbs      = ["*"]
  }
}

resource "kubernetes_cluster_role_binding" "monitoring" {
  metadata { name = "monitoring-reader" }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "app-reader"  # OK: not cluster-admin
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.api_sa.metadata[0].name
    namespace = "monitoring"
  }
}

resource "kubernetes_cluster_role_binding" "break_glass" {
  metadata { name = "break-glass-admin" }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    # VIOLATION: cluster-admin binding (k8s_rbac_no_cluster_admin)
    name = "cluster-admin"
  }

  subject {
    kind      = "User"
    name      = "on-call-engineer"
    api_group = "rbac.authorization.k8s.io"
  }
}

resource "kubernetes_role_binding" "app_namespace" {
  metadata {
    name      = "app-namespace-binding"
    namespace = "app"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"   # OK: namespace-scoped (k8s_rbac_namespace_scoped_preferred)
    name      = "app-reader"
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.api_sa.metadata[0].name
    namespace = "app"
  }
}

# -----------------------------------------------------------------------------
# Deployments
# -----------------------------------------------------------------------------

resource "kubernetes_deployment" "api_server" {
  metadata {
    name      = "api-server"
    namespace = "app"
    labels = {
      app         = "api-server"
      environment = "production"
    }
    annotations = {
      "trivy-operator.aquasecurity.github.io/report-ttl" = "24h"
      "cosign.sigstore.dev/signature"                    = "sha256:abc123def456"
      "runtime-security.io/monitored"                    = "true"
    }
  }

  spec {
    replicas = 3

    selector {
      match_labels = { app = "api-server" }
    }

    template {
      metadata {
        labels = {
          app         = "api-server"
          environment = "production"
        }
      }

      spec {
        host_network = false  # OK
        host_pid     = false  # OK
        host_ipc     = false  # OK

        service_account_name = kubernetes_service_account.api_sa.metadata[0].name

        container {
          name  = "api"
          image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/api-server:v1.2.3"

          image_pull_policy = "IfNotPresent"

          security_context {
            privileged                 = false  # OK
            run_as_non_root            = true   # OK
            run_as_user                = 1000   # OK
            read_only_root_filesystem  = true   # OK
            allow_privilege_escalation = false  # OK

            capabilities {
              drop = ["ALL"]  # OK
            }
          }

          resources {
            limits   = { cpu = "500m", memory = "256Mi" }
            requests = { cpu = "250m", memory = "128Mi" }
          }
        }
      }
    }
  }
}

resource "kubernetes_deployment" "batch_worker" {
  metadata {
    name      = "batch-worker"
    namespace = "app"
    labels    = { app = "batch-worker" }
  }

  spec {
    replicas = 2

    selector {
      match_labels = { app = "batch-worker" }
    }

    template {
      metadata {
        labels = { app = "batch-worker" }
      }

      spec {
        container {
          name  = "worker"
          # VIOLATION: latest tag + untrusted registry (k8s_no_latest_image_tag, k8s_trusted_registry_only)
          image = "my-internal-registry/worker:latest"

          security_context {
            privileged                 = true   # VIOLATION (k8s_no_privileged_containers)
            run_as_user                = 0      # VIOLATION: root (k8s_no_root_user)
            run_as_non_root            = false  # VIOLATION
            read_only_root_filesystem  = false  # VIOLATION (k8s_readonly_root_filesystem)
            allow_privilege_escalation = true   # VIOLATION (k8s_no_privilege_escalation)
          }

          # VIOLATION: no resource limits/requests (k8s_resource_limits, k8s_resource_requests)
        }
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Network Policies
# -----------------------------------------------------------------------------

resource "kubernetes_network_policy" "default_deny_ingress" {
  metadata {
    name      = "default-deny-ingress"
    namespace = "app"
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress"]  # OK: default deny ingress
  }
}

resource "kubernetes_network_policy" "allow_api" {
  metadata {
    name      = "allow-api-ingress"
    namespace = "app"
  }

  spec {
    pod_selector {
      match_labels = { app = "api-server" }
    }

    policy_types = ["Ingress"]

    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = "ingress-nginx"
          }
        }
      }

      ports {
        port     = "8080"
        protocol = "TCP"
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Services
# -----------------------------------------------------------------------------

resource "kubernetes_service" "api" {
  metadata {
    name      = "api-service"
    namespace = "app"
    labels    = { app = "api-server", environment = "production" }
  }

  spec {
    selector = { app = "api-server" }
    type     = "ClusterIP"  # OK: not NodePort in production

    port {
      port        = 80
      target_port = 8080
    }
  }
}

resource "kubernetes_service" "admin_console" {
  metadata {
    name      = "admin-console"
    namespace = "app"
    labels    = { app = "admin", environment = "production" }
  }

  spec {
    selector = { app = "admin" }
    # VIOLATION: NodePort in production (k8s_service_no_node_port)
    type = "NodePort"

    port {
      port        = 8080
      target_port = 8080
      node_port   = 30080
    }
  }
}

# -----------------------------------------------------------------------------
# Ingress
# -----------------------------------------------------------------------------

resource "kubernetes_ingress" "web" {
  metadata {
    name      = "web-ingress"
    namespace = "app"
    annotations = {
      "kubernetes.io/ingress.class" = "nginx"
    }
  }

  spec {
    tls {
      hosts       = ["app.example.com"]
      secret_name = "app-tls-secret"  # OK: TLS configured
    }

    rule {
      host = "app.example.com"

      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service.api.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }
}

# -----------------------------------------------------------------------------
# Secrets
# -----------------------------------------------------------------------------

resource "kubernetes_secret" "db_credentials" {
  metadata {
    name      = "db-credentials"
    namespace = "app"
    annotations = {
      "riveter.io/encryption-at-rest-verified"  = "true"
      "external-secrets.io/managed-by"          = "external-secrets-operator"
      "secret.kubernetes.io/rotation-time"      = "2026-04-30T00:00:00Z"
    }
  }

  immutable = true  # OK
  type      = "Opaque"
  data      = { username = base64encode("appuser") }
}

resource "kubernetes_secret" "api_keys" {
  metadata {
    name      = "api-keys"
    namespace = "app"
  }

  # VIOLATION: not immutable (k8s_secret_immutable)
  # VIOLATION: no external-secrets annotation (k8s_external_secrets_preferred)
  # VIOLATION: no rotation annotation (k8s_secret_rotation_annotation)
  # VIOLATION: no encryption-at-rest annotation (k8s_secret_encryption_at_rest)

  type = "Opaque"
  data = { stripe_key = base64encode("sk_live_abc123") }
}
