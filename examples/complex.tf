# Complex Terraform configuration for Riveter scanning demos.
#
# Covers a realistic multi-tier AWS stack with intentional violations
# mixed in alongside correctly-configured resources.
#
# Good test commands:
#   riveter scan -p aws-security -t examples/complex.tf
#   riveter scan -p aws-security -p cis-aws -t examples/complex.tf
#   riveter scan -p aws-security -t examples/complex.tf -f html > report.html
#   riveter scan -p aws-security -t examples/complex.tf --include-rules "*s3*"

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
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
