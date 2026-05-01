# Example Terraform configuration for Riveter scanning demos.
#
# Good test commands:
#   riveter scan -p aws-security -t examples/main.tf
#   riveter scan -p gcp-security -t examples/main.tf
#   riveter scan -p kubernetes-security -t examples/main.tf

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

# -----------------------------------------------------------------------------
# GCP Compute & Storage
# -----------------------------------------------------------------------------

resource "google_compute_instance" "web_server" {
  name         = "web-server"
  machine_type = "n2-standard-2"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    network = "default"
  }

  shielded_instance_config {
    enable_secure_boot          = true  # OK
    enable_vtpm                 = true  # OK
    enable_integrity_monitoring = true  # OK
  }

  labels = {
    environment = "production"
    owner       = "team-platform"
    project     = "demo"
  }
}

resource "google_compute_instance" "dev_instance" {
  name         = "dev-instance"
  machine_type = "e2-medium"
  zone         = "us-central1-a"

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    network = "default"
    # VIOLATION: external IP on a production-labelled instance (gcp_compute_no_external_ip_prod)
    access_config {}
  }

  # VIOLATION: Shielded VM not configured (gcp_compute_shielded_vm)

  # VIOLATION: missing owner and project labels (gcp_compute_required_labels)
  labels = {
    environment = "production"
  }
}

resource "google_storage_bucket" "assets" {
  name                        = "my-company-assets"
  location                    = "US"
  uniform_bucket_level_access = true       # OK
  public_access_prevention    = "enforced" # OK

  versioning {
    enabled = true  # OK
  }

  lifecycle_rule {
    condition { age = 365 }
    action { type = "Delete" }
  }
}

resource "google_storage_bucket" "staging_bucket" {
  name     = "my-company-staging"
  location = "US"

  # VIOLATION: uniform_bucket_level_access not set (gcp_storage_uniform_access)
  # VIOLATION: public_access_prevention not set (gcp_storage_public_access_prevention)
  # VIOLATION: no versioning (gcp_storage_versioning)
  # VIOLATION: no lifecycle_rule (gcp_storage_lifecycle_policy)
}

# -----------------------------------------------------------------------------
# GCP Cloud SQL
# -----------------------------------------------------------------------------

resource "google_sql_database_instance" "main" {
  name             = "prod-db"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    tier = "db-n1-standard-2"

    ip_configuration {
      require_ssl  = true   # OK
      ipv4_enabled = false  # OK: no public IP
    }

    backup_configuration {
      enabled                        = true  # OK
      point_in_time_recovery_enabled = true  # OK
    }
  }
}

resource "google_sql_database_instance" "dev_db" {
  name             = "dev-db"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    tier = "db-f1-micro"

    ip_configuration {
      require_ssl  = false  # VIOLATION: SSL not required (gcp_sql_ssl_required)
      ipv4_enabled = true   # VIOLATION: public IP enabled (gcp_sql_no_public_ip)
    }

    backup_configuration {
      enabled = false  # VIOLATION: no backups (gcp_sql_automated_backups)
    }
  }
}

# -----------------------------------------------------------------------------
# Kubernetes Workloads
# -----------------------------------------------------------------------------

resource "kubernetes_deployment" "api" {
  metadata {
    name      = "api-server"
    namespace = "app"
    labels = {
      app         = "api-server"
      environment = "production"
    }
  }

  spec {
    replicas = 2

    selector {
      match_labels = { app = "api-server" }
    }

    template {
      metadata {
        labels = { app = "api-server" }
      }

      spec {
        host_network = false  # OK
        host_pid     = false  # OK
        host_ipc     = false  # OK

        container {
          name  = "api"
          image = "123456789012.dkr.ecr.us-east-1.amazonaws.com/api:v1.0.0"

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

resource "kubernetes_deployment" "worker" {
  metadata {
    name      = "batch-worker"
    namespace = "app"
    labels    = { app = "worker" }
  }

  spec {
    replicas = 1

    selector {
      match_labels = { app = "worker" }
    }

    template {
      metadata {
        labels = { app = "worker" }
      }

      spec {
        container {
          name  = "worker"
          image = "my-worker:latest"  # VIOLATION: latest tag (k8s_no_latest_image_tag + k8s_trusted_registry_only)

          security_context {
            privileged                 = true   # VIOLATION (k8s_no_privileged_containers)
            run_as_user                = 0      # VIOLATION: root (k8s_no_root_user)
            run_as_non_root            = false  # VIOLATION
            read_only_root_filesystem  = false  # VIOLATION (k8s_readonly_root_filesystem)
            allow_privilege_escalation = true   # VIOLATION (k8s_no_privilege_escalation)
          }

          # VIOLATION: no resource limits or requests (k8s_resource_limits, k8s_resource_requests)
        }
      }
    }
  }
}

resource "kubernetes_service_account" "app_sa" {
  metadata {
    name      = "app-sa"
    namespace = "app"  # OK: non-default namespace
  }

  automount_service_account_token = false  # OK
}

resource "kubernetes_service_account" "legacy_sa" {
  metadata {
    name      = "legacy"
    namespace = "default"  # VIOLATION (k8s_rbac_service_account_namespace)
  }

  # VIOLATION: automount_service_account_token not set (k8s_service_account_automount_token)
}

resource "kubernetes_cluster_role_binding" "admin" {
  metadata { name = "break-glass-admin" }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "cluster-admin"  # VIOLATION (k8s_rbac_no_cluster_admin)
  }

  subject {
    kind      = "User"
    name      = "on-call-engineer"
    api_group = "rbac.authorization.k8s.io"
  }
}

resource "kubernetes_network_policy" "default_deny" {
  metadata {
    name      = "default-deny-all"
    namespace = "app"
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]  # OK: default deny all traffic
  }
}
