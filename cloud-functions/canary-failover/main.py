"""
Enhanced Canary Failover Cloud Function with Security Hardening
Implements graduated failover with validation checkpoints
"""

import os
import time
import json
import logging
import subprocess
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from google.cloud import container_v1
from google.cloud import dns
from google.cloud import secretmanager
from google.cloud import monitoring_v3
from google.cloud import compute_v1
from google.cloud import pubsub_v1
import requests
from google.auth import default
from google.auth.transport import requests as google_requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class CanaryConfig:
    """Configuration for canary failover process"""
    project_id: str
    cluster_name: str
    cluster_location: str
    nodepool_name: str
    min_canary_replicas: int = 1
    full_scale_replicas: int = 3
    canary_validation_timeout: int = 300  # 5 minutes
    health_check_interval: int = 10  # seconds
    dns_zone: str = ""
    dns_record: str = ""
    static_ip_name: str = "dr-gcp-ip"

class SecurityHardenedFailover:
    """Enhanced failover orchestrator with security and canary deployment"""
    
    def __init__(self):
        self.config = self._load_secure_config()
        self.credentials, self.project_id = default()
        self.auth_request = google_requests.Request()
        
        # Initialize clients with proper authentication
        self.container_client = container_v1.ClusterManagerClient(credentials=self.credentials)
        self.dns_client = dns.Client(project=self.project_id, credentials=self.credentials)
        self.secret_client = secretmanager.SecretManagerServiceClient(credentials=self.credentials)
        self.monitoring_client = monitoring_v3.MetricServiceClient(credentials=self.credentials)
        self.compute_client = compute_v1.AddressesClient(credentials=self.credentials)
        
    def _load_secure_config(self) -> CanaryConfig:
        """Load configuration from secure sources"""
        try:
            return CanaryConfig(
                project_id=os.environ["PROJECT_ID"],
                cluster_name=os.environ["CLUSTER_NAME"],
                cluster_location=os.environ["GKE_LOCATION"],
                nodepool_name=os.environ["NODEPOOL_NAME"],
                min_canary_replicas=int(os.environ.get("CANARY_REPLICAS", "1")),
                full_scale_replicas=int(os.environ.get("FULL_SCALE_REPLICAS", "3")),
                dns_zone=os.environ.get("DNS_ZONE", ""),
                dns_record=os.environ.get("DNS_RECORD", ""),
                static_ip_name=os.environ.get("STATIC_IP_NAME", "dr-gcp-ip")
            )
        except KeyError as e:
            logger.error(f"Missing required environment variable: {e}")
            raise
    
    def _get_secret(self, secret_name: str) -> str:
        """Securely retrieve secrets from Secret Manager"""
        try:
            name = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
            response = self.secret_client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            logger.error(f"Failed to retrieve secret {secret_name}: {e}")
            raise
    
    def _authenticate_kubectl(self) -> None:
        """Authenticate kubectl with cluster using Workload Identity"""
        try:
            cmd = [
                "gcloud", "container", "clusters", "get-credentials",
                self.config.cluster_name,
                "--region", self.config.cluster_location,
                "--project", self.config.project_id
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info("Successfully authenticated with GKE cluster")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to authenticate with cluster: {e}")
            raise
    
    def _scale_nodepool(self, desired_nodes: int) -> None:
        """Scale the GKE nodepool with security validation"""
        try:
            # Validate scaling parameters
            if desired_nodes < 0 or desired_nodes > 10:  # Safety limit
                raise ValueError(f"Invalid node count: {desired_nodes}")
            
            request = container_v1.SetNodePoolSizeRequest(
                project_id=self.config.project_id,
                zone=self.config.cluster_location,
                cluster_id=self.config.cluster_name,
                node_pool_id=self.config.nodepool_name,
                node_count=desired_nodes
            )
            
            operation = self.container_client.set_node_pool_size(request=request)
            logger.info(f"Scaling nodepool to {desired_nodes} nodes. Operation: {operation.name}")
            
            # Wait for operation completion with timeout
            self._wait_for_operation(operation, timeout=600)
            
        except Exception as e:
            logger.error(f"Failed to scale nodepool: {e}")
            raise
    
    def _wait_for_operation(self, operation, timeout: int = 600) -> None:
        """Wait for GKE operation to complete with timeout"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            request = container_v1.GetOperationRequest(
                project_id=self.config.project_id,
                zone=self.config.cluster_location,
                operation_id=operation.name
            )
            
            op_status = self.container_client.get_operation(request=request)
            
            if op_status.status == container_v1.Operation.Status.DONE:
                if op_status.error:
                    raise Exception(f"Operation failed: {op_status.error}")
                logger.info("Operation completed successfully")
                return
            
            time.sleep(10)
        
        raise TimeoutError(f"Operation {operation.name} timed out after {timeout}s")
    
    def _wait_for_nodes_ready(self, expected_count: int, timeout: int = 300) -> None:
        """Wait for nodes to be ready with enhanced validation"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["kubectl", "get", "nodes", "--no-headers", "-o", "wide"],
                    capture_output=True, text=True, check=True
                )
                
                ready_nodes = [
                    line for line in result.stdout.splitlines()
                    if " Ready " in line and " NotReady " not in line
                ]
                
                if len(ready_nodes) >= expected_count:
                    logger.info(f"All {expected_count} nodes are ready")
                    return
                
                logger.info(f"Waiting for nodes: {len(ready_nodes)}/{expected_count} ready")
                
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to check node status: {e}")
            
            time.sleep(10)
        
        raise TimeoutError(f"Nodes not ready within {timeout}s")
    
    def _deploy_canary_application(self) -> None:
        """Deploy application in canary mode with security hardening"""
        try:
            # Apply namespace with security policies
            self._apply_secure_namespace()
            
            # Deploy canary version with minimal replicas
            canary_manifest = self._generate_canary_manifest()
            
            with open("/tmp/canary-deployment.yaml", "w") as f:
                f.write(canary_manifest)
            
            subprocess.run(
                ["kubectl", "apply", "-f", "/tmp/canary-deployment.yaml"],
                check=True, capture_output=True
            )
            
            logger.info("Canary deployment applied successfully")
            
        except Exception as e:
            logger.error(f"Failed to deploy canary application: {e}")
            raise
    
    def _apply_secure_namespace(self) -> None:
        """Apply namespace with enhanced security policies"""
        namespace_manifest = """
apiVersion: v1
kind: Namespace
metadata:
  name: dr-system
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: dr-network-policy
  namespace: dr-system
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: istio-system
    - namespaceSelector:
        matchLabels:
          name: kube-system
  egress:
  - to: []
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 5432  # PostgreSQL
    - protocol: UDP
      port: 53    # DNS
"""
        
        with open("/tmp/secure-namespace.yaml", "w") as f:
            f.write(namespace_manifest)
        
        subprocess.run(
            ["kubectl", "apply", "-f", "/tmp/secure-namespace.yaml"],
            check=True, capture_output=True
        )
    
    def _generate_canary_manifest(self) -> str:
        """Generate secure canary deployment manifest"""
        return f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dr-app-canary
  namespace: dr-system
  labels:
    app: dr-app
    version: canary
spec:
  replicas: {self.config.min_canary_replicas}
  selector:
    matchLabels:
      app: dr-app
      version: canary
  template:
    metadata:
      labels:
        app: dr-app
        version: canary
      annotations:
        sidecar.istio.io/inject: "true"
    spec:
      serviceAccountName: dr-app-service-account
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 2000
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: app
        image: {self._get_secret("app-image-url")}
        ports:
        - containerPort: 8080
          name: http
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: gcp-database-url
        - name: MODE
          value: "CANARY"
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 1000
          capabilities:
            drop:
            - ALL
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: cache
          mountPath: /app/cache
      volumes:
      - name: tmp
        emptyDir: {{}}
      - name: cache
        emptyDir: {{}}
---
apiVersion: v1
kind: Service
metadata:
  name: dr-app-canary-service
  namespace: dr-system
spec:
  selector:
    app: dr-app
    version: canary
  ports:
  - port: 80
    targetPort: 8080
    name: http
  type: ClusterIP
"""
    
    def _validate_canary_health(self) -> bool:
        """Validate canary deployment health with comprehensive checks"""
        try:
            logger.info("Starting canary validation...")
            
            # Wait for pods to be ready
            time.sleep(30)
            
            # Check pod status
            pod_check = subprocess.run(
                ["kubectl", "get", "pods", "-n", "dr-system", "-l", "version=canary", "-o", "jsonpath={.items[*].status.phase}"],
                capture_output=True, text=True, check=True
            )
            
            if "Running" not in pod_check.stdout:
                logger.error("Canary pods are not running")
                return False
            
            # Get service endpoint for health check
            service_ip = subprocess.run(
                ["kubectl", "get", "service", "dr-app-canary-service", "-n", "dr-system", "-o", "jsonpath={.spec.clusterIP}"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            
            # Perform health checks
            health_url = f"http://{service_ip}/health"
            
            for attempt in range(10):
                try:
                    # Use kubectl port-forward for secure access
                    port_forward = subprocess.Popen([
                        "kubectl", "port-forward", "-n", "dr-system",
                        "service/dr-app-canary-service", "8080:80"
                    ])
                    
                    time.sleep(5)  # Allow port-forward to establish
                    
                    response = requests.get("http://localhost:8080/health", timeout=10)
                    
                    port_forward.terminate()
                    port_forward.wait()
                    
                    if response.status_code == 200:
                        logger.info("Canary health check passed")
                        return True
                    
                except Exception as e:
                    logger.warning(f"Health check attempt {attempt + 1} failed: {e}")
                    if port_forward:
                        port_forward.terminate()
                
                time.sleep(15)
            
            logger.error("Canary health validation failed")
            return False
            
        except Exception as e:
            logger.error(f"Canary validation error: {e}")
            return False
    
    def _scale_to_full_deployment(self) -> None:
        """Scale canary to full deployment"""
        try:
            # Update deployment to full scale
            subprocess.run([
                "kubectl", "patch", "deployment", "dr-app-canary",
                "-n", "dr-system",
                "-p", f'{{"spec":{{"replicas":{self.config.full_scale_replicas}}}}}'
            ], check=True, capture_output=True)
            
            # Wait for all replicas to be ready
            subprocess.run([
                "kubectl", "rollout", "status", "deployment/dr-app-canary",
                "-n", "dr-system", "--timeout=300s"
            ], check=True, capture_output=True)
            
            logger.info(f"Successfully scaled to {self.config.full_scale_replicas} replicas")
            
        except Exception as e:
            logger.error(f"Failed to scale to full deployment: {e}")
            raise
    
    def _update_dns_with_validation(self) -> None:
        """Update DNS with validation and rollback capability"""
        try:
            if not self.config.dns_zone or not self.config.dns_record:
                logger.warning("DNS configuration not provided, skipping DNS update")
                return
            
            # Get the current static IP
            gcp_ip = self._get_static_ip()
            
            # Store current DNS record for rollback
            current_record = self._get_current_dns_record()
            
            # Update DNS record
            zone = self.dns_client.zone(self.config.dns_zone)
            changes = zone.changes()
            
            # Remove old record if exists
            if current_record:
                changes.delete_record_set(current_record)
            
            # Add new record
            new_record = zone.resource_record_set(
                name=f"{self.config.dns_record}.{zone.dns_name}",
                record_type="A",
                ttl=60,
                rrdatas=[gcp_ip]
            )
            changes.add_record_set(new_record)
            
            # Apply changes
            changes.create()
            
            # Wait for propagation
            while changes.status != 'done':
                time.sleep(5)
                changes.reload()
            
            logger.info(f"DNS updated successfully: {self.config.dns_record} -> {gcp_ip}")
            
            # Validate DNS propagation
            self._validate_dns_propagation(gcp_ip)
            
        except Exception as e:
            logger.error(f"DNS update failed: {e}")
            raise
    
    def _get_static_ip(self) -> str:
        """Get the reserved static IP address"""
        try:
            request = compute_v1.GetRequest(
                project=self.config.project_id,
                address=self.config.static_ip_name
            )
            
            address = self.compute_client.get(request=request)
            return address.address
            
        except Exception as e:
            logger.error(f"Failed to get static IP: {e}")
            raise
    
    def _get_current_dns_record(self):
        """Get current DNS record for backup"""
        try:
            zone = self.dns_client.zone(self.config.dns_zone)
            record_name = f"{self.config.dns_record}.{zone.dns_name}"
            
            for record in zone.list_resource_record_sets():
                if record.name == record_name and record.record_type == "A":
                    return record
            return None
            
        except Exception as e:
            logger.warning(f"Could not get current DNS record: {e}")
            return None
    
    def _validate_dns_propagation(self, expected_ip: str, timeout: int = 120) -> None:
        """Validate DNS propagation"""
        import socket
        
        start_time = time.time()
        domain = f"{self.config.dns_record}.{self.config.dns_zone.replace('-', '.')}"
        
        while time.time() - start_time < timeout:
            try:
                resolved_ip = socket.gethostbyname(domain)
                if resolved_ip == expected_ip:
                    logger.info(f"DNS propagation verified: {domain} -> {resolved_ip}")
                    return
            except Exception as e:
                logger.debug(f"DNS resolution attempt failed: {e}")
            
            time.sleep(10)
        
        logger.warning(f"DNS propagation validation timed out for {domain}")
    
    def _rollback_deployment(self) -> None:
        """Rollback deployment in case of failure"""
        try:
            logger.warning("Rolling back canary deployment...")
            
            # Delete the canary deployment
            subprocess.run([
                "kubectl", "delete", "deployment", "dr-app-canary",
                "-n", "dr-system", "--ignore-not-found=true"
            ], check=True, capture_output=True)
            
            # Scale down the nodepool
            self._scale_nodepool(0)
            
            logger.info("Rollback completed")
            
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
    
    def _publish_metrics(self, stage: str, success: bool, duration: float) -> None:
        """Publish custom metrics to Cloud Monitoring"""
        try:
            series = monitoring_v3.TimeSeries()
            series.metric.type = "custom.googleapis.com/dr/failover_stage"
            series.resource.type = "global"
            
            series.metric.labels["stage"] = stage
            series.metric.labels["success"] = str(success).lower()
            
            now = time.time()
            seconds = int(now)
            nanos = int((now - seconds) * 10 ** 9)
            interval = monitoring_v3.TimeInterval({"end_time": {"seconds": seconds, "nanos": nanos}})
            
            point = monitoring_v3.Point({
                "interval": interval,
                "value": {"double_value": duration}
            })
            series.points = [point]
            
            project_name = f"projects/{self.config.project_id}"
            self.monitoring_client.create_time_series(
                name=project_name, time_series=[series]
            )
            
        except Exception as e:
            logger.warning(f"Failed to publish metrics: {e}")
    
    def execute_canary_failover(self) -> Dict[str, Any]:
        """Execute the complete canary failover process"""
        start_time = time.time()
        stages = {}
        
        try:
            logger.info("Starting enhanced canary failover process")
            
            # Stage 1: Authentication and Setup
            stage_start = time.time()
            self._authenticate_kubectl()
            stages["authentication"] = time.time() - stage_start
            self._publish_metrics("authentication", True, stages["authentication"])
            
            # Stage 2: Scale nodepool for canary
            stage_start = time.time()
            self._scale_nodepool(self.config.min_canary_replicas)
            stages["nodepool_scale_canary"] = time.time() - stage_start
            self._publish_metrics("nodepool_scale_canary", True, stages["nodepool_scale_canary"])
            
            # Stage 3: Wait for nodes
            stage_start = time.time()
            self._wait_for_nodes_ready(self.config.min_canary_replicas)
            stages["nodes_ready"] = time.time() - stage_start
            self._publish_metrics("nodes_ready", True, stages["nodes_ready"])
            
            # Stage 4: Deploy canary
            stage_start = time.time()
            self._deploy_canary_application()
            stages["canary_deploy"] = time.time() - stage_start
            self._publish_metrics("canary_deploy", True, stages["canary_deploy"])
            
            # Stage 5: Validate canary
            stage_start = time.time()
            if not self._validate_canary_health():
                raise Exception("Canary validation failed")
            stages["canary_validation"] = time.time() - stage_start
            self._publish_metrics("canary_validation", True, stages["canary_validation"])
            
            # Stage 6: Scale to full deployment
            stage_start = time.time()
            self._scale_nodepool(self.config.full_scale_replicas)
            self._wait_for_nodes_ready(self.config.full_scale_replicas)
            self._scale_to_full_deployment()
            stages["full_scale"] = time.time() - stage_start
            self._publish_metrics("full_scale", True, stages["full_scale"])
            
            # Stage 7: Update DNS
            stage_start = time.time()
            self._update_dns_with_validation()
            stages["dns_update"] = time.time() - stage_start
            self._publish_metrics("dns_update", True, stages["dns_update"])
            
            total_duration = time.time() - start_time
            
            result = {
                "success": True,
                "total_duration_seconds": total_duration,
                "stages": stages,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Canary failover completed successfully"
            }
            
            logger.info(f"Canary failover completed in {total_duration:.2f} seconds")
            self._publish_metrics("total_failover", True, total_duration)
            
            return result
            
        except Exception as e:
            error_duration = time.time() - start_time
            logger.error(f"Canary failover failed after {error_duration:.2f}s: {e}")
            
            # Attempt rollback
            try:
                self._rollback_deployment()
            except Exception as rollback_error:
                logger.error(f"Rollback failed: {rollback_error}")
            
            self._publish_metrics("total_failover", False, error_duration)
            
            return {
                "success": False,
                "total_duration_seconds": error_duration,
                "stages": stages,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

def handle_failover_request(request):
    """Cloud Function entry point for canary failover"""
    try:
        failover = SecurityHardenedFailover()
        result = failover.execute_canary_failover()
        
        return json.dumps(result), 200 if result["success"] else 500
        
    except Exception as e:
        logger.error(f"Failover handler error: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500

# For Pub/Sub trigger
def handle_pubsub_failover(event, context):
    """Handle Pub/Sub triggered failover"""
    try:
        # Decode Pub/Sub message
        import base64
        
        if 'data' in event:
            message_data = base64.b64decode(event['data']).decode('utf-8')
            trigger_info = json.loads(message_data)
            logger.info(f"Failover triggered by: {trigger_info}")
        
        return handle_failover_request(None)
        
    except Exception as e:
        logger.error(f"Pub/Sub failover handler error: {e}")
        return str(e), 500
