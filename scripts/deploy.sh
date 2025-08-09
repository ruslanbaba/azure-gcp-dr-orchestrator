#!/bin/bash

# Azure to GCP Cross-Cloud DR Orchestrator - Deployment Script
# Deploys the complete enterprise DR solution across Azure and GCP

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOYMENT_ENV="${DEPLOYMENT_ENV:-production}"
LOG_FILE="/tmp/dr_orchestrator_deployment_$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${1}" | tee -a "$LOG_FILE"
}

log_info() {
    log "${BLUE}[INFO]${NC} $1"
}

log_success() {
    log "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    log "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    log "${RED}[ERROR]${NC} $1"
}

# Print banner
print_banner() {
    echo -e "${BLUE}"
    echo "============================================================================"
    echo "  Azure to GCP Cross-Cloud DR Orchestrator - Enterprise Deployment"
    echo "============================================================================"
    echo -e "${NC}"
    echo "Environment: $DEPLOYMENT_ENV"
    echo "Started at: $(date)"
    echo "Log file: $LOG_FILE"
    echo ""
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    local missing_tools=()
    
    # Check required tools
    for tool in az gcloud terraform kubectl docker python3 helm; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -ne 0 ]; then
        log_error "Missing required tools: ${missing_tools[*]}"
        log_error "Please install the missing tools and try again"
        exit 1
    fi
    
    # Check Azure CLI login
    if ! az account show &> /dev/null; then
        log_error "Azure CLI not logged in. Please run 'az login'"
        exit 1
    fi
    
    # Check GCP CLI login
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n 1 &> /dev/null; then
        log_error "GCP CLI not logged in. Please run 'gcloud auth login'"
        exit 1
    fi
    
    # Check Python dependencies
    if ! python3 -c "import asyncio, aiohttp, prometheus_client" &> /dev/null; then
        log_warning "Some Python dependencies may be missing. Installing..."
        pip3 install -r "$PROJECT_ROOT/requirements.txt" || {
            log_error "Failed to install Python dependencies"
            exit 1
        }
    fi
    
    log_success "Prerequisites check completed"
}

# Load configuration
load_configuration() {
    log_info "Loading configuration for environment: $DEPLOYMENT_ENV"
    
    local config_file="$PROJECT_ROOT/config/${DEPLOYMENT_ENV}.json"
    if [ ! -f "$config_file" ]; then
        log_error "Configuration file not found: $config_file"
        exit 1
    fi
    
    # Export configuration variables
    export AZURE_SUBSCRIPTION_ID=$(jq -r '.azure.subscription_id' "$config_file")
    export AZURE_RESOURCE_GROUP=$(jq -r '.azure.resource_group' "$config_file")
    export AZURE_REGION=$(jq -r '.azure.region' "$config_file")
    
    export GCP_PROJECT_ID=$(jq -r '.gcp.project_id' "$config_file")
    export GCP_REGION=$(jq -r '.gcp.region' "$config_file")
    
    export STRIIM_LICENSE_KEY=$(jq -r '.striim.license_key // "demo"' "$config_file")
    
    log_success "Configuration loaded"
    log_info "Azure Subscription: $AZURE_SUBSCRIPTION_ID"
    log_info "Azure Resource Group: $AZURE_RESOURCE_GROUP"
    log_info "GCP Project: $GCP_PROJECT_ID"
}

# Deploy Azure infrastructure
deploy_azure_infrastructure() {
    log_info "Deploying Azure infrastructure..."
    
    cd "$PROJECT_ROOT/terraform/azure"
    
    # Initialize Terraform
    terraform init
    
    # Plan deployment
    terraform plan \
        -var="subscription_id=$AZURE_SUBSCRIPTION_ID" \
        -var="resource_group_name=$AZURE_RESOURCE_GROUP" \
        -var="location=$AZURE_REGION" \
        -var="environment=$DEPLOYMENT_ENV" \
        -out=azure.tfplan
    
    # Apply deployment
    terraform apply azure.tfplan
    
    # Save outputs
    terraform output -json > "$PROJECT_ROOT/outputs/azure_outputs.json"
    
    log_success "Azure infrastructure deployed"
}

# Deploy GCP infrastructure
deploy_gcp_infrastructure() {
    log_info "Deploying GCP infrastructure..."
    
    cd "$PROJECT_ROOT/terraform/gcp"
    
    # Set GCP project
    gcloud config set project "$GCP_PROJECT_ID"
    
    # Initialize Terraform
    terraform init
    
    # Plan deployment
    terraform plan \
        -var="project_id=$GCP_PROJECT_ID" \
        -var="region=$GCP_REGION" \
        -var="environment=$DEPLOYMENT_ENV" \
        -out=gcp.tfplan
    
    # Apply deployment
    terraform apply gcp.tfplan
    
    # Save outputs
    terraform output -json > "$PROJECT_ROOT/outputs/gcp_outputs.json"
    
    log_success "GCP infrastructure deployed"
}

# Deploy Striim CDC
deploy_striim_cdc() {
    log_info "Deploying Striim CDC..."
    
    cd "$PROJECT_ROOT/striim/deployment"
    
    # Create Striim namespace in both clusters
    kubectl --context=azure create namespace striim-system || true
    kubectl --context=gcp create namespace striim-system || true
    
    # Deploy Striim using Docker Compose (for demo)
    # In production, this would use Kubernetes Helm charts
    
    # Set license key
    export STRIIM_LICENSE_KEY
    
    # Start Striim cluster
    docker-compose up -d
    
    # Wait for Striim to be ready
    log_info "Waiting for Striim to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:9080/api/v2/health | grep -q "OK"; then
            break
        fi
        sleep 10
    done
    
    # Deploy CDC application
    cd "$PROJECT_ROOT/striim/applications"
    
    # Submit the replication application
    curl -X POST http://localhost:9080/api/v2/applications \
        -H "Content-Type: application/json" \
        -d @azure_to_gcp_dr_replication.json
    
    log_success "Striim CDC deployed"
}

# Deploy Kubernetes applications
deploy_kubernetes_applications() {
    log_info "Deploying Kubernetes applications..."
    
    # Get cluster credentials
    az aks get-credentials --resource-group "$AZURE_RESOURCE_GROUP" --name "dr-aks-cluster" --context azure
    gcloud container clusters get-credentials "dr-gke-cluster" --region "$GCP_REGION" --project "$GCP_PROJECT_ID"
    kubectl config rename-context "gke_${GCP_PROJECT_ID}_${GCP_REGION}_dr-gke-cluster" gcp
    
    # Deploy to Azure AKS
    log_info "Deploying to Azure AKS..."
    kubectl apply -f "$PROJECT_ROOT/kubernetes/azure-aks/manifests.yaml" --context=azure
    
    # Deploy to GCP GKE
    log_info "Deploying to GCP GKE..."
    kubectl apply -f "$PROJECT_ROOT/kubernetes/gcp-gke/manifests.yaml" --context=gcp
    
    # Wait for deployments to be ready
    log_info "Waiting for deployments to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/dr-orchestrator --context=azure
    kubectl wait --for=condition=available --timeout=300s deployment/dr-orchestrator --context=gcp
    
    log_success "Kubernetes applications deployed"
}

# Deploy Cloud Functions
deploy_cloud_functions() {
    log_info "Deploying Cloud Functions..."
    
    cd "$PROJECT_ROOT/cloud-functions"
    
    # Deploy to GCP Cloud Functions
    gcloud functions deploy dr-orchestrator-health-check \
        --runtime python39 \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars "ENVIRONMENT=$DEPLOYMENT_ENV" \
        --source .
    
    gcloud functions deploy dr-orchestrator-failover \
        --runtime python39 \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars "ENVIRONMENT=$DEPLOYMENT_ENV" \
        --source .
    
    log_success "Cloud Functions deployed"
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring..."
    
    # Deploy Prometheus
    kubectl apply -f "$PROJECT_ROOT/monitoring/prometheus/prometheus.yml" --context=azure
    kubectl apply -f "$PROJECT_ROOT/monitoring/prometheus/prometheus.yml" --context=gcp
    
    # Deploy Grafana
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update
    
    # Install Grafana in both clusters
    helm install grafana grafana/grafana \
        --namespace monitoring \
        --create-namespace \
        --kube-context azure \
        --set persistence.enabled=true \
        --set adminPassword=admin
    
    helm install grafana grafana/grafana \
        --namespace monitoring \
        --create-namespace \
        --kube-context gcp \
        --set persistence.enabled=true \
        --set adminPassword=admin
    
    # Import dashboards
    log_info "Importing Grafana dashboards..."
    # This would typically be done via Grafana API or ConfigMaps
    
    log_success "Monitoring setup completed"
}

# Configure networking
configure_networking() {
    log_info "Configuring cross-cloud networking..."
    
    # Set up VPN connections between Azure and GCP
    # This would involve creating VPN gateways and establishing connections
    
    # For now, we'll configure firewall rules to allow cross-cloud communication
    
    # Azure NSG rules
    az network nsg rule create \
        --resource-group "$AZURE_RESOURCE_GROUP" \
        --nsg-name "dr-orchestrator-nsg" \
        --name "AllowGCPTraffic" \
        --priority 100 \
        --access Allow \
        --protocol "*" \
        --source-address-prefixes "10.1.0.0/16" \
        --destination-port-ranges "*"
    
    # GCP firewall rules
    gcloud compute firewall-rules create allow-azure-traffic \
        --allow tcp,udp,icmp \
        --source-ranges 10.0.0.0/16 \
        --description "Allow traffic from Azure"
    
    log_success "Cross-cloud networking configured"
}

# Run health checks
run_health_checks() {
    log_info "Running post-deployment health checks..."
    
    # Check Azure services
    if az sql mi show --resource-group "$AZURE_RESOURCE_GROUP" --name "dr-sql-mi" --query "state" -o tsv | grep -q "Ready"; then
        log_success "Azure SQL MI is ready"
    else
        log_warning "Azure SQL MI is not ready"
    fi
    
    # Check GCP services
    if gcloud sql instances describe dr-cloud-sql --format="value(state)" | grep -q "RUNNABLE"; then
        log_success "GCP Cloud SQL is ready"
    else
        log_warning "GCP Cloud SQL is not ready"
    fi
    
    # Check Kubernetes deployments
    if kubectl get deployment dr-orchestrator --context=azure -o jsonpath='{.status.readyReplicas}' | grep -q "1"; then
        log_success "Azure Kubernetes deployment is ready"
    else
        log_warning "Azure Kubernetes deployment is not ready"
    fi
    
    if kubectl get deployment dr-orchestrator --context=gcp -o jsonpath='{.status.readyReplicas}' | grep -q "1"; then
        log_success "GCP Kubernetes deployment is ready"
    else
        log_warning "GCP Kubernetes deployment is not ready"
    fi
    
    # Test DR orchestrator endpoint
    local azure_endpoint=$(kubectl get service dr-orchestrator-service --context=azure -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
    if curl -s "http://$azure_endpoint:8080/health" | grep -q "healthy"; then
        log_success "DR orchestrator health endpoint is responding"
    else
        log_warning "DR orchestrator health endpoint is not responding"
    fi
    
    log_success "Health checks completed"
}

# Generate deployment report
generate_deployment_report() {
    log_info "Generating deployment report..."
    
    local report_file="$PROJECT_ROOT/outputs/deployment_report_$(date +%Y%m%d_%H%M%S).json"
    
    cat > "$report_file" << EOF
{
    "deployment_info": {
        "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
        "environment": "$DEPLOYMENT_ENV",
        "version": "1.0.0",
        "deployed_by": "$(whoami)",
        "log_file": "$LOG_FILE"
    },
    "azure_resources": $(cat "$PROJECT_ROOT/outputs/azure_outputs.json" 2>/dev/null || echo "{}"),
    "gcp_resources": $(cat "$PROJECT_ROOT/outputs/gcp_outputs.json" 2>/dev/null || echo "{}"),
    "endpoints": {
        "azure_orchestrator": "$(kubectl get service dr-orchestrator-service --context=azure -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending')",
        "gcp_orchestrator": "$(kubectl get service dr-orchestrator-service --context=gcp -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending')",
        "striim_console": "http://localhost:9080",
        "grafana_azure": "$(kubectl get service grafana --context=azure -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending')",
        "grafana_gcp": "$(kubectl get service grafana --context=gcp -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending')"
    },
    "next_steps": [
        "Access Grafana dashboards using admin/admin credentials",
        "Configure Striim CDC application for your specific databases",
        "Set up alerting rules in Prometheus",
        "Run disaster recovery simulation tests",
        "Configure backup and monitoring schedules"
    ]
}
EOF
    
    log_success "Deployment report generated: $report_file"
}

# Cleanup function
cleanup() {
    log_info "Performing cleanup..."
    # Clean up any temporary files or resources if needed
}

# Main deployment function
main() {
    print_banner
    
    # Set up error handling
    trap cleanup EXIT
    
    # Create outputs directory
    mkdir -p "$PROJECT_ROOT/outputs"
    
    # Run deployment steps
    check_prerequisites
    load_configuration
    deploy_azure_infrastructure
    deploy_gcp_infrastructure
    configure_networking
    deploy_striim_cdc
    deploy_kubernetes_applications
    deploy_cloud_functions
    setup_monitoring
    run_health_checks
    generate_deployment_report
    
    # Print completion message
    echo ""
    log_success "Deployment completed successfully!"
    echo ""
    echo -e "${GREEN}============================================================================${NC}"
    echo -e "${GREEN}  Azure to GCP Cross-Cloud DR Orchestrator - Deployment Complete${NC}"
    echo -e "${GREEN}============================================================================${NC}"
    echo ""
    echo "Environment: $DEPLOYMENT_ENV"
    echo "Completed at: $(date)"
    echo "Log file: $LOG_FILE"
    echo ""
    echo "Next steps:"
    echo "1. Access Grafana dashboards to monitor the system"
    echo "2. Run disaster recovery simulation tests"
    echo "3. Configure alerting and notification channels"
    echo "4. Review the deployment report for detailed information"
    echo ""
    echo "For troubleshooting, check the log file: $LOG_FILE"
    echo ""
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
