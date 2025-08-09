#!/bin/bash

# Configuration Management Script for DR Orchestrator
# Manages environment-specific configurations and secrets

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_DIR="$PROJECT_ROOT/config"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create configuration directory
create_config_structure() {
    log_info "Creating configuration directory structure..."
    
    mkdir -p "$CONFIG_DIR"/{environments,secrets,templates}
    
    log_success "Configuration structure created"
}

# Generate environment configuration template
generate_config_template() {
    local env_name="${1:-development}"
    local config_file="$CONFIG_DIR/environments/${env_name}.json"
    
    log_info "Generating configuration template for environment: $env_name"
    
    cat > "$config_file" << EOF
{
  "environment": "$env_name",
  "azure": {
    "subscription_id": "REPLACE_WITH_AZURE_SUBSCRIPTION_ID",
    "tenant_id": "REPLACE_WITH_AZURE_TENANT_ID",
    "resource_group": "dr-orchestrator-${env_name}-rg",
    "region": "eastus",
    "sql_mi": {
      "name": "dr-sql-mi-${env_name}",
      "admin_username": "sqladmin",
      "tier": "GeneralPurpose",
      "vcores": 4,
      "storage_size_gb": 256,
      "backup_retention_days": 7
    },
    "aks": {
      "cluster_name": "dr-aks-${env_name}",
      "node_count": 3,
      "node_vm_size": "Standard_D4s_v3",
      "kubernetes_version": "1.28",
      "enable_rbac": true,
      "enable_network_policy": true
    },
    "networking": {
      "vnet_name": "dr-vnet-${env_name}",
      "vnet_cidr": "10.0.0.0/16",
      "subnet_cidr": "10.0.1.0/24",
      "enable_private_endpoint": true
    },
    "monitoring": {
      "log_analytics_workspace": "dr-logs-${env_name}",
      "application_insights": "dr-insights-${env_name}"
    }
  },
  "gcp": {
    "project_id": "REPLACE_WITH_GCP_PROJECT_ID",
    "region": "us-central1",
    "zone": "us-central1-a",
    "cloud_sql": {
      "instance_name": "dr-cloud-sql-${env_name}",
      "database_version": "POSTGRES_14",
      "tier": "db-standard-4",
      "disk_size_gb": 256,
      "backup_enabled": true,
      "high_availability": true
    },
    "gke": {
      "cluster_name": "dr-gke-${env_name}",
      "node_count": 3,
      "machine_type": "e2-standard-4",
      "kubernetes_version": "1.28",
      "enable_autopilot": false,
      "enable_workload_identity": true
    },
    "networking": {
      "vpc_name": "dr-vpc-${env_name}",
      "subnet_name": "dr-subnet-${env_name}",
      "cidr": "10.1.0.0/16",
      "enable_private_google_access": true
    },
    "cloud_functions": {
      "runtime": "python39",
      "memory_mb": 512,
      "timeout_seconds": 540
    }
  },
  "striim": {
    "cluster_endpoint": "http://striim-cluster.${env_name}.internal:9080",
    "license_key": "REPLACE_WITH_STRIIM_LICENSE_KEY",
    "admin_username": "admin",
    "application_name": "AzureToGcpDrReplication",
    "cluster_config": {
      "nodes": 3,
      "memory_gb": 8,
      "cpu_cores": 4,
      "storage_gb": 100
    },
    "replication": {
      "batch_size": 1000,
      "commit_interval_ms": 5000,
      "parallel_threads": 4,
      "compression_enabled": true
    }
  },
  "thresholds": {
    "health_critical": 0.5,
    "health_warning": 0.8,
    "rto_target_seconds": 300,
    "rpo_target_ms": 30000,
    "max_failover_duration_seconds": 300,
    "replication_lag_warning_ms": 15000,
    "replication_lag_critical_ms": 30000
  },
  "monitoring": {
    "prometheus": {
      "scrape_interval": "30s",
      "evaluation_interval": "30s",
      "retention": "30d",
      "storage_tsdb_retention_size": "10GB"
    },
    "grafana": {
      "admin_password": "REPLACE_WITH_GRAFANA_PASSWORD",
      "smtp_enabled": false,
      "smtp_host": "smtp.company.com",
      "smtp_port": 587
    },
    "alerting": {
      "webhook_url": "REPLACE_WITH_WEBHOOK_URL",
      "email_recipients": ["ops-team@company.com"],
      "slack_channel": "#dr-alerts",
      "pagerduty_integration_key": "REPLACE_WITH_PAGERDUTY_KEY"
    }
  },
  "security": {
    "enable_encryption_at_rest": true,
    "enable_encryption_in_transit": true,
    "key_vault_name": "dr-keyvault-${env_name}",
    "certificate_auto_renewal": true,
    "network_security": {
      "allow_public_access": false,
      "whitelist_ips": ["203.0.113.0/24"],
      "enable_ddos_protection": true
    }
  },
  "backup": {
    "enabled": true,
    "schedule": "0 2 * * *",
    "retention_days": 30,
    "cross_region_backup": true,
    "backup_storage_account": "drbackup${env_name}storage"
  },
  "disaster_recovery": {
    "automatic_failover": false,
    "manual_approval_required": true,
    "failback_enabled": true,
    "test_schedule": "0 4 * * 1",
    "notification_channels": ["email", "slack"]
  }
}
EOF
    
    log_success "Configuration template created: $config_file"
}

# Validate configuration
validate_config() {
    local env_name="${1:-development}"
    local config_file="$CONFIG_DIR/environments/${env_name}.json"
    
    log_info "Validating configuration for environment: $env_name"
    
    if [ ! -f "$config_file" ]; then
        log_error "Configuration file not found: $config_file"
        return 1
    fi
    
    # Validate JSON syntax
    if ! jq . "$config_file" > /dev/null 2>&1; then
        log_error "Invalid JSON syntax in configuration file"
        return 1
    fi
    
    # Check for required fields
    local required_fields=(
        ".azure.subscription_id"
        ".gcp.project_id"
        ".azure.resource_group"
        ".gcp.region"
        ".thresholds.rto_target_seconds"
        ".thresholds.rpo_target_ms"
    )
    
    local missing_fields=()
    for field in "${required_fields[@]}"; do
        if ! jq -e "$field" "$config_file" > /dev/null 2>&1; then
            missing_fields+=("$field")
        fi
    done
    
    if [ ${#missing_fields[@]} -ne 0 ]; then
        log_error "Missing required configuration fields:"
        for field in "${missing_fields[@]}"; do
            echo "  - $field"
        done
        return 1
    fi
    
    # Check for placeholder values
    local placeholders=$(jq -r '[.. | strings] | map(select(test("REPLACE_WITH_"))) | unique | .[]' "$config_file" 2>/dev/null || true)
    if [ -n "$placeholders" ]; then
        log_warning "Configuration contains placeholder values:"
        echo "$placeholders" | while read -r placeholder; do
            echo "  - $placeholder"
        done
    fi
    
    log_success "Configuration validation completed"
}

# Set up secrets management
setup_secrets() {
    local env_name="${1:-development}"
    
    log_info "Setting up secrets management for environment: $env_name"
    
    # Create secrets directory
    local secrets_dir="$CONFIG_DIR/secrets/$env_name"
    mkdir -p "$secrets_dir"
    
    # Generate secrets template
    cat > "$secrets_dir/secrets.env.template" << EOF
# Azure Authentication
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
AZURE_TENANT_ID=

# GCP Authentication
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GCP_SERVICE_ACCOUNT_KEY=

# Database Credentials
AZURE_SQL_MI_PASSWORD=
GCP_CLOUD_SQL_PASSWORD=

# Striim Configuration
STRIIM_LICENSE_KEY=
STRIIM_ADMIN_PASSWORD=

# Monitoring
GRAFANA_ADMIN_PASSWORD=
PROMETHEUS_BASIC_AUTH=

# Alerting
SLACK_WEBHOOK_URL=
PAGERDUTY_INTEGRATION_KEY=
SMTP_PASSWORD=

# Encryption Keys
ENCRYPTION_KEY_BASE64=
JWT_SECRET_KEY=

# API Keys
AZURE_MONITOR_API_KEY=
GCP_MONITORING_API_KEY=
EOF
    
    # Create gitignore for secrets
    cat > "$secrets_dir/.gitignore" << EOF
# Ignore all secrets files
*.env
*.key
*.pem
*.p12
*.pfx
service-account*.json
EOF
    
    log_success "Secrets management setup completed"
    log_warning "Remember to populate the secrets template: $secrets_dir/secrets.env.template"
}

# Generate Terraform variables
generate_terraform_vars() {
    local env_name="${1:-development}"
    local config_file="$CONFIG_DIR/environments/${env_name}.json"
    
    log_info "Generating Terraform variables for environment: $env_name"
    
    if [ ! -f "$config_file" ]; then
        log_error "Configuration file not found: $config_file"
        return 1
    fi
    
    # Generate Azure Terraform variables
    local azure_vars_file="$PROJECT_ROOT/terraform/azure/terraform.tfvars"
    cat > "$azure_vars_file" << EOF
# Generated from $config_file
subscription_id = "$(jq -r '.azure.subscription_id' "$config_file")"
resource_group_name = "$(jq -r '.azure.resource_group' "$config_file")"
location = "$(jq -r '.azure.region' "$config_file")"
environment = "$env_name"

# SQL Managed Instance
sql_mi_name = "$(jq -r '.azure.sql_mi.name' "$config_file")"
sql_mi_admin_username = "$(jq -r '.azure.sql_mi.admin_username' "$config_file")"
sql_mi_tier = "$(jq -r '.azure.sql_mi.tier' "$config_file")"
sql_mi_vcores = $(jq -r '.azure.sql_mi.vcores' "$config_file")
sql_mi_storage_size_gb = $(jq -r '.azure.sql_mi.storage_size_gb' "$config_file")

# AKS Configuration
aks_cluster_name = "$(jq -r '.azure.aks.cluster_name' "$config_file")"
aks_node_count = $(jq -r '.azure.aks.node_count' "$config_file")
aks_node_vm_size = "$(jq -r '.azure.aks.node_vm_size' "$config_file")"
aks_kubernetes_version = "$(jq -r '.azure.aks.kubernetes_version' "$config_file")"

# Networking
vnet_name = "$(jq -r '.azure.networking.vnet_name' "$config_file")"
vnet_cidr = "$(jq -r '.azure.networking.vnet_cidr' "$config_file")"
subnet_cidr = "$(jq -r '.azure.networking.subnet_cidr' "$config_file")"

# Monitoring
log_analytics_workspace_name = "$(jq -r '.azure.monitoring.log_analytics_workspace' "$config_file")"
application_insights_name = "$(jq -r '.azure.monitoring.application_insights' "$config_file")"

# Security
enable_encryption_at_rest = $(jq -r '.security.enable_encryption_at_rest' "$config_file")
key_vault_name = "$(jq -r '.security.key_vault_name' "$config_file")"
EOF
    
    # Generate GCP Terraform variables
    local gcp_vars_file="$PROJECT_ROOT/terraform/gcp/terraform.tfvars"
    cat > "$gcp_vars_file" << EOF
# Generated from $config_file
project_id = "$(jq -r '.gcp.project_id' "$config_file")"
region = "$(jq -r '.gcp.region' "$config_file")"
zone = "$(jq -r '.gcp.zone' "$config_file")"
environment = "$env_name"

# Cloud SQL
cloud_sql_instance_name = "$(jq -r '.gcp.cloud_sql.instance_name' "$config_file")"
cloud_sql_database_version = "$(jq -r '.gcp.cloud_sql.database_version' "$config_file")"
cloud_sql_tier = "$(jq -r '.gcp.cloud_sql.tier' "$config_file")"
cloud_sql_disk_size_gb = $(jq -r '.gcp.cloud_sql.disk_size_gb' "$config_file")

# GKE Configuration
gke_cluster_name = "$(jq -r '.gcp.gke.cluster_name' "$config_file")"
gke_node_count = $(jq -r '.gcp.gke.node_count' "$config_file")
gke_machine_type = "$(jq -r '.gcp.gke.machine_type' "$config_file")"
gke_kubernetes_version = "$(jq -r '.gcp.gke.kubernetes_version' "$config_file")"

# Networking
vpc_name = "$(jq -r '.gcp.networking.vpc_name' "$config_file")"
subnet_name = "$(jq -r '.gcp.networking.subnet_name' "$config_file")"
subnet_cidr = "$(jq -r '.gcp.networking.cidr' "$config_file")"

# Cloud Functions
cloud_function_runtime = "$(jq -r '.gcp.cloud_functions.runtime' "$config_file")"
cloud_function_memory_mb = $(jq -r '.gcp.cloud_functions.memory_mb' "$config_file")
cloud_function_timeout_seconds = $(jq -r '.gcp.cloud_functions.timeout_seconds' "$config_file")
EOF
    
    log_success "Terraform variables generated"
}

# Generate Kubernetes manifests
generate_k8s_manifests() {
    local env_name="${1:-development}"
    local config_file="$CONFIG_DIR/environments/${env_name}.json"
    
    log_info "Generating Kubernetes manifests for environment: $env_name"
    
    # Create environment-specific manifest directory
    local k8s_env_dir="$PROJECT_ROOT/kubernetes/environments/$env_name"
    mkdir -p "$k8s_env_dir"
    
    # Generate ConfigMap with DR configuration
    cat > "$k8s_env_dir/dr-config.yaml" << EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: dr-orchestrator-config
  namespace: dr-system
data:
  config.json: |
$(jq '.' "$config_file" | sed 's/^/    /')
  environment: "$env_name"
  rto_target_seconds: "$(jq -r '.thresholds.rto_target_seconds' "$config_file")"
  rpo_target_ms: "$(jq -r '.thresholds.rpo_target_ms' "$config_file")"
---
apiVersion: v1
kind: Secret
metadata:
  name: dr-orchestrator-secrets
  namespace: dr-system
type: Opaque
stringData:
  azure-client-secret: "REPLACE_WITH_AZURE_CLIENT_SECRET"
  gcp-service-account-key: "REPLACE_WITH_GCP_SERVICE_ACCOUNT_KEY"
  striim-license-key: "$(jq -r '.striim.license_key' "$config_file")"
  grafana-admin-password: "$(jq -r '.monitoring.grafana.admin_password' "$config_file")"
EOF
    
    log_success "Kubernetes manifests generated"
}

# Create environment
create_environment() {
    local env_name="$1"
    
    log_info "Creating new environment: $env_name"
    
    create_config_structure
    generate_config_template "$env_name"
    setup_secrets "$env_name"
    
    log_success "Environment '$env_name' created successfully"
    echo ""
    echo "Next steps:"
    echo "1. Edit the configuration file: $CONFIG_DIR/environments/${env_name}.json"
    echo "2. Replace placeholder values with actual values"
    echo "3. Set up secrets in: $CONFIG_DIR/secrets/${env_name}/secrets.env"
    echo "4. Validate the configuration: $0 validate $env_name"
    echo "5. Generate deployment files: $0 generate $env_name"
}

# Generate all deployment files
generate_deployment_files() {
    local env_name="$1"
    
    log_info "Generating deployment files for environment: $env_name"
    
    validate_config "$env_name"
    generate_terraform_vars "$env_name"
    generate_k8s_manifests "$env_name"
    
    log_success "Deployment files generated for environment: $env_name"
}

# List environments
list_environments() {
    log_info "Available environments:"
    
    if [ -d "$CONFIG_DIR/environments" ]; then
        for config_file in "$CONFIG_DIR/environments"/*.json; do
            if [ -f "$config_file" ]; then
                local env_name=$(basename "$config_file" .json)
                local valid_status="✓"
                if ! validate_config "$env_name" > /dev/null 2>&1; then
                    valid_status="✗"
                fi
                echo "  $valid_status $env_name"
            fi
        done
    else
        echo "  No environments found"
    fi
}

# Show usage
show_usage() {
    echo "DR Orchestrator Configuration Management"
    echo ""
    echo "Usage: $0 <command> [environment_name]"
    echo ""
    echo "Commands:"
    echo "  create <env>     Create a new environment configuration"
    echo "  validate <env>   Validate environment configuration"
    echo "  generate <env>   Generate deployment files for environment"
    echo "  list             List all available environments"
    echo "  secrets <env>    Set up secrets management for environment"
    echo ""
    echo "Examples:"
    echo "  $0 create production"
    echo "  $0 validate development"
    echo "  $0 generate staging"
    echo "  $0 list"
}

# Main function
main() {
    local command="${1:-}"
    local env_name="${2:-}"
    
    case "$command" in
        "create")
            if [ -z "$env_name" ]; then
                log_error "Environment name is required for create command"
                show_usage
                exit 1
            fi
            create_environment "$env_name"
            ;;
        "validate")
            if [ -z "$env_name" ]; then
                log_error "Environment name is required for validate command"
                show_usage
                exit 1
            fi
            validate_config "$env_name"
            ;;
        "generate")
            if [ -z "$env_name" ]; then
                log_error "Environment name is required for generate command"
                show_usage
                exit 1
            fi
            generate_deployment_files "$env_name"
            ;;
        "secrets")
            if [ -z "$env_name" ]; then
                log_error "Environment name is required for secrets command"
                show_usage
                exit 1
            fi
            setup_secrets "$env_name"
            ;;
        "list")
            list_environments
            ;;
        *)
            show_usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
