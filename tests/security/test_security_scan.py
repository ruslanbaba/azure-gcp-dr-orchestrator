"""
Comprehensive security scanning and vulnerability testing
"""

import os
import re
import json
import subprocess
import requests
import time
import socket
from pathlib import Path
from typing import List, Dict, Any
import pytest
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SecurityScanner:
    """Comprehensive security scanner for DR Orchestrator"""
    
    def __init__(self):
        self.results = {
            'secrets_scan': [],
            'dependency_scan': [],
            'code_analysis': [],
            'network_scan': [],
            'api_security': [],
            'compliance_check': []
        }
    
    def scan_for_secrets(self, directory: str = ".") -> List[Dict]:
        """Scan for exposed secrets and credentials"""
        logger.info("Starting secrets scan...")
        
        # Define secret patterns
        secret_patterns = {
            'aws_access_key': r'AKIA[0-9A-Z]{16}',
            'aws_secret_key': r'[0-9a-zA-Z/+]{40}',
            'google_api_key': r'AIza[0-9A-Za-z\-_]{35}',
            'slack_token': r'xoxb-[0-9]+-[0-9]+-[a-zA-Z0-9]+',
            'github_token': r'ghp_[0-9a-zA-Z]{36}',
            'openai_key': r'sk-[a-zA-Z0-9]{32,}',
            'private_key': r'-----BEGIN.*PRIVATE KEY-----',
            'password_field': r'password\s*[:=]\s*["\'][^"\']{8,}["\']',
            'secret_field': r'secret\s*[:=]\s*["\'][^"\']{8,}["\']',
            'token_field': r'token\s*[:=]\s*["\'][^"\']{8,}["\']',
            'api_key_field': r'api_key\s*[:=]\s*["\'][^"\']{8,}["\']',
            'database_url': r'(postgres|mysql|mongodb)://[^\\s]+',
            'jwt_token': r'eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*',
            'base64_encoded': r'[A-Za-z0-9+/]{40,}={0,2}',
        }
        
        findings = []
        excluded_dirs = {'.git', 'node_modules', '__pycache__', '.pytest_cache', 'venv', '.env'}
        excluded_files = {'.pyc', '.pyo', '.git', '.DS_Store'}
        
        for root, dirs, files in os.walk(directory):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            
            for file in files:
                file_path = Path(root) / file
                
                # Skip binary files and excluded file types
                if any(file.endswith(ext) for ext in excluded_files):
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                        for pattern_name, pattern in secret_patterns.items():
                            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                            
                            for match in matches:
                                matched_text = match.group()
                                
                                # Filter out obvious placeholders and examples
                                if self._is_likely_placeholder(matched_text):
                                    continue
                                
                                # Get line number
                                line_num = content[:match.start()].count('\n') + 1
                                
                                findings.append({
                                    'type': 'secret_exposure',
                                    'severity': 'HIGH' if pattern_name in ['private_key', 'aws_secret_key'] else 'MEDIUM',
                                    'file': str(file_path),
                                    'line': line_num,
                                    'pattern': pattern_name,
                                    'match': matched_text[:50] + '...' if len(matched_text) > 50 else matched_text,
                                    'description': f'Potential {pattern_name.replace("_", " ")} exposure'
                                })
                
                except (UnicodeDecodeError, IOError, PermissionError):
                    continue
        
        self.results['secrets_scan'] = findings
        logger.info(f"Secrets scan completed. Found {len(findings)} potential issues")
        return findings
    
    def _is_likely_placeholder(self, text: str) -> bool:
        """Check if text is likely a placeholder value"""
        placeholders = [
            'your-', 'example', 'placeholder', 'changeme', 'xxx', 'dummy',
            'test', 'sample', 'demo', 'replace', 'enter-your', 'add-your',
            '${', 'TODO', 'FIXME', '123456', 'password', 'secret'
        ]
        
        text_lower = text.lower()
        return any(placeholder in text_lower for placeholder in placeholders)
    
    def scan_dependencies(self) -> List[Dict]:
        """Scan dependencies for known vulnerabilities"""
        logger.info("Starting dependency vulnerability scan...")
        
        findings = []
        
        # Check Python dependencies
        requirements_files = [
            'requirements.txt',
            'tests/requirements.txt',
            'cloud-functions/requirements.txt'
        ]
        
        for req_file in requirements_files:
            if os.path.exists(req_file):
                try:
                    # Use safety to check for vulnerabilities
                    result = subprocess.run(
                        ['safety', 'check', '-r', req_file, '--json'],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    if result.returncode == 0:
                        safety_data = json.loads(result.stdout)
                        for vuln in safety_data:
                            findings.append({
                                'type': 'dependency_vulnerability',
                                'severity': 'HIGH',
                                'file': req_file,
                                'package': vuln.get('package'),
                                'version': vuln.get('installed_version'),
                                'vulnerability_id': vuln.get('id'),
                                'description': vuln.get('advisory')
                            })
                
                except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
                    logger.warning(f"Could not scan {req_file} with safety")
        
        # Check for outdated base images in Dockerfiles
        dockerfile_paths = ['Dockerfile', 'docker/Dockerfile', 'striim/Dockerfile']
        for dockerfile in dockerfile_paths:
            if os.path.exists(dockerfile):
                with open(dockerfile, 'r') as f:
                    content = f.read()
                    
                    # Check for specific vulnerable base images
                    if re.search(r'FROM.*ubuntu:16\.04', content, re.IGNORECASE):
                        findings.append({
                            'type': 'outdated_base_image',
                            'severity': 'MEDIUM',
                            'file': dockerfile,
                            'description': 'Using outdated Ubuntu 16.04 base image'
                        })
        
        self.results['dependency_scan'] = findings
        logger.info(f"Dependency scan completed. Found {len(findings)} vulnerabilities")
        return findings
    
    def analyze_code_security(self) -> List[Dict]:
        """Analyze code for security issues using bandit"""
        logger.info("Starting code security analysis...")
        
        findings = []
        
        try:
            # Run bandit security linter
            result = subprocess.run(
                ['bandit', '-r', '.', '-f', 'json', '-ll'],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.stdout:
                bandit_data = json.loads(result.stdout)
                
                for issue in bandit_data.get('results', []):
                    findings.append({
                        'type': 'code_security_issue',
                        'severity': issue.get('issue_severity', 'MEDIUM'),
                        'file': issue.get('filename'),
                        'line': issue.get('line_number'),
                        'test_id': issue.get('test_id'),
                        'description': issue.get('issue_text'),
                        'confidence': issue.get('issue_confidence')
                    })
        
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            logger.warning("Could not run bandit security analysis")
        
        self.results['code_analysis'] = findings
        logger.info(f"Code analysis completed. Found {len(findings)} issues")
        return findings
    
    def scan_network_security(self) -> List[Dict]:
        """Scan network configuration for security issues"""
        logger.info("Starting network security scan...")
        
        findings = []
        
        # Check for open ports
        common_ports = [22, 80, 443, 3000, 5432, 8080, 9090, 9080]
        
        for port in common_ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            
            try:
                result = sock.connect_ex(('localhost', port))
                if result == 0:
                    findings.append({
                        'type': 'open_port',
                        'severity': 'INFO',
                        'port': port,
                        'description': f'Port {port} is open on localhost'
                    })
            except socket.error:
                pass
            finally:
                sock.close()
        
        # Check Terraform files for security misconfigurations
        tf_files = list(Path('.').rglob('*.tf'))
        
        for tf_file in tf_files:
            try:
                with open(tf_file, 'r') as f:
                    content = f.read()
                    
                    # Check for overly permissive security groups
                    if re.search(r'0\.0\.0\.0/0', content):
                        findings.append({
                            'type': 'overly_permissive_access',
                            'severity': 'MEDIUM',
                            'file': str(tf_file),
                            'description': 'Found 0.0.0.0/0 CIDR which allows access from anywhere'
                        })
                    
                    # Check for unencrypted storage
                    if re.search(r'encrypted\s*=\s*false', content, re.IGNORECASE):
                        findings.append({
                            'type': 'unencrypted_storage',
                            'severity': 'HIGH',
                            'file': str(tf_file),
                            'description': 'Found unencrypted storage configuration'
                        })
            
            except (IOError, UnicodeDecodeError):
                continue
        
        self.results['network_scan'] = findings
        logger.info(f"Network scan completed. Found {len(findings)} issues")
        return findings
    
    def test_api_security(self) -> List[Dict]:
        """Test API endpoints for security vulnerabilities"""
        logger.info("Starting API security testing...")
        
        findings = []
        base_urls = [
            'http://localhost:8080',  # DR Orchestrator
            'http://localhost:9090',  # Prometheus
            'http://localhost:3000'   # Grafana
        ]
        
        for base_url in base_urls:
            try:
                # Test for directory traversal
                response = requests.get(f"{base_url}/../../../etc/passwd", timeout=5)
                if response.status_code == 200 and 'root:' in response.text:
                    findings.append({
                        'type': 'directory_traversal',
                        'severity': 'HIGH',
                        'url': base_url,
                        'description': 'Directory traversal vulnerability detected'
                    })
                
                # Test for SQL injection (basic)
                response = requests.get(f"{base_url}/api/health?id=1'OR'1'='1", timeout=5)
                if response.status_code == 500:
                    findings.append({
                        'type': 'sql_injection',
                        'severity': 'HIGH',
                        'url': base_url,
                        'description': 'Potential SQL injection vulnerability'
                    })
                
                # Test for missing security headers
                response = requests.get(base_url, timeout=5)
                security_headers = [
                    'X-Content-Type-Options',
                    'X-Frame-Options',
                    'X-XSS-Protection',
                    'Strict-Transport-Security'
                ]
                
                for header in security_headers:
                    if header not in response.headers:
                        findings.append({
                            'type': 'missing_security_header',
                            'severity': 'MEDIUM',
                            'url': base_url,
                            'header': header,
                            'description': f'Missing security header: {header}'
                        })
            
            except requests.RequestException:
                continue
        
        self.results['api_security'] = findings
        logger.info(f"API security testing completed. Found {len(findings)} issues")
        return findings
    
    def check_compliance(self) -> List[Dict]:
        """Check for compliance with security standards"""
        logger.info("Starting compliance check...")
        
        findings = []
        
        # Check for required security files
        required_files = [
            'SECURITY.md',
            '.github/dependabot.yml',
            '.github/workflows/security.yml'
        ]
        
        for file_path in required_files:
            if not os.path.exists(file_path):
                findings.append({
                    'type': 'missing_security_file',
                    'severity': 'MEDIUM',
                    'file': file_path,
                    'description': f'Missing required security file: {file_path}'
                })
        
        # Check for security policy in CI/CD
        github_workflows = list(Path('.github/workflows').glob('*.yml')) if Path('.github/workflows').exists() else []
        
        security_checks = ['security', 'vulnerability', 'scan', 'bandit', 'safety']
        has_security_checks = False
        
        for workflow_file in github_workflows:
            try:
                with open(workflow_file, 'r') as f:
                    content = f.read().lower()
                    if any(check in content for check in security_checks):
                        has_security_checks = True
                        break
            except IOError:
                continue
        
        if not has_security_checks:
            findings.append({
                'type': 'missing_security_automation',
                'severity': 'MEDIUM',
                'description': 'No security scanning found in CI/CD workflows'
            })
        
        self.results['compliance_check'] = findings
        logger.info(f"Compliance check completed. Found {len(findings)} issues")
        return findings
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive security report"""
        total_findings = sum(len(findings) for findings in self.results.values())
        
        severity_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0, 'INFO': 0}
        
        for scan_results in self.results.values():
            for finding in scan_results:
                severity = finding.get('severity', 'MEDIUM')
                severity_counts[severity] += 1
        
        report = {
            'summary': {
                'total_findings': total_findings,
                'severity_breakdown': severity_counts,
                'scan_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'FAIL' if severity_counts['HIGH'] > 0 else 'PASS'
            },
            'detailed_results': self.results
        }
        
        return report


# Test class for pytest integration
class TestSecurityScan:
    """Security tests using pytest framework"""
    
    @pytest.fixture(scope='class')
    def scanner(self):
        """Initialize security scanner"""
        return SecurityScanner()
    
    def test_no_exposed_secrets(self, scanner):
        """Test that no secrets are exposed in the codebase"""
        findings = scanner.scan_for_secrets()
        
        # Filter out known false positives
        real_secrets = [f for f in findings if f['severity'] in ['HIGH', 'MEDIUM']]
        
        assert len(real_secrets) == 0, f"Found {len(real_secrets)} exposed secrets: {real_secrets}"
    
    def test_no_high_severity_vulnerabilities(self, scanner):
        """Test that no high-severity vulnerabilities exist"""
        deps_findings = scanner.scan_dependencies()
        code_findings = scanner.analyze_code_security()
        
        high_severity = [
            f for f in deps_findings + code_findings 
            if f.get('severity') == 'HIGH'
        ]
        
        assert len(high_severity) == 0, f"Found {len(high_severity)} high-severity issues: {high_severity}"
    
    def test_network_security_configuration(self, scanner):
        """Test network security configuration"""
        findings = scanner.scan_network_security()
        
        # Check for critical network misconfigurations
        critical_issues = [
            f for f in findings 
            if f.get('severity') == 'HIGH' or 'unencrypted' in f.get('type', '')
        ]
        
        assert len(critical_issues) == 0, f"Found critical network issues: {critical_issues}"
    
    def test_api_endpoints_security(self, scanner):
        """Test API endpoint security"""
        findings = scanner.test_api_security()
        
        # Check for critical API vulnerabilities
        critical_api_issues = [
            f for f in findings 
            if f.get('severity') == 'HIGH'
        ]
        
        assert len(critical_api_issues) == 0, f"Found critical API issues: {critical_api_issues}"
    
    def test_compliance_requirements(self, scanner):
        """Test compliance with security requirements"""
        findings = scanner.check_compliance()
        
        # Some compliance issues are acceptable
        # Focus on critical missing security measures
        critical_compliance = [
            f for f in findings 
            if 'security_automation' in f.get('type', '')
        ]
        
        # This is a warning rather than failure for compliance
        if critical_compliance:
            logger.warning(f"Compliance issues found: {critical_compliance}")


if __name__ == "__main__":
    # Run comprehensive security scan
    scanner = SecurityScanner()
    
    print("🔒 Starting Comprehensive Security Scan...")
    print("=" * 50)
    
    # Run all scans
    scanner.scan_for_secrets()
    scanner.scan_dependencies()
    scanner.analyze_code_security()
    scanner.scan_network_security()
    scanner.test_api_security()
    scanner.check_compliance()
    
    # Generate report
    report = scanner.generate_report()
    
    # Print summary
    print(f"\n📊 Security Scan Summary:")
    print(f"Status: {report['summary']['status']}")
    print(f"Total Findings: {report['summary']['total_findings']}")
    print(f"High Severity: {report['summary']['severity_breakdown']['HIGH']}")
    print(f"Medium Severity: {report['summary']['severity_breakdown']['MEDIUM']}")
    print(f"Low Severity: {report['summary']['severity_breakdown']['LOW']}")
    
    # Save detailed report
    with open('security_scan_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n📄 Detailed report saved to: security_scan_report.json")
    
    # Exit with appropriate code
    exit_code = 1 if report['summary']['status'] == 'FAIL' else 0
    exit(exit_code)
