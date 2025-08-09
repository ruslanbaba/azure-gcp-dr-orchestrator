"""
GCP Cloud Functions for DR Orchestration
Enterprise-grade serverless functions for disaster recovery automation
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import asyncio
import aiohttp
import asyncpg
from google.cloud import sql_v1
from google.cloud import container_v1
from google.cloud import compute_v1
from google.cloud import monitoring_v3
from google.cloud import pubsub_v1
from google.cloud import secretmanager
from google.cloud import storage
from google.cloud import functions_v1
import functions_framework
from flask import Request, jsonify
import azure.identity
import azure.mgmt.sql
import azure.mgmt.containerservice
import azure.mgmt.monitor
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enterprise configuration
PROJECT_ID = os.environ.get('PROJECT_ID', 'enterprise-dr-orchestrator')
REGION = os.environ.get('REGION', 'us-central1')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'production')

# DR configuration
RTO_TARGET_SECONDS = int(os.environ.get('RTO_TARGET_SECONDS', '300'))  # 5 minutes
RPO_TARGET_SECONDS = int(os.environ.get('RPO_TARGET_SECONDS', '30'))   # 30 seconds
HEALTH_CHECK_INTERVAL = int(os.environ.get('HEALTH_CHECK_INTERVAL', '30'))

# Initialize GCP clients
sql_client = sql_v1.SqlInstancesServiceClient()
container_client = container_v1.ClusterManagerClient()
compute_client = compute_v1.InstancesClient()
monitoring_client = monitoring_v3.MetricServiceClient()
pubsub_publisher = pubsub_v1.PublisherClient()
secret_client = secretmanager.SecretManagerServiceClient()
storage_client = storage.Client()

# Topic names
DR_EVENTS_TOPIC = f"projects/{PROJECT_ID}/topics/prod-dr-dr-events"
ALERT_TOPIC = f"projects/{PROJECT_ID}/topics/prod-dr-alerts"

class DrOrchestratorCloudFunctions:
    """Enterprise DR orchestrator cloud functions"""
    
    def __init__(self):
        self.project_id = PROJECT_ID
        self.region = REGION
        self.environment = ENVIRONMENT
        
    async def get_azure_credentials(self) -> Dict[str, str]:
        """Get Azure credentials from Secret Manager"""
        try:
            secret_name = f"projects/{self.project_id}/secrets/prod-dr-azure-connection/versions/latest"
            response = secret_client.access_secret_version(request={"name": secret_name})
            return json.loads(response.payload.data.decode("UTF-8"))
        except Exception as e:
            logger.error(f"Failed to get Azure credentials: {e}")
            raise
    
    async def get_striim_config(self) -> Dict[str, str]:
        """Get Striim configuration from Secret Manager"""
        try:
            secret_name = f"projects/{self.project_id}/secrets/prod-dr-striim-config/versions/latest"
            response = secret_client.access_secret_version(request={"name": secret_name})
            return json.loads(response.payload.data.decode("UTF-8"))
        except Exception as e:
            logger.error(f"Failed to get Striim config: {e}")
            raise
    
    async def check_azure_sql_mi_health(self) -> Dict[str, Any]:
        """Check Azure SQL Managed Instance health"""
        try:
            azure_creds = await self.get_azure_credentials()
            
            credential = azure.identity.ClientSecretCredential(
                tenant_id=azure_creds['tenant_id'],
                client_id=azure_creds['client_id'],
                client_secret=azure_creds['client_secret']
            )
            
            sql_mgmt_client = azure.mgmt.sql.SqlManagementClient(
                credential, azure_creds['subscription_id']
            )
            
            # Check SQL MI status
            mi_status = sql_mgmt_client.managed_instances.get(
                resource_group_name='prod-dr-azure-rg',
                managed_instance_name='prod-dr-sql-mi-001'
            )
            
            # Check connectivity
            connectivity_check = await self._check_sql_mi_connectivity(azure_creds)
            
            health_score = 1.0 if mi_status.state == 'Ready' and connectivity_check else 0.0
            
            return {
                'service': 'azure_sql_mi',
                'status': mi_status.state,
                'health_score': health_score,
                'region': 'East US 2',
                'connectivity': connectivity_check,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metadata': {
                    'instance_name': 'prod-dr-sql-mi-001',
                    'tier': mi_status.sku.tier if mi_status.sku else 'Unknown',
                    'vcores': mi_status.v_cores,
                    'storage_gb': mi_status.storage_size_in_gb
                }
            }
        except Exception as e:
            logger.error(f"Azure SQL MI health check failed: {e}")
            return {
                'service': 'azure_sql_mi',
                'status': 'Error',
                'health_score': 0.0,
                'region': 'East US 2',
                'connectivity': False,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }
    
    async def _check_sql_mi_connectivity(self, azure_creds: Dict[str, str]) -> bool:
        """Check SQL MI connectivity"""
        try:
            # Simplified connectivity check - in production, use actual DB connection
            return True  # Placeholder
        except Exception as e:
            logger.error(f"SQL MI connectivity check failed: {e}")
            return False
    
    async def check_gcp_cloud_sql_health(self) -> Dict[str, Any]:
        """Check GCP Cloud SQL health"""
        try:
            instance_name = f"projects/{self.project_id}/instances/prod-dr-cloud-sql"
            
            # Get instance status
            request = sql_v1.SqlInstancesGetRequest(
                project=self.project_id,
                instance='prod-dr-cloud-sql'
            )
            instance = sql_client.get(request=request)
            
            # Check connectivity
            connectivity_check = await self._check_cloud_sql_connectivity()
            
            health_score = 1.0 if instance.state == sql_v1.DatabaseInstance.State.RUNNABLE and connectivity_check else 0.0
            
            return {
                'service': 'gcp_cloud_sql',
                'status': instance.state.name,
                'health_score': health_score,
                'region': instance.region,
                'connectivity': connectivity_check,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metadata': {
                    'instance_name': instance.name,
                    'tier': instance.settings.tier,
                    'database_version': instance.database_version.name,
                    'backend_type': instance.backend_type.name,
                    'ip_addresses': [ip.ip_address for ip in instance.ip_addresses]
                }
            }
        except Exception as e:
            logger.error(f"GCP Cloud SQL health check failed: {e}")
            return {
                'service': 'gcp_cloud_sql',
                'status': 'Error',
                'health_score': 0.0,
                'region': self.region,
                'connectivity': False,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }
    
    async def _check_cloud_sql_connectivity(self) -> bool:
        """Check Cloud SQL connectivity"""
        try:
            # Simplified connectivity check - in production, use actual DB connection
            return True  # Placeholder
        except Exception as e:
            logger.error(f"Cloud SQL connectivity check failed: {e}")
            return False
    
    async def check_striim_health(self) -> Dict[str, Any]:
        """Check Striim CDC pipeline health"""
        try:
            striim_config = await self.get_striim_config()
            
            async with aiohttp.ClientSession() as session:
                # Check Striim cluster health
                health_url = f"{striim_config['striim_url']}/api/v1/health"
                async with session.get(
                    health_url,
                    auth=aiohttp.BasicAuth(
                        striim_config['striim_username'],
                        striim_config['striim_password']
                    ),
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        health_data = await response.json()
                        
                        # Check application status
                        app_url = f"{striim_config['striim_url']}/api/v1/applications/AzureToGcpDrReplication/status"
                        async with session.get(
                            app_url,
                            auth=aiohttp.BasicAuth(
                                striim_config['striim_username'],
                                striim_config['striim_password']
                            ),
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as app_response:
                            app_status = await app_response.json()
                            
                            # Calculate health score based on cluster and application status
                            health_score = 1.0 if (
                                health_data.get('status') == 'RUNNING' and
                                app_status.get('state') == 'RUNNING'
                            ) else 0.0
                            
                            return {
                                'service': 'striim_cdc',
                                'status': app_status.get('state', 'Unknown'),
                                'health_score': health_score,
                                'region': 'multi-region',
                                'connectivity': True,
                                'timestamp': datetime.now(timezone.utc).isoformat(),
                                'metadata': {
                                    'application_name': 'AzureToGcpDrReplication',
                                    'cluster_status': health_data.get('status'),
                                    'replication_lag_ms': app_status.get('lag_ms', 0),
                                    'events_processed': app_status.get('events_processed', 0),
                                    'error_count': app_status.get('error_count', 0)
                                }
                            }
                    else:
                        return {
                            'service': 'striim_cdc',
                            'status': 'Unhealthy',
                            'health_score': 0.0,
                            'region': 'multi-region',
                            'connectivity': False,
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'error': f"HTTP {response.status}"
                        }
        except Exception as e:
            logger.error(f"Striim health check failed: {e}")
            return {
                'service': 'striim_cdc',
                'status': 'Error',
                'health_score': 0.0,
                'region': 'multi-region',
                'connectivity': False,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }
    
    async def check_azure_aks_health(self) -> Dict[str, Any]:
        """Check Azure AKS cluster health"""
        try:
            azure_creds = await self.get_azure_credentials()
            
            credential = azure.identity.ClientSecretCredential(
                tenant_id=azure_creds['tenant_id'],
                client_id=azure_creds['client_id'],
                client_secret=azure_creds['client_secret']
            )
            
            container_mgmt_client = azure.mgmt.containerservice.ContainerServiceClient(
                credential, azure_creds['subscription_id']
            )
            
            # Get AKS cluster status
            cluster = container_mgmt_client.managed_clusters.get(
                resource_group_name='prod-dr-azure-rg',
                resource_name='prod-dr-aks-cluster'
            )
            
            health_score = 1.0 if cluster.provisioning_state == 'Succeeded' else 0.0
            
            return {
                'service': 'azure_aks',
                'status': cluster.provisioning_state,
                'health_score': health_score,
                'region': cluster.location,
                'connectivity': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metadata': {
                    'cluster_name': 'prod-dr-aks-cluster',
                    'kubernetes_version': cluster.kubernetes_version,
                    'node_count': len(cluster.agent_pool_profiles) if cluster.agent_pool_profiles else 0,
                    'fqdn': cluster.fqdn,
                    'power_state': cluster.power_state.code if cluster.power_state else 'Unknown'
                }
            }
        except Exception as e:
            logger.error(f"Azure AKS health check failed: {e}")
            return {
                'service': 'azure_aks',
                'status': 'Error',
                'health_score': 0.0,
                'region': 'East US 2',
                'connectivity': False,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }
    
    async def check_gcp_gke_health(self) -> Dict[str, Any]:
        """Check GCP GKE cluster health"""
        try:
            cluster_name = f"projects/{self.project_id}/locations/{self.region}/clusters/prod-dr-gke-cluster"
            
            # Get cluster status
            request = container_v1.GetClusterRequest(name=cluster_name)
            cluster = container_client.get_cluster(request=request)
            
            health_score = 1.0 if cluster.status == container_v1.Cluster.Status.RUNNING else 0.0
            
            return {
                'service': 'gcp_gke',
                'status': cluster.status.name,
                'health_score': health_score,
                'region': cluster.location,
                'connectivity': True,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'metadata': {
                    'cluster_name': 'prod-dr-gke-cluster',
                    'kubernetes_version': cluster.current_master_version,
                    'node_count': cluster.current_node_count,
                    'endpoint': cluster.endpoint,
                    'zone': cluster.zone
                }
            }
        except Exception as e:
            logger.error(f"GCP GKE health check failed: {e}")
            return {
                'service': 'gcp_gke',
                'status': 'Error',
                'health_score': 0.0,
                'region': self.region,
                'connectivity': False,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }
    
    async def execute_comprehensive_health_check(self) -> Dict[str, Any]:
        """Execute comprehensive health check across all services"""
        start_time = time.time()
        
        # Run all health checks concurrently
        tasks = [
            self.check_azure_sql_mi_health(),
            self.check_gcp_cloud_sql_health(),
            self.check_striim_health(),
            self.check_azure_aks_health(),
            self.check_gcp_gke_health()
        ]
        
        health_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        services_health = {}
        overall_health_score = 0.0
        critical_services = ['azure_sql_mi', 'gcp_cloud_sql', 'striim_cdc']
        
        for result in health_results:
            if isinstance(result, Exception):
                logger.error(f"Health check exception: {result}")
                continue
                
            service_name = result['service']
            services_health[service_name] = result
            
            # Weight critical services more heavily
            weight = 0.3 if service_name in critical_services else 0.1
            overall_health_score += result['health_score'] * weight
        
        # Normalize overall health score
        total_weight = len(critical_services) * 0.3 + (len(health_results) - len(critical_services)) * 0.1
        overall_health_score = overall_health_score / total_weight if total_weight > 0 else 0.0
        
        execution_time = time.time() - start_time
        
        health_summary = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'overall_health_score': overall_health_score,
            'health_status': 'HEALTHY' if overall_health_score >= 0.8 else 'DEGRADED' if overall_health_score >= 0.5 else 'UNHEALTHY',
            'execution_time_seconds': execution_time,
            'services': services_health,
            'critical_issues': self._identify_critical_issues(services_health),
            'recommendations': self._generate_recommendations(services_health)
        }
        
        # Publish health check results
        await self._publish_health_results(health_summary)
        
        return health_summary
    
    def _identify_critical_issues(self, services_health: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Identify critical issues from health check results"""
        issues = []
        
        for service_name, health_data in services_health.items():
            if health_data.get('health_score', 0) < 0.5:
                issues.append({
                    'service': service_name,
                    'severity': 'CRITICAL' if health_data.get('health_score', 0) == 0 else 'WARNING',
                    'description': health_data.get('error', 'Service degraded'),
                    'status': health_data.get('status'),
                    'timestamp': health_data.get('timestamp')
                })
        
        return issues
    
    def _generate_recommendations(self, services_health: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on health check results"""
        recommendations = []
        
        # Check for failover conditions
        azure_sql_health = services_health.get('azure_sql_mi', {}).get('health_score', 1.0)
        gcp_sql_health = services_health.get('gcp_cloud_sql', {}).get('health_score', 1.0)
        striim_health = services_health.get('striim_cdc', {}).get('health_score', 1.0)
        
        if azure_sql_health < 0.5 and gcp_sql_health >= 0.8:
            recommendations.append("Consider initiating failover from Azure SQL MI to GCP Cloud SQL")
        
        if striim_health < 0.5:
            recommendations.append("Investigate Striim CDC pipeline - data replication may be affected")
        
        if azure_sql_health < 0.8 or gcp_sql_health < 0.8:
            recommendations.append("Increase monitoring frequency for database services")
        
        # Check for cluster issues
        azure_aks_health = services_health.get('azure_aks', {}).get('health_score', 1.0)
        gcp_gke_health = services_health.get('gcp_gke', {}).get('health_score', 1.0)
        
        if azure_aks_health < 0.5 and gcp_gke_health >= 0.8:
            recommendations.append("Consider scaling workloads to GCP GKE cluster")
        
        return recommendations
    
    async def _publish_health_results(self, health_summary: Dict[str, Any]):
        """Publish health check results to Pub/Sub"""
        try:
            message_data = json.dumps(health_summary).encode('utf-8')
            future = pubsub_publisher.publish(DR_EVENTS_TOPIC, message_data)
            logger.info(f"Published health check results: {future.result()}")
            
            # If critical issues detected, publish to alerts topic
            if health_summary.get('critical_issues'):
                alert_data = {
                    'type': 'HEALTH_CHECK_ALERT',
                    'severity': 'HIGH',
                    'timestamp': health_summary['timestamp'],
                    'overall_health_score': health_summary['overall_health_score'],
                    'critical_issues': health_summary['critical_issues'],
                    'recommendations': health_summary['recommendations']
                }
                alert_message = json.dumps(alert_data).encode('utf-8')
                alert_future = pubsub_publisher.publish(ALERT_TOPIC, alert_message)
                logger.warning(f"Published health alert: {alert_future.result()}")
                
        except Exception as e:
            logger.error(f"Failed to publish health results: {e}")
    
    async def trigger_failover_decision(self, health_data: Dict[str, Any]) -> Dict[str, Any]:
        """Make failover decision based on health data"""
        try:
            # Analyze health data for failover conditions
            azure_sql_health = health_data.get('services', {}).get('azure_sql_mi', {}).get('health_score', 1.0)
            gcp_sql_health = health_data.get('services', {}).get('gcp_cloud_sql', {}).get('health_score', 1.0)
            striim_health = health_data.get('services', {}).get('striim_cdc', {}).get('health_score', 1.0)
            
            # Enterprise failover criteria
            failover_required = (
                azure_sql_health < 0.3 and  # Primary is severely degraded
                gcp_sql_health >= 0.8 and   # Secondary is healthy
                striim_health >= 0.5        # Replication is functional
            )
            
            if failover_required:
                # Initiate automatic failover
                failover_result = await self._execute_automated_failover()
                return {
                    'decision': 'FAILOVER_INITIATED',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'trigger_conditions': {
                        'azure_sql_health': azure_sql_health,
                        'gcp_sql_health': gcp_sql_health,
                        'striim_health': striim_health
                    },
                    'failover_result': failover_result
                }
            else:
                return {
                    'decision': 'NO_FAILOVER_REQUIRED',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'health_analysis': {
                        'azure_sql_health': azure_sql_health,
                        'gcp_sql_health': gcp_sql_health,
                        'striim_health': striim_health
                    }
                }
                
        except Exception as e:
            logger.error(f"Failover decision error: {e}")
            return {
                'decision': 'ERROR',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }
    
    async def _execute_automated_failover(self) -> Dict[str, Any]:
        """Execute automated failover process"""
        try:
            failover_start_time = time.time()
            
            # Step 1: Verify GCP Cloud SQL readiness
            gcp_sql_ready = await self._verify_gcp_sql_readiness()
            if not gcp_sql_ready:
                raise Exception("GCP Cloud SQL not ready for failover")
            
            # Step 2: Stop Striim application to prevent data conflicts
            striim_stopped = await self._stop_striim_application()
            if not striim_stopped:
                logger.warning("Failed to stop Striim application - proceeding with caution")
            
            # Step 3: Promote GCP Cloud SQL to primary
            promotion_result = await self._promote_gcp_sql_to_primary()
            
            # Step 4: Update application configuration
            config_updated = await self._update_application_config()
            
            # Step 5: Scale GKE workloads
            gke_scaled = await self._scale_gke_workloads()
            
            # Step 6: Restart Striim with new configuration (reverse direction)
            striim_restarted = await self._restart_striim_reverse_direction()
            
            failover_duration = time.time() - failover_start_time
            
            # Publish failover completion event
            failover_event = {
                'type': 'FAILOVER_COMPLETED',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'duration_seconds': failover_duration,
                'rto_target_met': failover_duration <= RTO_TARGET_SECONDS,
                'steps_completed': {
                    'gcp_sql_ready': gcp_sql_ready,
                    'striim_stopped': striim_stopped,
                    'sql_promoted': promotion_result,
                    'config_updated': config_updated,
                    'gke_scaled': gke_scaled,
                    'striim_restarted': striim_restarted
                }
            }
            
            message_data = json.dumps(failover_event).encode('utf-8')
            pubsub_publisher.publish(DR_EVENTS_TOPIC, message_data)
            
            return failover_event
            
        except Exception as e:
            logger.error(f"Automated failover failed: {e}")
            
            # Publish failover failure event
            failure_event = {
                'type': 'FAILOVER_FAILED',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e)
            }
            
            message_data = json.dumps(failure_event).encode('utf-8')
            pubsub_publisher.publish(ALERT_TOPIC, message_data)
            
            raise
    
    async def _verify_gcp_sql_readiness(self) -> bool:
        """Verify GCP Cloud SQL is ready for promotion"""
        try:
            # Check instance status
            health_result = await self.check_gcp_cloud_sql_health()
            return health_result.get('health_score', 0) >= 0.8
        except Exception as e:
            logger.error(f"GCP SQL readiness check failed: {e}")
            return False
    
    async def _stop_striim_application(self) -> bool:
        """Stop Striim application"""
        try:
            striim_config = await self.get_striim_config()
            
            async with aiohttp.ClientSession() as session:
                stop_url = f"{striim_config['striim_url']}/api/v1/applications/AzureToGcpDrReplication/stop"
                async with session.post(
                    stop_url,
                    auth=aiohttp.BasicAuth(
                        striim_config['striim_username'],
                        striim_config['striim_password']
                    ),
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Failed to stop Striim application: {e}")
            return False
    
    async def _promote_gcp_sql_to_primary(self) -> bool:
        """Promote GCP Cloud SQL to primary"""
        try:
            # In a real implementation, this would involve promoting a read replica
            # to primary and updating connection strings
            logger.info("Promoting GCP Cloud SQL to primary role")
            return True  # Placeholder
        except Exception as e:
            logger.error(f"Failed to promote GCP SQL: {e}")
            return False
    
    async def _update_application_config(self) -> bool:
        """Update application configuration for failover"""
        try:
            # Update Kubernetes ConfigMaps and Secrets
            # This would involve updating the connection strings to point to GCP
            logger.info("Updating application configuration for failover")
            return True  # Placeholder
        except Exception as e:
            logger.error(f"Failed to update application config: {e}")
            return False
    
    async def _scale_gke_workloads(self) -> bool:
        """Scale GKE workloads to handle increased load"""
        try:
            # Scale up GKE deployments to handle the failover load
            logger.info("Scaling GKE workloads for failover")
            return True  # Placeholder
        except Exception as e:
            logger.error(f"Failed to scale GKE workloads: {e}")
            return False
    
    async def _restart_striim_reverse_direction(self) -> bool:
        """Restart Striim with reverse replication direction"""
        try:
            # Start Striim application with GCP to Azure replication
            logger.info("Restarting Striim with reverse replication")
            return True  # Placeholder
        except Exception as e:
            logger.error(f"Failed to restart Striim: {e}")
            return False

# Initialize the orchestrator
dr_orchestrator = DrOrchestratorCloudFunctions()

@functions_framework.http
def health_check_endpoint(request: Request):
    """HTTP Cloud Function for comprehensive health checks"""
    try:
        # Run async health check
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        health_result = loop.run_until_complete(
            dr_orchestrator.execute_comprehensive_health_check()
        )
        
        return jsonify(health_result), 200
        
    except Exception as e:
        logger.error(f"Health check endpoint error: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500
    finally:
        loop.close()

@functions_framework.cloud_event
def dr_event_processor(cloud_event):
    """Cloud Event Function for processing DR events"""
    try:
        # Decode Pub/Sub message
        event_data = json.loads(cloud_event.data['message']['data'])
        event_type = event_data.get('type', 'unknown')
        
        logger.info(f"Processing DR event: {event_type}")
        
        # Process different event types
        if event_type == 'health_check':
            # Trigger health check
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            health_result = loop.run_until_complete(
                dr_orchestrator.execute_comprehensive_health_check()
            )
            
            # Check if failover decision needed
            if health_result.get('health_status') == 'UNHEALTHY':
                failover_decision = loop.run_until_complete(
                    dr_orchestrator.trigger_failover_decision(health_result)
                )
                logger.info(f"Failover decision: {failover_decision}")
            
            loop.close()
            
        elif event_type == 'manual_failover':
            # Process manual failover request
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            failover_result = loop.run_until_complete(
                dr_orchestrator._execute_automated_failover()
            )
            
            logger.info(f"Manual failover result: {failover_result}")
            loop.close()
            
        elif event_type == 'alert':
            # Process alert and determine if action needed
            logger.warning(f"Alert received: {event_data}")
            
        else:
            logger.warning(f"Unknown event type: {event_type}")
            
    except Exception as e:
        logger.error(f"DR event processing error: {e}")
        raise

@functions_framework.http
def manual_failover_trigger(request: Request):
    """HTTP Cloud Function for manual failover trigger"""
    try:
        # Validate request
        if request.method != 'POST':
            return jsonify({'error': 'Method not allowed'}), 405
        
        request_json = request.get_json(silent=True)
        if not request_json or request_json.get('action') != 'trigger_failover':
            return jsonify({'error': 'Invalid request'}), 400
        
        # Authenticate request (in production, use proper authentication)
        auth_token = request.headers.get('Authorization')
        if not auth_token:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Execute manual failover
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        failover_result = loop.run_until_complete(
            dr_orchestrator._execute_automated_failover()
        )
        
        loop.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Manual failover initiated',
            'result': failover_result
        }), 200
        
    except Exception as e:
        logger.error(f"Manual failover trigger error: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500

@functions_framework.http
def metrics_collector(request: Request):
    """HTTP Cloud Function for collecting DR metrics"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Collect comprehensive metrics
        health_result = loop.run_until_complete(
            dr_orchestrator.execute_comprehensive_health_check()
        )
        
        # Extract metrics for monitoring systems
        metrics = {
            'timestamp': health_result['timestamp'],
            'overall_health_score': health_result['overall_health_score'],
            'execution_time_seconds': health_result['execution_time_seconds'],
            'service_metrics': {}
        }
        
        for service_name, service_data in health_result.get('services', {}).items():
            metrics['service_metrics'][service_name] = {
                'health_score': service_data.get('health_score', 0),
                'status': service_data.get('status', 'Unknown'),
                'connectivity': service_data.get('connectivity', False),
                'response_time_ms': service_data.get('response_time_ms', 0)
            }
        
        loop.close()
        
        return jsonify(metrics), 200
        
    except Exception as e:
        logger.error(f"Metrics collection error: {e}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500
