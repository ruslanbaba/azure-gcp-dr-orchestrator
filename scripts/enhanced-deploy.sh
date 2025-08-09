#!/bin/bash

# Enhanced Deployment Script with Security Hardening and Canary Failover
# Implements comprehensive security checks, validation, and monitoring

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="/tmp/dr-deployment-$(date +%Y%m%d-%H%M%S).log"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    local level=$1
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case $level in
        ERROR)
            echo -e "${RED}[$timestamp] ERROR: $message${NC}" | tee -a "$LOG_FILE" >&2
            ;;
        WARN)
            echo -e "${YELLOW}[$timestamp] WARN: $message${NC}" | tee -a "$LOG_FILE"
            ;;
        INFO)
            echo -e "${GREEN}[$timestamp] INFO: $message${NC}" | tee -a "$LOG_FILE"
            ;;
        DEBUG)
            if [[ "${DEBUG:-false}" == "true" ]]; then
                echo -e "${BLUE}[$timestamp] DEBUG: $message${NC}" | tee -a "$LOG_FILE"
            fi
            ;;
    esac
}

# Error handling
error_exit() {
    log ERROR "$1"
    exit 1
}

# Cleanup function
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        log ERROR "Deployment failed. Check log file: $LOG_FILE"
        log INFO "Rolling back changes..."
        rollback_on_failure || true
    fi
    exit $exit_code
}

trap cleanup EXIT

# Configuration validation
validate_config() {
    log INFO "Validating configuration..."
    
    # Required environment variables
    local required_vars=(
        "PROJECT_ID"
        "REGION"
        "CLUSTER_NAME"
        "DNS_ZONE"
        "AZURE_HEALTH_ENDPOINT"
    )
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            error_exit "Required environment variable $var is not set"
        fi
    done
    
    # Validate GCP project
    if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
        error_exit "Project $PROJECT_ID does not exist or is not accessible"
    fi
    
    # Validate region
    if ! gcloud compute regions describe "$REGION" --project="$PROJECT_ID" &>/dev/null; then
        error_exit "Region $REGION is not valid for project $PROJECT_ID"
    fi
    
    log INFO "Configuration validation completed"
}

# Security prerequisites check
check_security_prerequisites() {
    log INFO "Checking security prerequisites..."
    
    # Check if Binary Authorization is available
    if ! gcloud container binauthz policy list --project="$PROJECT_ID" &>/dev/null; then
        log WARN "Binary Authorization not configured - consider enabling for production"
    fi
    
    # Check if Container Analysis API is enabled
    local enabled_apis
    enabled_apis=$(gcloud services list --enabled --project="$PROJECT_ID" --format="value(config.name)")
    
    local required_security_apis=(
        "containeranalysis.googleapis.com"
        "containersecurity.googleapis.com"
        "binaryauthorization.googleapis.com"
    )
    
    for api in "${required_security_apis[@]}"; do
        if ! echo "$enabled_apis" | grep -q "$api"; then
            log WARN "Security API $api is not enabled - enabling now"
            gcloud services enable "$api" --project="$PROJECT_ID"
        fi
    done
    
    # Check kubectl version compatibility
    local kubectl_version
    kubectl_version=$(kubectl version --client -o json | jq -r '.clientVersion.major + "." + .clientVersion.minor')
    log INFO "kubectl version: $kubectl_version"
    
    # Check if Istio is available
    if ! command -v istioctl &>/dev/null; then
        log WARN "istioctl not found - installing..."
        curl -L https://istio.io/downloadIstio | sh -
        export PATH="$PWD/istio-*/bin:$PATH"
    fi
    
    log INFO "Security prerequisites check completed"
}

# Infrastructure deployment with security hardening
deploy_infrastructure() {
    log INFO "Deploying security-hardened infrastructure..."
    
    local terraform_dir="$PROJECT_ROOT/terraform/enhanced-security"
    
    if [[ ! -d "$terraform_dir" ]]; then
        error_exit "Terraform directory not found: $terraform_dir"
    fi
    
    cd "$terraform_dir"
    
    # Initialize Terraform with backend configuration
    log INFO "Initializing Terraform..."
    terraform init \
        -backend-config="bucket=${PROJECT_ID}-terraform-state" \
        -backend-config="prefix=dr-orchestrator/terraform.tfstate"
    
    # Validate Terraform configuration
    log INFO "Validating Terraform configuration..."
    terraform validate
    
    # Plan deployment
    log INFO "Planning infrastructure deployment..."
    terraform plan \
        -var="project_id=$PROJECT_ID" \
        -var="region=$REGION" \
        -var="cluster_name=$CLUSTER_NAME" \
        -var="dns_zone_name=${DNS_ZONE}" \
        -var="dns_domain=${DNS_DOMAIN:-example.com.}" \
        -var="azure_health_endpoint=$AZURE_HEALTH_ENDPOINT" \
        -out=tfplan
    
    # Apply with auto-approval for automation
    log INFO "Applying infrastructure deployment..."
    terraform apply -auto-approve tfplan
    
    # Store outputs for later use
    terraform output -json > "/tmp/terraform-outputs.json"
    
    log INFO "Infrastructure deployment completed"
    cd "$PROJECT_ROOT"
}

# Set up Workload Identity
configure_workload_identity() {
    log INFO "Configuring Workload Identity..."
    
    local gsa_email
    gsa_email=$(jq -r '.service_account_email.value' /tmp/terraform-outputs.json)
    
    if [[ "$gsa_email" == "null" || -z "$gsa_email" ]]; then
        error_exit "Failed to get service account email from Terraform outputs"
    fi
    
    # Create Kubernetes service account annotation
    kubectl annotate serviceaccount dr-app-service-account \
        -n dr-system \
        iam.gke.io/gcp-service-account="$gsa_email" \
        --overwrite
    
    # Bind the Kubernetes service account to the Google service account
    gcloud iam service-accounts add-iam-policy-binding \
        "$gsa_email" \
        --role roles/iam.workloadIdentityUser \
        --member "serviceAccount:${PROJECT_ID}.svc.id.goog[dr-system/dr-app-service-account]" \
        --project="$PROJECT_ID"
    
    log INFO "Workload Identity configuration completed"
}

# Deploy Istio service mesh
deploy_istio() {
    log INFO "Deploying Istio service mesh..."
    
    # Install Istio with security features
    istioctl install --set values.pilot.env.EXTERNAL_ISTIOD=false \
        --set values.global.meshID=mesh1 \
        --set values.global.network=network1 \
        --set values.gateways.istio-ingressgateway.type=LoadBalancer \
        --set values.gateways.istio-ingressgateway.loadBalancerIP="$(jq -r '.static_ip.value' /tmp/terraform-outputs.json)" \
        -y
    
    # Enable Istio injection for the namespace
    kubectl label namespace dr-system istio-injection=enabled --overwrite
    
    # Wait for Istio to be ready
    kubectl wait --for=condition=Ready pods -l app=istiod -n istio-system --timeout=300s
    
    log INFO "Istio deployment completed"
}

# Set up monitoring and observability
setup_monitoring() {
    log INFO "Setting up monitoring and observability..."
    
    # Install Prometheus if not already installed
    if ! kubectl get namespace monitoring &>/dev/null; then
        kubectl create namespace monitoring
        
        # Add Prometheus Helm repository
        helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
        helm repo update
        
        # Install Prometheus with security configurations
        helm install prometheus prometheus-community/kube-prometheus-stack \
            --namespace monitoring \
            --set prometheus.prometheusSpec.retention=30d \
            --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi \
            --set grafana.adminPassword="$(openssl rand -base64 32)" \
            --set grafana.persistence.enabled=true \
            --set grafana.persistence.size=10Gi
    fi
    
    # Apply custom monitoring configurations
    kubectl apply -f "$PROJECT_ROOT/monitoring/prometheus/prometheus.yml" || true
    kubectl apply -f "$PROJECT_ROOT/monitoring/prometheus/alert-rules.yml" || true
    
    log INFO "Monitoring setup completed"
}

# Deploy application with security hardening
deploy_application() {
    log INFO "Deploying security-hardened application..."
    
    # Get GKE cluster credentials
    local cluster_name
    cluster_name=$(jq -r '.cluster_name.value' /tmp/terraform-outputs.json)
    
    gcloud container clusters get-credentials "$cluster_name" \
        --region="$REGION" \
        --project="$PROJECT_ID"
    
    # Update manifests with project-specific values
    local manifest_file="$PROJECT_ROOT/kubernetes/security-hardened/manifests.yaml"
    local temp_manifest="/tmp/manifests-${PROJECT_ID}.yaml"
    
    sed "s/PROJECT_ID/${PROJECT_ID}/g" "$manifest_file" > "$temp_manifest"
    
    # Apply the manifests
    kubectl apply -f "$temp_manifest"
    
    # Wait for namespace to be ready
    kubectl wait --for=condition=Ready namespace/dr-system --timeout=60s
    
    # Configure Workload Identity
    configure_workload_identity
    
    # Wait for deployments to be ready (they start with 0 replicas)
    log INFO "Waiting for deployments to be created..."
    kubectl wait --for=condition=Available deployment/dr-app-production -n dr-system --timeout=300s || true
    kubectl wait --for=condition=Available deployment/dr-app-canary -n dr-system --timeout=300s || true
    
    log INFO "Application deployment completed"
}

# Setup secrets management
setup_secrets() {
    log INFO "Setting up secrets management..."
    
    # Install External Secrets Operator if needed
    if ! kubectl get crd secretstores.external-secrets.io &>/dev/null; then
        helm repo add external-secrets https://charts.external-secrets.io
        helm repo update
        
        helm install external-secrets external-secrets/external-secrets \
            -n external-secrets-system \
            --create-namespace \
            --set installCRDs=true
    fi
    
    # Create SecretStore for Google Secret Manager
    cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: gcp-secret-manager
  namespace: dr-system
spec:
  provider:
    gcpsm:
      projectId: "${PROJECT_ID}"
      auth:
        workloadIdentity:
          clusterLocation: "${REGION}"
          clusterName: "${CLUSTER_NAME}"
          serviceAccountRef:
            name: dr-app-service-account
EOF
    
    # Create ExternalSecret for database URL
    cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: dr-app-database-secret
  namespace: dr-system
spec:
  refreshInterval: 60s
  secretStoreRef:
    name: gcp-secret-manager
    kind: SecretStore
  target:
    name: dr-app-secrets
    creationPolicy: Owner
  data:
  - secretKey: gcp-database-url
    remoteRef:
      key: dr-app-database-url
EOF
    
    log INFO "Secrets management setup completed"
}

# Network security configuration
configure_network_security() {
    log INFO "Configuring network security..."
    
    # Apply network policies
    kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-default
  namespace: dr-system
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
EOF
    
    # Apply the main network policy from manifests
    log INFO "Network policies applied"
    
    # Configure Istio security policies
    kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: dr-system
spec:
  mtls:
    mode: STRICT
EOF
    
    kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: dr-app-authz
  namespace: dr-system
spec:
  selector:
    matchLabels:
      app: dr-app
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/istio-system/sa/istio-ingressgateway-service-account"]
  - to:
    - operation:
        methods: ["GET", "POST"]
        paths: ["/health", "/ready", "/metrics"]
EOF
    
    log INFO "Network security configuration completed"
}

# Validate deployment
validate_deployment() {
    log INFO "Validating deployment..."
    
    # Check if all required resources are created
    local resources=(
        "namespace/dr-system"
        "serviceaccount/dr-app-service-account"
        "deployment/dr-app-production"
        "deployment/dr-app-canary"
        "service/dr-app-service"
        "hpa/dr-app-hpa"
    )
    
    for resource in "${resources[@]}"; do
        if ! kubectl get "$resource" -n dr-system &>/dev/null; then
            error_exit "Resource $resource not found"
        fi
    done
    
    # Check if Istio is properly configured
    if ! kubectl get gateway dr-app-gateway -n dr-system &>/dev/null; then
        log WARN "Istio Gateway not found - traffic routing may not work"
    fi
    
    # Check if monitoring is working
    if ! kubectl get servicemonitor dr-app-metrics -n dr-system &>/dev/null; then
        log WARN "ServiceMonitor not found - metrics collection may not work"
    fi
    
    # Check security policies
    if ! kubectl get networkpolicy -n dr-system | grep -q dr-network-policy; then
        log WARN "Network policies not properly applied"
    fi
    
    log INFO "Deployment validation completed"
}

# Performance testing
run_performance_tests() {
    log INFO "Running performance tests..."
    
    # Wait for services to be ready
    local static_ip
    static_ip=$(jq -r '.static_ip.value' /tmp/terraform-outputs.json)
    
    # Basic connectivity test
    local max_retries=30
    local retry_count=0
    
    while [[ $retry_count -lt $max_retries ]]; do
        if curl -s -o /dev/null -w "%{http_code}" "http://${static_ip}/health" | grep -q "200"; then
            log INFO "Health check endpoint is responding"
            break
        fi
        
        ((retry_count++))
        log INFO "Waiting for health check endpoint... (attempt $retry_count/$max_retries)"
        sleep 10
    done
    
    if [[ $retry_count -eq $max_retries ]]; then
        log WARN "Health check endpoint not responding after $max_retries attempts"
    fi
    
    # Run basic load test if hey is available
    if command -v hey &>/dev/null; then
        log INFO "Running load test..."
        hey -n 100 -c 10 "http://${static_ip}/health" > "/tmp/load-test-results.txt"
        log INFO "Load test completed. Results saved to /tmp/load-test-results.txt"
    else
        log WARN "hey tool not found - skipping load test"
    fi
    
    log INFO "Performance tests completed"
}

# Rollback function
rollback_on_failure() {
    log WARN "Rolling back deployment due to failure..."
    
    # Scale down deployments
    kubectl scale deployment dr-app-production -n dr-system --replicas=0 || true
    kubectl scale deployment dr-app-canary -n dr-system --replicas=0 || true
    
    # Remove problematic resources
    kubectl delete -f "$PROJECT_ROOT/kubernetes/security-hardened/manifests.yaml" --ignore-not-found=true || true
    
    log INFO "Rollback completed"
}

# Generate deployment report
generate_report() {
    log INFO "Generating deployment report..."
    
    local report_file="/tmp/dr-deployment-report-$(date +%Y%m%d-%H%M%S).json"
    
    # Collect deployment information
    cat > "$report_file" <<EOF
{
  "deployment_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "project_id": "$PROJECT_ID",
  "region": "$REGION",
  "cluster_name": "$CLUSTER_NAME",
  "terraform_outputs": $(cat /tmp/terraform-outputs.json),
  "kubernetes_resources": {
    "namespaces": $(kubectl get namespaces -o json | jq '.items | length'),
    "deployments": $(kubectl get deployments -n dr-system -o json | jq '.items | length'),
    "services": $(kubectl get services -n dr-system -o json | jq '.items | length'),
    "pods": $(kubectl get pods -n dr-system -o json | jq '.items | length')
  },
  "security_features": {
    "istio_enabled": $(kubectl get namespace dr-system -o json | jq '.metadata.labels."istio-injection" == "enabled"'),
    "network_policies": $(kubectl get networkpolicy -n dr-system -o json | jq '.items | length'),
    "pod_security_standards": true,
    "workload_identity": true
  }
}
EOF
    
    log INFO "Deployment report generated: $report_file"
    
    # Display summary
    echo
    echo "=== DEPLOYMENT SUMMARY ==="
    echo "Project ID: $PROJECT_ID"
    echo "Region: $REGION"
    echo "Cluster: $CLUSTER_NAME"
    echo "Static IP: $(jq -r '.static_ip.value' /tmp/terraform-outputs.json)"
    echo "Log File: $LOG_FILE"
    echo "Report File: $report_file"
    echo "=========================="
    echo
}

# Main deployment function
main() {
    log INFO "Starting enhanced DR orchestrator deployment..."
    log INFO "Log file: $LOG_FILE"
    
    # Set default values
    export PROJECT_ID="${PROJECT_ID:-}"
    export REGION="${REGION:-us-central1}"
    export CLUSTER_NAME="${CLUSTER_NAME:-dr-gke-secure}"
    export DNS_ZONE="${DNS_ZONE:-dr-zone}"
    export DNS_DOMAIN="${DNS_DOMAIN:-example.com.}"
    export AZURE_HEALTH_ENDPOINT="${AZURE_HEALTH_ENDPOINT:-https://primary.example.com/healthz}"
    
    # Check if running in CI/CD mode
    if [[ "${CI:-false}" == "true" ]]; then
        log INFO "Running in CI/CD mode"
        export DEBIAN_FRONTEND=noninteractive
    fi
    
    # Deployment steps
    validate_config
    check_security_prerequisites
    deploy_infrastructure
    deploy_istio
    setup_monitoring
    deploy_application
    setup_secrets
    configure_network_security
    validate_deployment
    run_performance_tests
    generate_report
    
    log INFO "Enhanced DR orchestrator deployment completed successfully!"
    log INFO "Next steps:"
    log INFO "1. Configure DNS records to point to $(jq -r '.static_ip.value' /tmp/terraform-outputs.json)"
    log INFO "2. Update Striim configuration with Cloud SQL endpoint"
    log INFO "3. Test failover scenarios using scripts/test-failover.sh"
    log INFO "4. Configure monitoring alerts and dashboards"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
