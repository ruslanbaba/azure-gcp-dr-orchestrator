# Security Hardened Terraform Configuration for Enhanced DR Orchestrator
# Incorporates Canary Failover, Workload Identity, and Defense in Depth

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
}

# Variables for Security Hardened Configuration
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "GKE Cluster Name"
  type        = string
  default     = "dr-gke-secure"
}

variable "nodepool_name" {
  description = "GKE Nodepool Name"
  type        = string
  default     = "secure-workload-pool"
}

variable "min_nodes" {
  description = "Minimum nodes for cold standby"
  type        = number
  default     = 0
}

variable "max_nodes" {
  description = "Maximum nodes for scaling"
  type        = number
  default     = 10
}

variable "canary_replicas" {
  description = "Number of canary replicas"
  type        = number
  default     = 1
}

variable "full_scale_replicas" {
  description = "Number of full scale replicas"
  type        = number
  default     = 3
}

variable "dns_zone_name" {
  description = "Cloud DNS Zone Name"
  type        = string
  default     = "dr-zone"
}

variable "dns_domain" {
  description = "DNS Domain"
  type        = string
  default     = "example.com."
}

variable "app_record_name" {
  description = "Application DNS record name"
  type        = string
  default     = "app"
}

variable "azure_health_endpoint" {
  description = "Azure health check endpoint"
  type        = string
  default     = "https://primary.example.com/healthz"
}

variable "fail_threshold" {
  description = "Consecutive failure threshold"
  type        = number
  default     = 3
}

# Local values for resource naming and configuration
locals {
  common_labels = {
    project     = "azure-gcp-dr-orchestrator"
    environment = "production"
    managed-by  = "terraform"
    security    = "hardened"
  }
  
  service_account_roles = [
    "roles/container.admin",
    "roles/dns.admin",
    "roles/secretmanager.secretAccessor",
    "roles/monitoring.metricWriter",
    "roles/compute.viewer",
    "roles/pubsub.subscriber",
    "roles/cloudsql.client"
  ]
}

# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "container.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudscheduler.googleapis.com",
    "pubsub.googleapis.com",
    "dns.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com",
    "compute.googleapis.com",
    "cloudsql.googleapis.com",
    "sqladmin.googleapis.com",
    "eventarc.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com"
  ])

  project = var.project_id
  service = each.value

  disable_dependent_services = false
  disable_on_destroy         = false
}

# VPC for secure networking
resource "google_compute_network" "dr_vpc" {
  name                    = "dr-vpc-secure"
  auto_create_subnetworks = false
  
  depends_on = [google_project_service.required_apis]
}

# Private subnet for GKE
resource "google_compute_subnetwork" "gke_subnet" {
  name                     = "gke-subnet-secure"
  ip_cidr_range           = "10.0.0.0/16"
  region                  = var.region
  network                 = google_compute_network.dr_vpc.id
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.1.0.0/16"
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.2.0.0/16"
  }
}

# Private subnet for Cloud SQL
resource "google_compute_subnetwork" "sql_subnet" {
  name          = "sql-subnet-secure"
  ip_cidr_range = "10.10.0.0/24"
  region        = var.region
  network       = google_compute_network.dr_vpc.id
  private_ip_google_access = true
}

# NAT Gateway for secure egress
resource "google_compute_router" "nat_router" {
  name    = "nat-router"
  region  = var.region
  network = google_compute_network.dr_vpc.id
}

resource "google_compute_router_nat" "nat_gateway" {
  name                               = "nat-gateway"
  router                            = google_compute_router.nat_router.name
  region                            = var.region
  nat_ip_allocate_option            = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Private Google Access
resource "google_compute_global_address" "private_ip_range" {
  name          = "private-ip-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.dr_vpc.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.dr_vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]

  depends_on = [google_project_service.required_apis]
}

# Security-hardened GKE cluster
resource "google_container_cluster" "secure_dr_cluster" {
  name     = var.cluster_name
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1

  network    = google_compute_network.dr_vpc.name
  subnetwork = google_compute_subnetwork.gke_subnet.name

  # Enable private cluster
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }

  # IP allocation for pods and services
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Network policy
  network_policy {
    enabled  = true
    provider = "CALICO"
  }

  # Enable Workload Identity
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Security configurations
  enable_shielded_nodes = true
  
  master_auth {
    client_certificate_config {
      issue_client_certificate = false
    }
  }

  # Enable network policy enforcement
  addons_config {
    network_policy_config {
      disabled = false
    }
    
    horizontal_pod_autoscaling {
      disabled = false
    }
    
    istio_config {
      disabled = false
      auth     = "AUTH_MUTUAL_TLS"
    }
  }

  # Binary authorization
  enable_binary_authorization = true

  # Pod security policy
  pod_security_policy_config {
    enabled = true
  }

  # Resource usage export
  resource_usage_export_config {
    enable_network_egress_metering = true
    bigquery_destination {
      dataset_id = google_bigquery_dataset.gke_usage.dataset_id
    }
  }

  # Maintenance policy
  maintenance_policy {
    daily_maintenance_window {
      start_time = "03:00"
    }
  }

  depends_on = [
    google_project_service.required_apis,
    google_service_networking_connection.private_vpc_connection
  ]
}

# Security-hardened node pool
resource "google_container_node_pool" "secure_workload_pool" {
  name       = var.nodepool_name
  location   = var.region
  cluster    = google_container_cluster.secure_dr_cluster.name

  autoscaling {
    min_node_count = var.min_nodes
    max_node_count = var.max_nodes
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type = "e2-standard-4"
    disk_type    = "pd-ssd"
    disk_size_gb = 50

    # Enable secure boot and integrity monitoring
    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    # Workload Identity
    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    # OAuth scopes
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]

    # Security settings
    service_account = google_service_account.gke_nodes.email

    labels = merge(local.common_labels, {
      role = "workload"
    })

    tags = ["gke-node", "secure"]

    # Restrict metadata access
    metadata = {
      disable-legacy-endpoints = "true"
    }
  }

  # Node pool upgrade settings
  upgrade_settings {
    max_surge       = 1
    max_unavailable = 0
  }

  depends_on = [google_project_service.required_apis]
}

# Service account for GKE nodes
resource "google_service_account" "gke_nodes" {
  account_id   = "gke-nodes-sa"
  display_name = "GKE Nodes Service Account"
}

# Minimal IAM bindings for GKE nodes
resource "google_project_iam_member" "gke_nodes_roles" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/monitoring.viewer",
    "roles/stackdriver.resourceMetadata.writer"
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

# Service account for DR orchestrator
resource "google_service_account" "dr_orchestrator" {
  account_id   = "dr-orchestrator-sa"
  display_name = "DR Orchestrator Service Account"
}

# IAM bindings for DR orchestrator
resource "google_project_iam_member" "dr_orchestrator_roles" {
  for_each = toset(local.service_account_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.dr_orchestrator.email}"
}

# Workload Identity binding
resource "google_service_account_iam_binding" "workload_identity_binding" {
  service_account_id = google_service_account.dr_orchestrator.name
  role               = "roles/iam.workloadIdentityUser"

  members = [
    "serviceAccount:${var.project_id}.svc.id.goog[dr-system/dr-app-service-account]"
  ]
}

# Cloud SQL instance with security hardening
resource "google_sql_database_instance" "secure_dr_postgres" {
  name             = "secure-dr-postgres"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier              = "db-custom-2-7680"
    availability_type = "REGIONAL"
    disk_type         = "PD_SSD"
    disk_size         = 100
    disk_autoresize   = true

    # Backup configuration
    backup_configuration {
      enabled                        = true
      start_time                     = "02:00"
      point_in_time_recovery_enabled = true
      location                       = var.region
      
      backup_retention_settings {
        retained_backups = 30
        retention_unit   = "COUNT"
      }
    }

    # IP configuration for private access
    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.dr_vpc.id
      enable_private_path_for_google_cloud_services = true
      require_ssl                                   = true
    }

    # Database flags for security
    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }
    
    database_flags {
      name  = "log_connections"
      value = "on"
    }
    
    database_flags {
      name  = "log_disconnections"
      value = "on"
    }
    
    database_flags {
      name  = "log_lock_waits"
      value = "on"
    }
    
    database_flags {
      name  = "log_statement"
      value = "all"
    }

    # Maintenance window
    maintenance_window {
      day  = 7
      hour = 3
    }

    user_labels = local.common_labels
  }

  # Deletion protection
  deletion_protection = true

  depends_on = [
    google_service_networking_connection.private_vpc_connection
  ]
}

# Database and user
resource "google_sql_database" "dr_app_db" {
  name     = "dr_app_db"
  instance = google_sql_database_instance.secure_dr_postgres.name
}

resource "google_sql_user" "app_user" {
  name     = "app_user"
  instance = google_sql_database_instance.secure_dr_postgres.name
  password = random_password.db_password.result
}

resource "random_password" "db_password" {
  length  = 32
  special = true
}

# Store database credentials in Secret Manager
resource "google_secret_manager_secret" "db_password" {
  secret_id = "dr-app-db-password"

  replication {
    auto {}
  }

  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}

# Database URL secret
resource "google_secret_manager_secret" "db_url" {
  secret_id = "dr-app-database-url"

  replication {
    auto {}
  }

  labels = local.common_labels
}

resource "google_secret_manager_secret_version" "db_url" {
  secret = google_secret_manager_secret.db_url.id
  secret_data = "postgresql://${google_sql_user.app_user.name}:${random_password.db_password.result}@${google_sql_database_instance.secure_dr_postgres.private_ip_address}:5432/${google_sql_database.dr_app_db.name}?sslmode=require"
}

# Pub/Sub topic for failover orchestration
resource "google_pubsub_topic" "failover_trigger" {
  name = "dr-failover-trigger"

  labels = local.common_labels

  depends_on = [google_project_service.required_apis]
}

# Static IP for load balancer
resource "google_compute_global_address" "dr_static_ip" {
  name         = "dr-gcp-ip"
  address_type = "EXTERNAL"
}

# Cloud DNS zone
resource "google_dns_managed_zone" "dr_zone" {
  name        = var.dns_zone_name
  dns_name    = var.dns_domain
  description = "DR Orchestrator DNS Zone"

  dnssec_config {
    state = "on"
  }

  labels = local.common_labels

  depends_on = [google_project_service.required_apis]
}

# Initial DNS record (placeholder)
resource "google_dns_record_set" "app_record" {
  name         = "${var.app_record_name}.${google_dns_managed_zone.dr_zone.dns_name}"
  managed_zone = google_dns_managed_zone.dr_zone.name
  type         = "A"
  ttl          = 60
  rrdatas      = [google_compute_global_address.dr_static_ip.address]
}

# BigQuery dataset for GKE resource usage
resource "google_bigquery_dataset" "gke_usage" {
  dataset_id  = "gke_usage_metering"
  description = "GKE resource usage data"
  location    = "US"

  labels = local.common_labels

  depends_on = [google_project_service.required_apis]
}

# Cloud Function storage bucket
resource "google_storage_bucket" "functions_source" {
  name     = "${var.project_id}-dr-functions-source"
  location = var.region

  uniform_bucket_level_access = true
  
  versioning {
    enabled = true
  }

  labels = local.common_labels

  depends_on = [google_project_service.required_apis]
}

# Archive canary failover function
data "archive_file" "canary_failover_source" {
  type        = "zip"
  source_dir  = "../../cloud-functions/canary-failover"
  output_path = "/tmp/canary-failover.zip"
}

resource "google_storage_bucket_object" "canary_failover_source" {
  name   = "canary-failover-${data.archive_file.canary_failover_source.output_md5}.zip"
  bucket = google_storage_bucket.functions_source.name
  source = data.archive_file.canary_failover_source.output_path
}

# Enhanced probe function
resource "google_cloudfunctions2_function" "azure_health_probe" {
  name        = "azure-health-probe-secure"
  location    = var.region
  description = "Security-hardened Azure health probe"

  build_config {
    runtime     = "python311"
    entry_point = "probe_azure_health"
    
    source {
      storage_source {
        bucket = google_storage_bucket.functions_source.name
        object = "probe-function.zip"  # You would need to create this
      }
    }
  }

  service_config {
    min_instance_count               = 0
    max_instance_count               = 10
    available_memory                 = "256M"
    timeout_seconds                  = 30
    max_instance_request_concurrency = 1
    
    environment_variables = {
      AZURE_HEALTH_URL = var.azure_health_endpoint
      FAIL_THRESHOLD   = var.fail_threshold
      PUBSUB_TOPIC     = google_pubsub_topic.failover_trigger.name
      PROJECT_ID       = var.project_id
    }

    service_account_email = google_service_account.dr_orchestrator.email

    ingress_settings = "ALLOW_INTERNAL_ONLY"
    
    vpc_connector_egress_settings = "PRIVATE_RANGES_ONLY"
  }

  depends_on = [
    google_project_service.required_apis,
    google_storage_bucket_object.canary_failover_source
  ]
}

# Canary failover function
resource "google_cloudfunctions2_function" "canary_failover" {
  name        = "canary-failover-orchestrator"
  location    = var.region
  description = "Security-hardened canary failover orchestrator"

  build_config {
    runtime     = "python311"
    entry_point = "handle_pubsub_failover"
    
    source {
      storage_source {
        bucket = google_storage_bucket.functions_source.name
        object = google_storage_bucket_object.canary_failover_source.name
      }
    }
  }

  service_config {
    min_instance_count               = 0
    max_instance_count               = 5
    available_memory                 = "2Gi"
    timeout_seconds                  = 540
    max_instance_request_concurrency = 1
    
    environment_variables = {
      PROJECT_ID            = var.project_id
      CLUSTER_NAME          = google_container_cluster.secure_dr_cluster.name
      GKE_LOCATION          = var.region
      NODEPOOL_NAME         = google_container_node_pool.secure_workload_pool.name
      CANARY_REPLICAS       = var.canary_replicas
      FULL_SCALE_REPLICAS   = var.full_scale_replicas
      DNS_ZONE              = google_dns_managed_zone.dr_zone.name
      DNS_RECORD            = var.app_record_name
      STATIC_IP_NAME        = google_compute_global_address.dr_static_ip.name
    }

    service_account_email = google_service_account.dr_orchestrator.email
    
    ingress_settings = "ALLOW_INTERNAL_ONLY"
    
    vpc_connector_egress_settings = "PRIVATE_RANGES_ONLY"
  }

  depends_on = [
    google_project_service.required_apis,
    google_storage_bucket_object.canary_failover_source
  ]
}

# Eventarc trigger for Pub/Sub
resource "google_eventarc_trigger" "failover_trigger" {
  name     = "failover-pubsub-trigger"
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.pubsub.topic.v1.messagePublished"
  }

  transport {
    pubsub {
      topic = google_pubsub_topic.failover_trigger.id
    }
  }

  destination {
    cloud_function {
      function = google_cloudfunctions2_function.canary_failover.id
    }
  }

  service_account = google_service_account.dr_orchestrator.email

  depends_on = [google_project_service.required_apis]
}

# Cloud Scheduler for health checks
resource "google_cloud_scheduler_job" "health_probe" {
  name             = "azure-health-probe-job"
  description      = "Periodic Azure health check"
  schedule         = "*/1 * * * *"  # Every minute
  time_zone        = "UTC"
  region           = var.region

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.azure_health_probe.service_config[0].uri

    oidc_token {
      service_account_email = google_service_account.dr_orchestrator.email
    }
  }

  retry_config {
    retry_count = 3
  }

  depends_on = [google_project_service.required_apis]
}

# Monitoring and alerting
resource "google_monitoring_notification_channel" "email" {
  display_name = "DR Orchestrator Alerts"
  type         = "email"
  
  labels = {
    email_address = "dr-team@example.com"  # Replace with actual email
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_monitoring_alert_policy" "failover_alert" {
  display_name = "DR Failover Initiated"
  combiner     = "OR"

  conditions {
    display_name = "Failover function execution"
    
    condition_threshold {
      filter          = "resource.type=\"cloud_function\" AND resource.labels.function_name=\"${google_cloudfunctions2_function.canary_failover.name}\""
      duration        = "60s"
      comparison      = "COMPARISON_GREATER_THAN"
      threshold_value = 0
      
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]

  depends_on = [google_project_service.required_apis]
}

# Outputs
output "cluster_name" {
  description = "GKE cluster name"
  value       = google_container_cluster.secure_dr_cluster.name
}

output "cluster_endpoint" {
  description = "GKE cluster endpoint"
  value       = google_container_cluster.secure_dr_cluster.endpoint
  sensitive   = true
}

output "static_ip" {
  description = "Static IP address for load balancer"
  value       = google_compute_global_address.dr_static_ip.address
}

output "dns_zone_name_servers" {
  description = "DNS zone name servers"
  value       = google_dns_managed_zone.dr_zone.name_servers
}

output "database_connection_name" {
  description = "Cloud SQL connection name"
  value       = google_sql_database_instance.secure_dr_postgres.connection_name
}

output "service_account_email" {
  description = "DR orchestrator service account email"
  value       = google_service_account.dr_orchestrator.email
}

output "pubsub_topic" {
  description = "Failover trigger Pub/Sub topic"
  value       = google_pubsub_topic.failover_trigger.name
}
