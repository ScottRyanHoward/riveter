# Example Terraform configuration for Riveter scanning demos.
# Run: riveter scan -p aws-security -t examples/main.tf

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
# EC2 Instance — intentional violations for demo purposes
# -----------------------------------------------------------------------------

resource "aws_instance" "web_server" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.large"  # OK: approved instance type

  # VIOLATION: public IP enabled in production
  associate_public_ip_address = true

  root_block_device {
    volume_size = 50
    encrypted   = true  # OK: encryption enabled
  }

  tags = {
    Environment = "production"
    Owner       = "team-platform"
    Project     = "demo"
  }
}

resource "aws_instance" "worker" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t2.micro"  # VIOLATION: unapproved instance type

  root_block_device {
    volume_size = 20
    encrypted   = false  # VIOLATION: encryption disabled
  }

  # VIOLATION: missing required tags (Owner, Project)
  tags = {
    Environment = "production"
  }
}

# -----------------------------------------------------------------------------
# S3 Bucket — intentional violations for demo purposes
# -----------------------------------------------------------------------------

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
    status = "Enabled"  # OK
  }
}

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------

resource "aws_security_group" "web_sg" {
  name        = "web-sg"
  description = "Security group for web servers"
  vpc_id      = "vpc-12345678"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # VIOLATION: SSH open to internet
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
