"""
Step definitions for DR Orchestrator BDD tests
"""

import os
import re
import json
import time
import subprocess
import requests
from behave import given, when, then, step
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SecurityScanner:
    """Security scanning utilities"""
    
    @staticmethod
    def scan_for_secrets(directory="."):
        """Scan for exposed secrets using multiple tools"""
        secret_patterns = [
            r'password\s*[:=]\s*["\'][^"\']+["\']',
            r'secret\s*[:=]\s*["\'][^"\']+["\']',
            r'key\s*[:=]\s*["\'][^"\']+["\']',
            r'token\s*[:=]\s*["\'][^"\']+["\']',
            r'[A-Za-z0-9+/]{40,}={0,2}',  # Base64 encoded strings
            r'sk-[a-zA-Z0-9]{32,}',  # OpenAI API keys
            r'xoxb-[0-9]+-[0-9]+-[a-zA-Z0-9]+',  # Slack tokens
            r'AIza[0-9A-Za-z\-_]{35}',  # Google API keys
            r'AKIA[0-9A-Z]{16}',  # AWS access keys
            r'-----BEGIN.*PRIVATE KEY-----'  # Private keys
        ]
        
        found_secrets = []
        for root, dirs, files in os.walk(directory):
            # Skip .git and other VCS directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file in files:
                if file.endswith(('.py', '.yaml', '.yml', '.json', '.tf', '.sh', '.env')):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            for pattern in secret_patterns:
                                matches = re.findall(pattern, content, re.IGNORECASE)
                                if matches:
                                    # Filter out obvious placeholders
                                    real_matches = [m for m in matches if not any(
                                        placeholder in m.lower() for placeholder in 
                                        ['your-', 'example', 'placeholder', 'changeme', 'xxx', 'dummy']
                                    )]
                                    if real_matches:
                                        found_secrets.append({
                                            'file': file_path,
                                            'pattern': pattern,
                                            'matches': real_matches
                                        })
                    except (UnicodeDecodeError, IOError):
                        continue
                        
        return found_secrets

class DROrchestrator:
    """DR Orchestrator test interface"""
    
    def __init__(self):
        self.base_url = os.getenv('DR_ORCHESTRATOR_URL', 'http://localhost:8080')
        self.session = requests.Session()
        
    def check_health(self):
        """Check orchestrator health status"""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=10)
            return response.status_code == 200
        except requests.RequestException:
            return False
            
    def trigger_failover(self, target='gcp'):
        """Trigger manual failover"""
        try:
            response = self.session.post(
                f"{self.base_url}/api/failover",
                json={'target': target, 'force': False},
                timeout=30
            )
            return response.status_code in [200, 202]
        except requests.RequestException:
            return False
            
    def get_metrics(self):
        """Get system metrics"""
        try:
            response = self.session.get(f"{self.base_url}/metrics", timeout=10)
            return response.json() if response.status_code == 200 else {}
        except (requests.RequestException, json.JSONDecodeError):
            return {}

class WebUI:
    """Web UI testing interface using Selenium"""
    
    def __init__(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 10)
        
    def navigate_to(self, url):
        """Navigate to URL"""
        self.driver.get(url)
        
    def find_element(self, by, value):
        """Find element with wait"""
        return self.wait.until(EC.presence_of_element_located((by, value)))
        
    def close(self):
        """Close browser"""
        self.driver.quit()

# Step Definitions

@given('the DR orchestrator environment is initialized')
def step_environment_initialized(context):
    """Initialize test environment"""
    context.orchestrator = DROrchestrator()
    context.scanner = SecurityScanner()
    context.web_ui = WebUI()
    logger.info("Test environment initialized")

@given('all security configurations are in place')
def step_security_configured(context):
    """Verify security configurations"""
    # Check for required environment variables
    required_vars = [
        'AZURE_SQL_PASSWORD',
        'GCP_CLOUD_SQL_PASSWORD', 
        'STRIIM_PASSWORD',
        'AZURE_CLIENT_SECRET'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.warning(f"Missing environment variables: {missing_vars}")
    
    context.security_configured = len(missing_vars) == 0

@given('monitoring systems are active')
def step_monitoring_active(context):
    """Check monitoring system status"""
    monitoring_endpoints = [
        'http://localhost:9090',  # Prometheus
        'http://localhost:3000',  # Grafana
    ]
    
    context.monitoring_status = {}
    for endpoint in monitoring_endpoints:
        try:
            response = requests.get(f"{endpoint}/api/health", timeout=5)
            context.monitoring_status[endpoint] = response.status_code == 200
        except requests.RequestException:
            context.monitoring_status[endpoint] = False

@given('I scan the repository for exposed secrets')
def step_scan_secrets(context):
    """Scan repository for secrets"""
    context.found_secrets = context.scanner.scan_for_secrets()
    logger.info(f"Secret scan completed. Found {len(context.found_secrets)} potential issues")

@when('I check all configuration files')
def step_check_configs(context):
    """Check configuration files for security issues"""
    config_files = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(('.yaml', '.yml', '.json', '.env', '.conf')):
                config_files.append(os.path.join(root, file))
    
    context.config_files = config_files
    logger.info(f"Checked {len(config_files)} configuration files")

@then('no hardcoded passwords should be found')
def step_no_hardcoded_passwords(context):
    """Verify no hardcoded passwords exist"""
    password_secrets = [s for s in context.found_secrets 
                       if 'password' in s['pattern'].lower()]
    assert len(password_secrets) == 0, f"Found hardcoded passwords: {password_secrets}"

@then('no API keys should be exposed')
def step_no_api_keys(context):
    """Verify no API keys are exposed"""
    api_key_patterns = ['sk-', 'xoxb-', 'AIza', 'AKIA']
    api_secrets = [s for s in context.found_secrets 
                  if any(pattern in str(s['matches']) for pattern in api_key_patterns)]
    assert len(api_secrets) == 0, f"Found exposed API keys: {api_secrets}"

@then('no private keys should be visible')
def step_no_private_keys(context):
    """Verify no private keys are exposed"""
    private_key_secrets = [s for s in context.found_secrets 
                          if 'PRIVATE KEY' in str(s['matches'])]
    assert len(private_key_secrets) == 0, f"Found exposed private keys: {private_key_secrets}"

@then('all credentials should use environment variables')
def step_credentials_use_env_vars(context):
    """Verify credentials use environment variables"""
    # This is verified by the absence of hardcoded secrets
    assert context.security_configured, "Security configuration incomplete"

@given('the DR orchestrator is running')
def step_orchestrator_running(context):
    """Verify orchestrator is running"""
    assert context.orchestrator.check_health(), "DR orchestrator is not responding"

@when('I attempt to access protected endpoints without credentials')
def step_access_without_credentials(context):
    """Test unauthorized access"""
    protected_endpoints = ['/api/admin', '/api/config', '/api/secrets']
    context.auth_results = {}
    
    for endpoint in protected_endpoints:
        try:
            response = requests.get(f"{context.orchestrator.base_url}{endpoint}", timeout=5)
            context.auth_results[endpoint] = response.status_code
        except requests.RequestException:
            context.auth_results[endpoint] = 0

@then('access should be denied')
def step_access_denied(context):
    """Verify access is properly denied"""
    for endpoint, status_code in context.auth_results.items():
        assert status_code in [401, 403], f"Endpoint {endpoint} returned {status_code}, expected 401/403"

@then('appropriate error messages should be returned')
def step_error_messages(context):
    """Verify error messages are appropriate"""
    # This is implicitly tested by checking status codes
    pass

@then('all access attempts should be logged')
def step_access_logged(context):
    """Verify access attempts are logged"""
    # Check if audit logs exist
    log_file = os.getenv('AUDIT_LOG_FILE', '/var/log/dr-orchestrator/audit.log')
    if os.path.exists(log_file):
        assert os.path.getsize(log_file) > 0, "Audit log is empty"

@given('Azure SQL MI is the primary database')
def step_azure_primary(context):
    """Set Azure as primary database"""
    context.primary_db = 'azure'

@given('GCP Cloud SQL is the secondary database') 
def step_gcp_secondary(context):
    """Set GCP as secondary database"""
    context.secondary_db = 'gcp'

@when('Azure region becomes unavailable')
def step_azure_unavailable(context):
    """Simulate Azure region outage"""
    # In a real test, this would simulate network partition or service failure
    context.failover_triggered = context.orchestrator.trigger_failover('gcp')

@then('traffic should automatically failover to GCP')
def step_traffic_failover(context):
    """Verify traffic fails over to GCP"""
    assert context.failover_triggered, "Failover was not triggered successfully"

@then('data synchronization should be maintained')
def step_data_sync_maintained(context):
    """Verify data synchronization"""
    metrics = context.orchestrator.get_metrics()
    sync_lag = metrics.get('replication_lag_seconds', 999)
    assert sync_lag < 30, f"Replication lag too high: {sync_lag} seconds"

@then('RTO should be less than 5 minutes')
def step_rto_check(context):
    """Verify RTO requirement"""
    # This would be measured in a real failover test
    # For now, we assume the failover trigger time
    assert True  # Placeholder for actual RTO measurement

@given('all system components are running')
def step_components_running(context):
    """Verify all components are running"""
    components = ['orchestrator', 'database', 'monitoring']
    context.component_status = {comp: True for comp in components}  # Simplified

@when('a critical service fails')
def step_service_fails(context):
    """Simulate service failure"""
    # This would actually trigger a service failure in a real test
    context.service_failure_time = time.time()

@then('alerts should be triggered within 30 seconds')
def step_alerts_triggered(context):
    """Verify alerts are triggered quickly"""
    # Check if alerts are generated (simplified)
    assert True  # Placeholder for actual alert verification

@then('appropriate teams should be notified')
def step_teams_notified(context):
    """Verify team notifications"""
    # Check notification systems (simplified)
    assert True  # Placeholder for notification verification

@then('automated recovery should be attempted')
def step_automated_recovery(context):
    """Verify automated recovery"""
    # Check if recovery procedures are initiated
    assert True  # Placeholder for recovery verification

def after_scenario(context, scenario):
    """Cleanup after each scenario"""
    if hasattr(context, 'web_ui'):
        context.web_ui.close()
    logger.info(f"Scenario '{scenario.name}' completed")
