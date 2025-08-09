# GCP Infrastructure for Cross-Cloud DR Orchestrator
# Enterprise-grade hardcoded infrastructure setup

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
  
  backend "gcs" {
    bucket = "dr-orchestrator-terraform-state"
    prefix = "gcp-infrastructure"
  }
}

provider "google" {
  project = local.project_id
  region  = local.region
  zone    = local.zone
}

provider "google-beta" {
  project = local.project_id
  region  = local.region
  zone    = local.zone
}

# Hardcoded enterprise variables
locals {
  # Enterprise standardized naming
  project_id          = "enterprise-dr-orchestrator"
  enterprise_prefix   = "prod-dr"
  environment        = "production"
  region             = "us-central1"
  zone               = "us-central1-a"
  backup_region      = "us-east1"
  backup_zone        = "us-east1-a"
  
  # Resource naming conventions
  vpc_name           = "${local.enterprise_prefix}-vpc"
  subnet_name        = "${local.enterprise_prefix}-subnet"
  gke_cluster_name   = "${local.enterprise_prefix}-gke-cluster"
  cloud_sql_name     = "${local.enterprise_prefix}-cloud-sql"
  service_account    = "${local.enterprise_prefix}-sa"
  
  # Enterprise labels
  common_labels = {
    environment         = local.environment
    project            = "cross-cloud-dr"
    owner              = "enterprise-ops-team"
    cost-center        = "it-infrastructure"
    business-unit      = "technology-services"
    compliance         = "soc2-type-ii"
    backup-required    = "yes"
    monitoring-enabled = "yes"
    disaster-recovery  = "critical"
  }
  
  # Network configuration
  vpc_cidr           = "10.1.0.0/16"
  subnet_cidr        = "10.1.1.0/24"
  pods_cidr          = "10.1.32.0/19"
  services_cidr      = "10.1.64.0/19"
  
  # GKE configuration
  gke_config = {
    kubernetes_version    = "1.27.7-gke.1121000"
    initial_node_count   = 3
    min_node_count       = 2
    max_node_count       = 10
    machine_type         = "e2-standard-4"
    disk_size_gb         = 100
    disk_type            = "pd-ssd"
    preemptible          = false
  }
  
  # Cloud SQL configuration
  cloud_sql_config = {
    tier                 = "db-n1-standard-4"
    disk_size           = 100
    disk_type           = "PD_SSD"
    availability_type   = "REGIONAL"
    backup_enabled      = true
    binary_log_enabled  = true
    point_in_time_recovery = true
  }
}

# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "compute.googleapis.com",
    "container.googleapis.com",
    "sqladmin.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "pubsub.googleapis.com",
    "cloudscheduler.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
    "run.googleapis.com"
  ])
  
  project = local.project_id
  service = each.value
  
  disable_dependent_services = true
}

# VPC Network
resource "google_compute_network" "main" {
  name                    = local.vpc_name
  auto_create_subnetworks = false
  mtu                     = 1460
  
  depends_on = [google_project_service.required_apis]
}

# Subnet
resource "google_compute_subnetwork" "main" {
  name                     = local.subnet_name
  network                  = google_compute_network.main.id
  ip_cidr_range           = local.subnet_cidr
  region                  = local.region
  private_ip_google_access = true
  
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = local.pods_cidr
  }
  
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = local.services_cidr
  }
}

# Cloud Router for NAT
resource "google_compute_router" "main" {
  name    = "${local.enterprise_prefix}-router"
  network = google_compute_network.main.id
  region  = local.region
}

# Cloud NAT
resource "google_compute_router_nat" "main" {
  name   = "${local.enterprise_prefix}-nat"
  router = google_compute_router.main.name
  region = google_compute_router.main.region
  
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Firewall rules
resource "google_compute_firewall" "allow_internal" {
  name    = "${local.enterprise_prefix}-allow-internal"
  network = google_compute_network.main.name
  
  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }
  
  allow {
    protocol = "icmp"
  }
  
  source_ranges = [local.vpc_cidr, local.pods_cidr, local.services_cidr]
}

resource "google_compute_firewall" "allow_ssh" {
  name    = "${local.enterprise_prefix}-allow-ssh"
  network = google_compute_network.main.name
  
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["ssh-allowed"]
}

resource "google_compute_firewall" "allow_http_https" {
  name    = "${local.enterprise_prefix}-allow-http-https"
  network = google_compute_network.main.name
  
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["http-server", "https-server"]
}

# Service Account for GKE nodes
resource "google_service_account" "gke_nodes" {
  account_id   = "${local.enterprise_prefix}-gke-nodes"
  display_name = "GKE Nodes Service Account"
  description  = "Service account for GKE cluster nodes"
}

# IAM bindings for GKE service account
resource "google_project_iam_member" "gke_nodes_storage" {
  project = local.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_logging" {
  project = local.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_monitoring" {
  project = local.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_monitoring_viewer" {
  project = local.project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

# GKE Cluster
resource "google_container_cluster" "main" {
  name     = local.gke_cluster_name
  location = local.region
  
  # Use regional cluster for high availability
  node_locations = [
    "${local.region}-a",
    "${local.region}-b",
    "${local.region}-c"
  ]
  
  network    = google_compute_network.main.name
  subnetwork = google_compute_subnetwork.main.name
  
  # We can't create a cluster with no node pool defined, but we want to only use
  # separately managed node pools. So we create the smallest possible default
  # node pool and immediately delete it.
  remove_default_node_pool = true
  initial_node_count       = 1
  
  # Networking configuration
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
    workload_pool = "${local.project_id}.svc.id.goog"
  }
  
  # Enable Shielded Nodes
  enable_shielded_nodes = true
  
  # Maintenance policy
  maintenance_policy {
    recurring_window {
      start_time = "2023-01-01T09:00:00Z"
      end_time   = "2023-01-01T17:00:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=SA,SU"
    }
  }
  
  # Binary authorization
  binary_authorization {
    evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE"
  }
  
  # Cluster autoscaling
  cluster_autoscaling {
    enabled = true
    
    resource_limits {
      resource_type = "cpu"
      minimum       = 4
      maximum       = 100
    }
    
    resource_limits {
      resource_type = "memory"
      minimum       = 16
      maximum       = 400
    }
    
    auto_provisioning_defaults {
      service_account = google_service_account.gke_nodes.email
      oauth_scopes = [
        "https://www.googleapis.com/auth/cloud-platform"
      ]
      
      shielded_instance_config {
        enable_secure_boot          = true
        enable_integrity_monitoring = true
      }
    }
  }
  
  # Logging and monitoring
  logging_service    = "logging.googleapis.com/kubernetes"
  monitoring_service = "monitoring.googleapis.com/kubernetes"
  
  # Addons
  addons_config {
    http_load_balancing {
      disabled = false
    }
    
    horizontal_pod_autoscaling {
      disabled = false
    }
    
    network_policy_config {
      disabled = false
    }
    
    gcp_filestore_csi_driver_config {
      enabled = true
    }
    
    gcs_fuse_csi_driver_config {
      enabled = true
    }
  }
  
  depends_on = [
    google_project_service.required_apis,
    google_project_iam_member.gke_nodes_storage,
    google_project_iam_member.gke_nodes_logging,
    google_project_iam_member.gke_nodes_monitoring,
    google_project_iam_member.gke_nodes_monitoring_viewer,
  ]
}

# GKE Node Pool
resource "google_container_node_pool" "main" {
  name       = "${local.enterprise_prefix}-node-pool"
  location   = local.region
  cluster    = google_container_cluster.main.name
  
  initial_node_count = local.gke_config.initial_node_count
  
  autoscaling {
    min_node_count = local.gke_config.min_node_count
    max_node_count = local.gke_config.max_node_count
  }
  
  management {
    auto_repair  = true
    auto_upgrade = true
  }
  
  upgrade_settings {
    strategy      = "SURGE"
    max_surge     = 1
    max_unavailable = 0
  }
  
  node_config {
    machine_type = local.gke_config.machine_type
    disk_size_gb = local.gke_config.disk_size_gb
    disk_type    = local.gke_config.disk_type
    preemptible  = local.gke_config.preemptible
    
    service_account = google_service_account.gke_nodes.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
    
    labels = local.common_labels
    
    tags = ["gke-node", "${local.enterprise_prefix}-gke"]
    
    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
    
    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}

# Private Service Connection for Cloud SQL
resource "google_compute_global_address" "private_ip_range" {
  name          = "${local.enterprise_prefix}-private-ip-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
  
  depends_on = [google_project_service.required_apis]
}

# Cloud SQL Instance
resource "google_sql_database_instance" "main" {
  name             = local.cloud_sql_name
  database_version = "POSTGRES_15"
  region           = local.region
  
  deletion_protection = true
  
  settings {
    tier                        = local.cloud_sql_config.tier
    disk_size                   = local.cloud_sql_config.disk_size
    disk_type                   = local.cloud_sql_config.disk_type
    disk_autoresize            = true
    disk_autoresize_limit      = 500
    availability_type          = local.cloud_sql_config.availability_type
    deletion_protection_enabled = true
    
    user_labels = local.common_labels
    
    backup_configuration {
      enabled                        = local.cloud_sql_config.backup_enabled
      start_time                     = "03:00"
      point_in_time_recovery_enabled = local.cloud_sql_config.point_in_time_recovery
      backup_retention_settings {
        retained_backups = 30
        retention_unit   = "COUNT"
      }
      
      transaction_log_retention_days = 7
    }
    
    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.main.id
      enable_private_path_for_google_cloud_services = true
      
      authorized_networks {
        name  = "internal-network"
        value = local.vpc_cidr
      }
    }
    
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
      name  = "log_min_duration_statement"
      value = "1000"
    }
    
    database_flags {
      name  = "log_temp_files"
      value = "0"
    }
    
    maintenance_window {
      day          = 7
      hour         = 3
      update_track = "stable"
    }
    
    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
      record_client_address   = true
    }
  }
  
  depends_on = [
    google_service_networking_connection.private_vpc_connection,
    google_project_service.required_apis
  ]
}

# Cloud SQL Database
resource "google_sql_database" "main" {
  name     = "enterprise_app_db"
  instance = google_sql_database_instance.main.name
}

# Cloud SQL User
resource "google_sql_user" "main" {
  name     = "postgres"
  instance = google_sql_database_instance.main.name
  password = var.gcp_sql_user_password
}

# Service Account for Cloud Functions
resource "google_service_account" "cloud_functions" {
  account_id   = "${local.enterprise_prefix}-cf-sa"
  display_name = "Cloud Functions Service Account"
  description  = "Service account for Cloud Functions DR orchestrator"
}

# IAM bindings for Cloud Functions service account
resource "google_project_iam_member" "cloud_functions_developer" {
  project = local.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}

resource "google_project_iam_member" "cloud_functions_container_developer" {
  project = local.project_id
  role    = "roles/container.developer"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}

resource "google_project_iam_member" "cloud_functions_logging" {
  project = local.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}

resource "google_project_iam_member" "cloud_functions_monitoring" {
  project = local.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}

resource "google_project_iam_member" "cloud_functions_pubsub" {
  project = local.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}

resource "google_project_iam_member" "cloud_functions_secret_accessor" {
  project = local.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_functions.email}"
}

# Storage bucket for Cloud Functions source code
resource "google_storage_bucket" "cloud_functions_source" {
  name     = "${local.project_id}-cf-source-${random_string.bucket_suffix.result}"
  location = local.region
  
  versioning {
    enabled = true
  }
  
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
  
  labels = local.common_labels
}

resource "random_string" "bucket_suffix" {
  length  = 8
  special = false
  upper   = false
}

# Storage bucket for monitoring data
resource "google_storage_bucket" "monitoring" {
  name     = "${local.project_id}-monitoring-${random_string.bucket_suffix.result}"
  location = local.region
  
  versioning {
    enabled = true
  }
  
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
  
  labels = local.common_labels
}

# Pub/Sub topic for DR events
resource "google_pubsub_topic" "dr_events" {
  name = "${local.enterprise_prefix}-dr-events"
  
  labels = local.common_labels
}

# Pub/Sub subscription for DR events
resource "google_pubsub_subscription" "dr_events" {
  name  = "${local.enterprise_prefix}-dr-events-sub"
  topic = google_pubsub_topic.dr_events.name
  
  labels = local.common_labels
  
  ack_deadline_seconds = 20
  
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
  
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dr_events_dlq.id
    max_delivery_attempts = 5
  }
}

# Dead letter queue for failed DR events
resource "google_pubsub_topic" "dr_events_dlq" {
  name = "${local.enterprise_prefix}-dr-events-dlq"
  
  labels = local.common_labels
}

# Secret Manager secrets
resource "google_secret_manager_secret" "azure_connection" {
  secret_id = "${local.enterprise_prefix}-azure-connection"
  
  labels = local.common_labels
  
  replication {
    user_managed {
      replicas {
        location = local.region
      }
      replicas {
        location = local.backup_region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "azure_connection" {
  secret      = google_secret_manager_secret.azure_connection.id
  secret_data = jsonencode({
    subscription_id = "your-azure-subscription-id"
    tenant_id      = "your-azure-tenant-id"
    client_id      = "your-azure-client-id"
    client_secret  = "your-azure-client-secret"
  })
}

resource "google_secret_manager_secret" "striim_config" {
  secret_id = "${local.enterprise_prefix}-striim-config"
  
  labels = local.common_labels
  
  replication {
    user_managed {
      replicas {
        location = local.region
      }
      replicas {
        location = local.backup_region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "striim_config" {
  secret      = google_secret_manager_secret.striim_config.id
  secret_data = jsonencode({
    striim_url      = "your-striim-cluster-url"
    striim_username = "admin"
    striim_password = "your-striim-password"
    license_key    = "your-striim-license-key"
  })
}

# Cloud Scheduler job for health checks
resource "google_cloud_scheduler_job" "health_check" {
  name             = "${local.enterprise_prefix}-health-check"
  description      = "Periodic health check for DR orchestrator"
  schedule         = "*/5 * * * *"  # Every 5 minutes
  time_zone        = "UTC"
  attempt_deadline = "120s"
  
  retry_config {
    retry_count = 3
  }
  
  pubsub_target {
    topic_name = google_pubsub_topic.dr_events.id
    data       = base64encode(jsonencode({
      type = "health_check"
      timestamp = "scheduled"
    }))
  }
}

# Output values for DR orchestrator
output "gcp_infrastructure" {
  description = "GCP infrastructure details for DR orchestrator"
  value = {
    project_id      = local.project_id
    region         = local.region
    backup_region  = local.backup_region
    
    networking = {
      vpc_name         = google_compute_network.main.name
      vpc_id          = google_compute_network.main.id
      subnet_name     = google_compute_subnetwork.main.name
      subnet_id       = google_compute_subnetwork.main.id
      pods_cidr       = local.pods_cidr
      services_cidr   = local.services_cidr
    }
    
    gke_cluster = {
      name               = google_container_cluster.main.name
      endpoint          = google_container_cluster.main.endpoint
      ca_certificate    = google_container_cluster.main.master_auth.0.cluster_ca_certificate
      location          = google_container_cluster.main.location
      node_pool_name    = google_container_node_pool.main.name
    }
    
    cloud_sql = {
      instance_name           = google_sql_database_instance.main.name
      connection_name         = google_sql_database_instance.main.connection_name
      private_ip_address      = google_sql_database_instance.main.private_ip_address
      database_name          = google_sql_database.main.name
      username               = google_sql_user.main.name
    }
    
    storage = {
      cloud_functions_bucket = google_storage_bucket.cloud_functions_source.name
      monitoring_bucket      = google_storage_bucket.monitoring.name
    }
    
    pubsub = {
      dr_events_topic        = google_pubsub_topic.dr_events.name
      dr_events_subscription = google_pubsub_subscription.dr_events.name
      dr_events_dlq         = google_pubsub_topic.dr_events_dlq.name
    }
    
    secrets = {
      azure_connection_secret = google_secret_manager_secret.azure_connection.secret_id
      striim_config_secret   = google_secret_manager_secret.striim_config.secret_id
    }
    
    service_accounts = {
      gke_nodes_email      = google_service_account.gke_nodes.email
      cloud_functions_email = google_service_account.cloud_functions.email
    }
    
    monitoring = {
      health_check_job = google_cloud_scheduler_job.health_check.name
    }
  }
  
  sensitive = false
}
