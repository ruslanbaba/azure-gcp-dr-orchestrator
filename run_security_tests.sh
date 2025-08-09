#!/bin/bash

# Comprehensive Security Testing and Bug Tracking Script
# This script executes all security tests and generates comprehensive reports

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPORT_DIR="./security_reports"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${REPORT_DIR}/security_test_${TIMESTAMP}.log"

echo -e "${BLUE}🔒 Azure-GCP DR Orchestrator Security Testing Suite${NC}"
echo -e "${BLUE}=================================================${NC}"

# Create reports directory
mkdir -p "$REPORT_DIR"

# Logging function
log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to install missing tools
install_tools() {
    log "${YELLOW}📦 Installing security testing tools...${NC}"
    
    # Install Python dependencies
    if [ -f "tests/requirements.txt" ]; then
        pip install -r tests/requirements.txt
    fi
    
    # Install additional security tools
    if ! command_exists bandit; then
        pip install bandit[toml]
    fi
    
    if ! command_exists safety; then
        pip install safety
    fi
    
    if ! command_exists semgrep; then
        pip install semgrep
    fi
    
    # Install TruffleHog if not present
    if ! command_exists trufflehog; then
        log "${YELLOW}Installing TruffleHog...${NC}"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install trufflesecurity/trufflehog/trufflehog
        else
            curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sh -s -- -b /usr/local/bin
        fi
    fi
    
    # Install GitLeaks if not present
    if ! command_exists gitleaks; then
        log "${YELLOW}Installing GitLeaks...${NC}"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            brew install gitleaks
        else
            wget https://github.com/gitleaks/gitleaks/releases/download/v8.18.0/gitleaks_8.18.0_linux_x64.tar.gz
            tar -xzf gitleaks_8.18.0_linux_x64.tar.gz
            sudo mv gitleaks /usr/local/bin/
            rm gitleaks_8.18.0_linux_x64.tar.gz
        fi
    fi
}

# Function to run secrets scanning
scan_secrets() {
    log "${BLUE}🔍 Phase 1: Secrets and Credentials Scanning${NC}"
    
    # TruffleHog scan
    if command_exists trufflehog; then
        log "${YELLOW}Running TruffleHog scan...${NC}"
        trufflehog filesystem . --json > "${REPORT_DIR}/trufflehog_${TIMESTAMP}.json" 2>/dev/null || true
        if [ -s "${REPORT_DIR}/trufflehog_${TIMESTAMP}.json" ]; then
            SECRETS_COUNT=$(cat "${REPORT_DIR}/trufflehog_${TIMESTAMP}.json" | jq '. | length' 2>/dev/null || echo "0")
            log "${RED}⚠️  TruffleHog found ${SECRETS_COUNT} potential secrets${NC}"
        else
            log "${GREEN}✅ TruffleHog: No secrets found${NC}"
        fi
    fi
    
    # GitLeaks scan
    if command_exists gitleaks; then
        log "${YELLOW}Running GitLeaks scan...${NC}"
        gitleaks detect --source . --report-format json --report-path "${REPORT_DIR}/gitleaks_${TIMESTAMP}.json" --no-git 2>/dev/null || true
        if [ -s "${REPORT_DIR}/gitleaks_${TIMESTAMP}.json" ]; then
            LEAKS_COUNT=$(cat "${REPORT_DIR}/gitleaks_${TIMESTAMP}.json" | jq '. | length' 2>/dev/null || echo "0")
            log "${RED}⚠️  GitLeaks found ${LEAKS_COUNT} potential leaks${NC}"
        else
            log "${GREEN}✅ GitLeaks: No secrets found${NC}"
        fi
    fi
    
    # Custom secrets scan using grep
    log "${YELLOW}Running custom secrets pattern scan...${NC}"
    grep -r -i -E "(password|secret|key|token|api_key|private_key).*[=:].*['\"][^'\"]{8,}" . \
        --exclude-dir=.git \
        --exclude-dir=node_modules \
        --exclude-dir=venv \
        --exclude-dir=security_reports \
        --exclude="*.log" \
        --exclude="*.json" > "${REPORT_DIR}/custom_secrets_${TIMESTAMP}.txt" 2>/dev/null || true
    
    if [ -s "${REPORT_DIR}/custom_secrets_${TIMESTAMP}.txt" ]; then
        CUSTOM_COUNT=$(wc -l < "${REPORT_DIR}/custom_secrets_${TIMESTAMP}.txt")
        log "${RED}⚠️  Custom scan found ${CUSTOM_COUNT} potential hardcoded secrets${NC}"
    else
        log "${GREEN}✅ Custom scan: No hardcoded secrets found${NC}"
    fi
}

# Function to run dependency scanning
scan_dependencies() {
    log "${BLUE}🔍 Phase 2: Dependency Vulnerability Scanning${NC}"
    
    # Safety check for Python dependencies
    if command_exists safety; then
        log "${YELLOW}Running Safety check for Python dependencies...${NC}"
        safety check --json --output "${REPORT_DIR}/safety_${TIMESTAMP}.json" 2>/dev/null || true
        safety check --short-report | tee -a "$LOG_FILE" || true
    fi
    
    # Bandit security linting
    if command_exists bandit; then
        log "${YELLOW}Running Bandit security analysis...${NC}"
        bandit -r . -f json -o "${REPORT_DIR}/bandit_${TIMESTAMP}.json" 2>/dev/null || true
        bandit -r . -f txt | tee -a "$LOG_FILE" || true
    fi
    
    # Semgrep static analysis
    if command_exists semgrep; then
        log "${YELLOW}Running Semgrep static analysis...${NC}"
        semgrep --config=auto --json --output="${REPORT_DIR}/semgrep_${TIMESTAMP}.json" . 2>/dev/null || true
        semgrep --config=auto . | tee -a "$LOG_FILE" || true
    fi
}

# Function to run infrastructure security scanning
scan_infrastructure() {
    log "${BLUE}🔍 Phase 3: Infrastructure Security Scanning${NC}"
    
    # Terraform security scan
    if find . -name "*.tf" -type f | head -1 | grep -q "."; then
        log "${YELLOW}Scanning Terraform files for security issues...${NC}"
        
        # Check for hardcoded secrets in Terraform
        grep -r -i -E "(password|secret|key|token).*=.*['\"][^'\"]{8,}" . \
            --include="*.tf" \
            --include="*.tfvars" > "${REPORT_DIR}/terraform_secrets_${TIMESTAMP}.txt" 2>/dev/null || true
        
        if [ -s "${REPORT_DIR}/terraform_secrets_${TIMESTAMP}.txt" ]; then
            TF_COUNT=$(wc -l < "${REPORT_DIR}/terraform_secrets_${TIMESTAMP}.txt")
            log "${RED}⚠️  Found ${TF_COUNT} potential hardcoded secrets in Terraform files${NC}"
        else
            log "${GREEN}✅ Terraform: No hardcoded secrets found${NC}"
        fi
    fi
    
    # Kubernetes security scan
    if find . -name "*.yaml" -o -name "*.yml" | grep -E "(k8s|kubernetes)" | head -1 | grep -q "."; then
        log "${YELLOW}Scanning Kubernetes manifests...${NC}"
        
        # Check for security issues in K8s manifests
        find . -name "*.yaml" -o -name "*.yml" | xargs grep -l "kind:" | while read -r file; do
            if grep -q "runAsRoot.*true\|privileged.*true\|allowPrivilegeEscalation.*true" "$file"; then
                echo "Security issue in $file" >> "${REPORT_DIR}/k8s_security_${TIMESTAMP}.txt"
            fi
        done 2>/dev/null || true
        
        if [ -s "${REPORT_DIR}/k8s_security_${TIMESTAMP}.txt" ]; then
            K8S_COUNT=$(wc -l < "${REPORT_DIR}/k8s_security_${TIMESTAMP}.txt")
            log "${RED}⚠️  Found ${K8S_COUNT} potential security issues in Kubernetes manifests${NC}"
        else
            log "${GREEN}✅ Kubernetes: No security issues found${NC}"
        fi
    fi
}

# Function to run comprehensive security tests
run_comprehensive_tests() {
    log "${BLUE}🔍 Phase 4: Comprehensive Security Testing${NC}"
    
    if [ -f "tests/security/test_security_scan.py" ]; then
        log "${YELLOW}Running comprehensive security scanner...${NC}"
        cd tests && python security/test_security_scan.py || true
        cd ..
    fi
    
    # Run pytest security tests
    if [ -d "tests" ]; then
        log "${YELLOW}Running pytest security tests...${NC}"
        python -m pytest tests/security/ -v --json-report --json-report-file="${REPORT_DIR}/pytest_security_${TIMESTAMP}.json" || true
    fi
}

# Function to run BDD tests
run_bdd_tests() {
    log "${BLUE}🥒 Phase 5: BDD Feature Testing${NC}"
    
    if [ -f "tests/features/security_and_functionality.feature" ]; then
        log "${YELLOW}Running BDD tests with Behave...${NC}"
        cd tests
        behave features/ --format=json --outfile="../${REPORT_DIR}/bdd_${TIMESTAMP}.json" || true
        behave features/ --format=pretty | tee -a "../$LOG_FILE" || true
        cd ..
    fi
}

# Function to run UI security tests
run_ui_tests() {
    log "${BLUE}🖥️  Phase 6: UI Security Testing${NC}"
    
    if [ -f "tests/selenium/test_ui.py" ]; then
        log "${YELLOW}Running Selenium UI security tests...${NC}"
        python -m pytest tests/selenium/test_ui.py -v --html="${REPORT_DIR}/ui_test_${TIMESTAMP}.html" --self-contained-html || true
    fi
}

# Function to generate comprehensive report
generate_report() {
    log "${BLUE}📊 Generating Comprehensive Security Report${NC}"
    
    REPORT_FILE="${REPORT_DIR}/comprehensive_security_report_${TIMESTAMP}.html"
    
    cat > "$REPORT_FILE" << EOF
<!DOCTYPE html>
<html>
<head>
    <title>Azure-GCP DR Orchestrator Security Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }
        .section { margin: 20px 0; padding: 15px; border-left: 4px solid #3498db; }
        .critical { border-left-color: #e74c3c; background: #fdf2f2; }
        .warning { border-left-color: #f39c12; background: #fef9e7; }
        .success { border-left-color: #27ae60; background: #eafaf1; }
        .info { border-left-color: #3498db; background: #ebf3fd; }
        pre { background: #f4f4f4; padding: 10px; border-radius: 3px; overflow-x: auto; }
        .file-list { max-height: 200px; overflow-y: auto; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔒 Azure-GCP DR Orchestrator Security Report</h1>
        <p>Generated on: $(date)</p>
        <p>Repository: Azure-GCP DR Orchestrator</p>
    </div>

    <div class="section info">
        <h2>📋 Executive Summary</h2>
        <p>This report contains the results of comprehensive security testing including:</p>
        <ul>
            <li>Secrets and credentials scanning</li>
            <li>Dependency vulnerability assessment</li>
            <li>Static code analysis</li>
            <li>Infrastructure security review</li>
            <li>BDD functional testing</li>
            <li>UI security testing</li>
        </ul>
    </div>

    <div class="section">
        <h2>🔍 Secrets Scanning Results</h2>
EOF

    # Add secrets scanning results
    if [ -s "${REPORT_DIR}/trufflehog_${TIMESTAMP}.json" ]; then
        echo '<div class="critical"><h3>TruffleHog Results</h3>' >> "$REPORT_FILE"
        echo '<p>Potential secrets detected. Review the JSON report for details.</p></div>' >> "$REPORT_FILE"
    else
        echo '<div class="success"><h3>TruffleHog Results</h3><p>✅ No secrets detected</p></div>' >> "$REPORT_FILE"
    fi

    if [ -s "${REPORT_DIR}/gitleaks_${TIMESTAMP}.json" ]; then
        echo '<div class="critical"><h3>GitLeaks Results</h3>' >> "$REPORT_FILE"
        echo '<p>Potential leaks detected. Review the JSON report for details.</p></div>' >> "$REPORT_FILE"
    else
        echo '<div class="success"><h3>GitLeaks Results</h3><p>✅ No leaks detected</p></div>' >> "$REPORT_FILE"
    fi

    # Add footer
    cat >> "$REPORT_FILE" << EOF
    </div>

    <div class="section">
        <h2>📁 Report Files Generated</h2>
        <div class="file-list">
            <ul>
EOF

    # List all generated report files
    find "$REPORT_DIR" -name "*${TIMESTAMP}*" -type f | while read -r file; do
        echo "<li>$(basename "$file")</li>" >> "$REPORT_FILE"
    done

    cat >> "$REPORT_FILE" << EOF
            </ul>
        </div>
    </div>

    <div class="section info">
        <h2>🔧 Next Steps</h2>
        <ol>
            <li>Review all flagged security issues</li>
            <li>Remediate critical and high severity vulnerabilities</li>
            <li>Update dependencies with known vulnerabilities</li>
            <li>Implement additional security controls as needed</li>
            <li>Re-run security tests to verify fixes</li>
        </ol>
    </div>
</body>
</html>
EOF

    log "${GREEN}✅ Comprehensive report generated: $REPORT_FILE${NC}"
}

# Function to cleanup old reports
cleanup_old_reports() {
    log "${YELLOW}🧹 Cleaning up reports older than 7 days...${NC}"
    find "$REPORT_DIR" -name "*.json" -o -name "*.txt" -o -name "*.html" -mtime +7 -delete 2>/dev/null || true
}

# Main execution
main() {
    log "${BLUE}Starting comprehensive security testing at $(date)${NC}"
    
    # Check if we're in a git repository
    if [ ! -d ".git" ]; then
        log "${YELLOW}⚠️  Not in a git repository. Some scans may not work properly.${NC}"
    fi
    
    # Install required tools
    install_tools
    
    # Run all security tests
    scan_secrets
    scan_dependencies
    scan_infrastructure
    run_comprehensive_tests
    run_bdd_tests
    run_ui_tests
    
    # Generate comprehensive report
    generate_report
    
    # Cleanup old reports
    cleanup_old_reports
    
    log "${GREEN}🎉 Security testing completed successfully!${NC}"
    log "${BLUE}📊 Reports available in: $REPORT_DIR${NC}"
    log "${BLUE}📋 Main report: ${REPORT_DIR}/comprehensive_security_report_${TIMESTAMP}.html${NC}"
    
    # Summary
    echo ""
    echo -e "${BLUE}📈 Security Testing Summary${NC}"
    echo -e "${BLUE}===========================${NC}"
    echo -e "Total files scanned: $(find . -type f | wc -l)"
    echo -e "Reports generated: $(find "$REPORT_DIR" -name "*${TIMESTAMP}*" | wc -l)"
    echo -e "Log file: $LOG_FILE"
    echo ""
    
    # Check for critical issues
    CRITICAL_ISSUES=0
    
    if [ -s "${REPORT_DIR}/trufflehog_${TIMESTAMP}.json" ]; then
        ((CRITICAL_ISSUES++))
    fi
    
    if [ -s "${REPORT_DIR}/gitleaks_${TIMESTAMP}.json" ]; then
        ((CRITICAL_ISSUES++))
    fi
    
    if [ -s "${REPORT_DIR}/custom_secrets_${TIMESTAMP}.txt" ]; then
        ((CRITICAL_ISSUES++))
    fi
    
    if [ $CRITICAL_ISSUES -gt 0 ]; then
        log "${RED}⚠️  ${CRITICAL_ISSUES} critical security issues detected! Review reports immediately.${NC}"
        exit 1
    else
        log "${GREEN}✅ No critical security issues detected.${NC}"
    fi
}

# Run main function
main "$@"
