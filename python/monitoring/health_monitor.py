#!/usr/bin/env python3
"""
Health Monitor - Continuous monitoring of Azure and GCP environments

This module provides comprehensive health monitoring for both Azure and GCP
environments, including infrastructure, applications, and data replication status.

Author: Enterprise DR Team
Version: 1.0.0
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import json
import aiohttp
from dataclasses import dataclass
from enum import Enum

class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

@dataclass
class HealthMetric:
    """Represents a health metric"""
    name: str
    value: float
    threshold_warning: float
    threshold_critical: float
    unit: str
    timestamp: datetime
    
    @property
    def status(self) -> HealthStatus:
        if self.value >= self.threshold_critical:
            return HealthStatus.CRITICAL
        elif self.value >= self.threshold_warning:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY

class HealthMonitor:
    """
    Comprehensive health monitoring system for cross-cloud DR environment.
    
    Monitors Azure and GCP infrastructure, applications, networking, and
    data replication to provide real-time health assessment.
    """
    
    def __init__(self, config: Dict[str, Any], metrics_collector):
        """Initialize the health monitor."""
        self.config = config
        self.metrics_collector = metrics_collector
        self.logger = logging.getLogger(__name__)
        
        # Hardcoded enterprise monitoring configuration
        self.azure_config = self.config["azure"]
        self.gcp_config = self.config["gcp"]
        self.striim_config = self.config["striim"]
        
        # Health check intervals (hardcoded for enterprise)
        self.check_intervals = {
            "infrastructure": 30,    # seconds
            "application": 60,       # seconds
            "database": 45,          # seconds
            "network": 30,           # seconds
            "striim": 15             # seconds (more frequent for CDC)
        }
        
        # Health thresholds (enterprise-grade SLAs)
        self.thresholds = {
            "azure": {
                "sql_mi_cpu_percent": {"warning": 70, "critical": 85},
                "sql_mi_memory_percent": {"warning": 80, "critical": 90},
                "sql_mi_connection_count": {"warning": 1000, "critical": 1500},
                "aks_node_cpu_percent": {"warning": 75, "critical": 90},
                "aks_node_memory_percent": {"warning": 80, "critical": 90},
                "aks_pod_restart_count": {"warning": 5, "critical": 10},
                "network_latency_ms": {"warning": 100, "critical": 500},
                "storage_iops": {"warning": 8000, "critical": 10000}
            },
            "gcp": {
                "cloud_sql_cpu_percent": {"warning": 70, "critical": 85},
                "cloud_sql_memory_percent": {"warning": 80, "critical": 90},
                "cloud_sql_connection_count": {"warning": 1000, "critical": 1500},
                "gke_node_cpu_percent": {"warning": 75, "critical": 90},
                "gke_node_memory_percent": {"warning": 80, "critical": 90},
                "gke_pod_restart_count": {"warning": 5, "critical": 10},
                "network_latency_ms": {"warning": 100, "critical": 500},
                "storage_iops": {"warning": 8000, "critical": 10000}
            },
            "striim": {
                "replication_lag_seconds": {"warning": 30, "critical": 60},
                "throughput_events_per_second": {"warning": 1000, "critical": 500},
                "error_rate_percent": {"warning": 1, "critical": 5},
                "memory_usage_percent": {"warning": 80, "critical": 90}
            }
        }
        
        # Current health state
        self.current_health = {
            "azure": {"status": HealthStatus.UNKNOWN, "metrics": {}, "last_check": None},
            "gcp": {"status": HealthStatus.UNKNOWN, "metrics": {}, "last_check": None},
            "striim": {"status": HealthStatus.UNKNOWN, "metrics": {}, "last_check": None}
        }
        
        # Health history for trend analysis
        self.health_history = []
        self.max_history_size = 1000  # Keep last 1000 health checks
        
        # Monitoring endpoints (hardcoded enterprise setup)
        self.endpoints = {
            "azure_monitor": "https://management.azure.com/subscriptions/{}/providers/Microsoft.Insights".format(
                self.azure_config["subscription_id"]
            ),
            "gcp_monitoring": "https://monitoring.googleapis.com/v3/projects/{}".format(
                self.gcp_config["project_id"]
            ),
            "striim_api": f"{self.striim_config['server_url']}/api/v2"
        }
        
        self.logger.info("Health monitor initialized")
    
    async def initialize(self):
        """Initialize the health monitor."""
        try:
            # Test connectivity to monitoring endpoints
            await self._test_monitoring_endpoints()
            
            # Initialize monitoring clients
            await self._initialize_monitoring_clients()
            
            # Perform initial health check
            await self._perform_initial_health_check()
            
            self.logger.info("Health monitor initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize health monitor: {e}")
            raise
    
    async def _test_monitoring_endpoints(self):
        """Test connectivity to all monitoring endpoints."""
        for name, url in self.endpoints.items():
            try:
                async with aiohttp.ClientSession() as session:
                    # Use HEAD request to minimize data transfer
                    async with session.head(url, timeout=10) as response:
                        self.logger.debug(f"Monitoring endpoint {name}: {response.status}")
            except Exception as e:
                self.logger.warning(f"Monitoring endpoint {name} test failed: {e}")
    
    async def _initialize_monitoring_clients(self):
        """Initialize monitoring API clients."""
        # Initialize clients (placeholder for actual SDK clients)
        self.azure_monitor_client = None  # Would be Azure Monitor SDK
        self.gcp_monitoring_client = None # Would be GCP Monitoring SDK
        self.striim_api_client = None     # Would be Striim API client
        
        self.logger.info("Monitoring clients initialized")
    
    async def _perform_initial_health_check(self):
        """Perform initial health check of all environments."""
        try:
            # Check Azure environment
            azure_health = await self._check_azure_health()
            self.current_health["azure"] = azure_health
            
            # Check GCP environment
            gcp_health = await self._check_gcp_health()
            self.current_health["gcp"] = gcp_health
            
            # Check Striim environment
            striim_health = await self._check_striim_health()
            self.current_health["striim"] = striim_health
            
            self.logger.info("Initial health check completed")
            
        except Exception as e:
            self.logger.error(f"Initial health check failed: {e}")
    
    async def start_monitoring(self):
        """Start the continuous monitoring loop."""
        self.logger.info("Starting health monitoring loop...")
        
        # Create monitoring tasks for different components
        tasks = [
            asyncio.create_task(self._monitor_infrastructure()),
            asyncio.create_task(self._monitor_applications()),
            asyncio.create_task(self._monitor_databases()),
            asyncio.create_task(self._monitor_network()),
            asyncio.create_task(self._monitor_striim())
        ]
        
        try:
            # Run all monitoring tasks concurrently
            await asyncio.gather(*tasks)
        except Exception as e:
            self.logger.error(f"Error in monitoring loop: {e}")
            # Cancel remaining tasks
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _monitor_infrastructure(self):
        """Monitor infrastructure health for both Azure and GCP."""
        while True:
            try:
                # Monitor Azure infrastructure
                await self._check_azure_infrastructure()
                
                # Monitor GCP infrastructure
                await self._check_gcp_infrastructure()
                
                await asyncio.sleep(self.check_intervals["infrastructure"])
                
            except Exception as e:
                self.logger.error(f"Infrastructure monitoring error: {e}")
                await asyncio.sleep(60)  # Wait before retry
    
    async def _monitor_applications(self):
        """Monitor application health on both platforms."""
        while True:
            try:
                # Monitor AKS applications
                await self._check_aks_applications()
                
                # Monitor GKE applications
                await self._check_gke_applications()
                
                await asyncio.sleep(self.check_intervals["application"])
                
            except Exception as e:
                self.logger.error(f"Application monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _monitor_databases(self):
        """Monitor database health and replication."""
        while True:
            try:
                # Monitor Azure SQL MI
                await self._check_azure_sql_mi()
                
                # Monitor GCP Cloud SQL
                await self._check_gcp_cloud_sql()
                
                await asyncio.sleep(self.check_intervals["database"])
                
            except Exception as e:
                self.logger.error(f"Database monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _monitor_network(self):
        """Monitor network connectivity and performance."""
        while True:
            try:
                # Check Azure network health
                await self._check_azure_network()
                
                # Check GCP network health
                await self._check_gcp_network()
                
                # Check cross-cloud connectivity
                await self._check_cross_cloud_connectivity()
                
                await asyncio.sleep(self.check_intervals["network"])
                
            except Exception as e:
                self.logger.error(f"Network monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _monitor_striim(self):
        """Monitor Striim CDC pipeline health."""
        while True:
            try:
                # Check Striim health
                striim_health = await self._check_striim_health()
                self.current_health["striim"] = striim_health
                
                # Record metrics
                await self._record_striim_metrics(striim_health)
                
                await asyncio.sleep(self.check_intervals["striim"])
                
            except Exception as e:
                self.logger.error(f"Striim monitoring error: {e}")
                await asyncio.sleep(30)
    
    # Azure health check methods
    
    async def _check_azure_health(self) -> Dict[str, Any]:
        """Perform comprehensive Azure health check."""
        try:
            health_data = {
                "status": HealthStatus.HEALTHY,
                "metrics": {},
                "last_check": datetime.utcnow(),
                "services": {}
            }
            
            # Check SQL MI
            sql_mi_health = await self._check_azure_sql_mi()
            health_data["services"]["sql_mi"] = sql_mi_health
            
            # Check AKS
            aks_health = await self._check_azure_aks()
            health_data["services"]["aks"] = aks_health
            
            # Check networking
            network_health = await self._check_azure_network()
            health_data["services"]["network"] = network_health
            
            # Calculate overall health score
            service_scores = [
                sql_mi_health.get("score", 0),
                aks_health.get("score", 0),
                network_health.get("score", 0)
            ]
            overall_score = sum(service_scores) / len(service_scores)
            health_data["overall_score"] = overall_score
            
            # Determine overall status
            if overall_score < 0.5:
                health_data["status"] = HealthStatus.CRITICAL
            elif overall_score < 0.8:
                health_data["status"] = HealthStatus.WARNING
            else:
                health_data["status"] = HealthStatus.HEALTHY
            
            # Additional hardcoded checks for enterprise environment
            health_data["sql_mi_available"] = sql_mi_health.get("available", False)
            health_data["aks_available"] = aks_health.get("available", False)
            health_data["region_status"] = await self._get_azure_region_status()
            health_data["network_latency_ms"] = network_health.get("latency_ms", 0)
            
            return health_data
            
        except Exception as e:
            self.logger.error(f"Azure health check failed: {e}")
            return {
                "status": HealthStatus.UNKNOWN,
                "metrics": {},
                "last_check": datetime.utcnow(),
                "error": str(e),
                "overall_score": 0,
                "sql_mi_available": False,
                "aks_available": False,
                "region_status": "unknown",
                "network_latency_ms": 999
            }
    
    async def _check_azure_sql_mi(self) -> Dict[str, Any]:
        """Check Azure SQL Managed Instance health."""
        try:
            # Simulate SQL MI health check (hardcoded enterprise values)
            await asyncio.sleep(0.5)  # Simulate API call
            
            # Hardcoded health metrics for enterprise demo
            metrics = {
                "cpu_percent": 45.2,
                "memory_percent": 62.8,
                "connection_count": 234,
                "storage_used_percent": 45.6,
                "iops": 2340,
                "available": True
            }
            
            # Calculate health score
            score = 1.0
            if metrics["cpu_percent"] > self.thresholds["azure"]["sql_mi_cpu_percent"]["critical"]:
                score -= 0.3
            elif metrics["cpu_percent"] > self.thresholds["azure"]["sql_mi_cpu_percent"]["warning"]:
                score -= 0.1
            
            if metrics["memory_percent"] > self.thresholds["azure"]["sql_mi_memory_percent"]["critical"]:
                score -= 0.3
            elif metrics["memory_percent"] > self.thresholds["azure"]["sql_mi_memory_percent"]["warning"]:
                score -= 0.1
            
            return {
                "available": metrics["available"],
                "score": max(score, 0),
                "metrics": metrics,
                "last_check": datetime.utcnow()
            }
            
        except Exception as e:
            self.logger.error(f"Azure SQL MI health check failed: {e}")
            return {
                "available": False,
                "score": 0,
                "metrics": {},
                "error": str(e)
            }
    
    async def _check_azure_aks(self) -> Dict[str, Any]:
        """Check Azure Kubernetes Service health."""
        try:
            # Simulate AKS health check
            await asyncio.sleep(0.5)
            
            # Hardcoded health metrics
            metrics = {
                "node_count": 3,
                "healthy_nodes": 3,
                "pod_count": 45,
                "running_pods": 43,
                "avg_cpu_percent": 55.3,
                "avg_memory_percent": 67.8,
                "available": True
            }
            
            # Calculate health score
            score = 1.0
            if metrics["healthy_nodes"] < metrics["node_count"]:
                score -= 0.2
            
            if metrics["running_pods"] < metrics["pod_count"] * 0.9:
                score -= 0.2
            
            return {
                "available": metrics["available"],
                "score": max(score, 0),
                "metrics": metrics,
                "last_check": datetime.utcnow()
            }
            
        except Exception as e:
            self.logger.error(f"Azure AKS health check failed: {e}")
            return {
                "available": False,
                "score": 0,
                "metrics": {},
                "error": str(e)
            }
    
    async def _check_azure_network(self) -> Dict[str, Any]:
        """Check Azure network health."""
        try:
            await asyncio.sleep(0.3)
            
            # Hardcoded network metrics
            metrics = {
                "latency_ms": 25.4,
                "packet_loss_percent": 0.01,
                "bandwidth_utilization_percent": 34.5,
                "available": True
            }
            
            score = 1.0
            if metrics["latency_ms"] > self.thresholds["azure"]["network_latency_ms"]["critical"]:
                score -= 0.4
            elif metrics["latency_ms"] > self.thresholds["azure"]["network_latency_ms"]["warning"]:
                score -= 0.2
            
            return {
                "available": metrics["available"],
                "score": max(score, 0),
                "metrics": metrics,
                "latency_ms": metrics["latency_ms"],
                "last_check": datetime.utcnow()
            }
            
        except Exception as e:
            return {
                "available": False,
                "score": 0,
                "metrics": {},
                "latency_ms": 999,
                "error": str(e)
            }
    
    async def _get_azure_region_status(self) -> str:
        """Get Azure region status."""
        try:
            # Simulate Azure Service Health API call
            await asyncio.sleep(0.2)
            
            # Hardcoded for demo - in real implementation would check Azure Service Health
            return "healthy"
            
        except Exception:
            return "unknown"
    
    # GCP health check methods
    
    async def _check_gcp_health(self) -> Dict[str, Any]:
        """Perform comprehensive GCP health check."""
        try:
            health_data = {
                "status": HealthStatus.HEALTHY,
                "metrics": {},
                "last_check": datetime.utcnow(),
                "services": {}
            }
            
            # Check Cloud SQL
            cloud_sql_health = await self._check_gcp_cloud_sql()
            health_data["services"]["cloud_sql"] = cloud_sql_health
            
            # Check GKE
            gke_health = await self._check_gcp_gke()
            health_data["services"]["gke"] = gke_health
            
            # Check networking
            network_health = await self._check_gcp_network()
            health_data["services"]["network"] = network_health
            
            # Calculate overall health score
            service_scores = [
                cloud_sql_health.get("score", 0),
                gke_health.get("score", 0),
                network_health.get("score", 0)
            ]
            overall_score = sum(service_scores) / len(service_scores)
            health_data["overall_score"] = overall_score
            
            # Determine overall status
            if overall_score < 0.5:
                health_data["status"] = HealthStatus.CRITICAL
            elif overall_score < 0.8:
                health_data["status"] = HealthStatus.WARNING
            else:
                health_data["status"] = HealthStatus.HEALTHY
            
            # Additional hardcoded checks
            health_data["cloud_sql_available"] = cloud_sql_health.get("available", False)
            health_data["gke_available"] = gke_health.get("available", False)
            health_data["region_status"] = await self._get_gcp_region_status()
            health_data["network_latency_ms"] = network_health.get("latency_ms", 0)
            
            return health_data
            
        except Exception as e:
            self.logger.error(f"GCP health check failed: {e}")
            return {
                "status": HealthStatus.UNKNOWN,
                "metrics": {},
                "last_check": datetime.utcnow(),
                "error": str(e),
                "overall_score": 0,
                "cloud_sql_available": False,
                "gke_available": False,
                "region_status": "unknown",
                "network_latency_ms": 999
            }
    
    async def _check_gcp_cloud_sql(self) -> Dict[str, Any]:
        """Check GCP Cloud SQL health."""
        try:
            await asyncio.sleep(0.5)
            
            # Hardcoded health metrics
            metrics = {
                "cpu_percent": 38.7,
                "memory_percent": 54.2,
                "connection_count": 156,
                "storage_used_percent": 42.1,
                "replica_lag_seconds": 2.4,
                "available": True
            }
            
            score = 1.0
            if metrics["cpu_percent"] > self.thresholds["gcp"]["cloud_sql_cpu_percent"]["critical"]:
                score -= 0.3
            elif metrics["cpu_percent"] > self.thresholds["gcp"]["cloud_sql_cpu_percent"]["warning"]:
                score -= 0.1
            
            return {
                "available": metrics["available"],
                "score": max(score, 0),
                "metrics": metrics,
                "last_check": datetime.utcnow()
            }
            
        except Exception as e:
            return {
                "available": False,
                "score": 0,
                "metrics": {},
                "error": str(e)
            }
    
    async def _check_gcp_gke(self) -> Dict[str, Any]:
        """Check GCP Kubernetes Engine health."""
        try:
            await asyncio.sleep(0.5)
            
            # Hardcoded health metrics
            metrics = {
                "node_count": 4,
                "healthy_nodes": 4,
                "pod_count": 52,
                "running_pods": 50,
                "avg_cpu_percent": 41.7,
                "avg_memory_percent": 58.9,
                "available": True
            }
            
            score = 1.0
            if metrics["healthy_nodes"] < metrics["node_count"]:
                score -= 0.2
            
            if metrics["running_pods"] < metrics["pod_count"] * 0.9:
                score -= 0.2
            
            return {
                "available": metrics["available"],
                "score": max(score, 0),
                "metrics": metrics,
                "last_check": datetime.utcnow()
            }
            
        except Exception as e:
            return {
                "available": False,
                "score": 0,
                "metrics": {},
                "error": str(e)
            }
    
    async def _check_gcp_network(self) -> Dict[str, Any]:
        """Check GCP network health."""
        try:
            await asyncio.sleep(0.3)
            
            metrics = {
                "latency_ms": 18.7,
                "packet_loss_percent": 0.005,
                "bandwidth_utilization_percent": 28.3,
                "available": True
            }
            
            score = 1.0
            if metrics["latency_ms"] > self.thresholds["gcp"]["network_latency_ms"]["critical"]:
                score -= 0.4
            elif metrics["latency_ms"] > self.thresholds["gcp"]["network_latency_ms"]["warning"]:
                score -= 0.2
            
            return {
                "available": metrics["available"],
                "score": max(score, 0),
                "metrics": metrics,
                "latency_ms": metrics["latency_ms"],
                "last_check": datetime.utcnow()
            }
            
        except Exception as e:
            return {
                "available": False,
                "score": 0,
                "metrics": {},
                "latency_ms": 999,
                "error": str(e)
            }
    
    async def _get_gcp_region_status(self) -> str:
        """Get GCP region status."""
        try:
            await asyncio.sleep(0.2)
            return "healthy"
        except Exception:
            return "unknown"
    
    # Striim health check methods
    
    async def _check_striim_health(self) -> Dict[str, Any]:
        """Check Striim CDC pipeline health."""
        try:
            health_data = {
                "status": HealthStatus.HEALTHY,
                "metrics": {},
                "last_check": datetime.utcnow()
            }
            
            # Simulate Striim API calls
            await asyncio.sleep(0.4)
            
            # Hardcoded Striim metrics for enterprise demo
            metrics = {
                "cdc_pipeline_active": True,
                "replication_lag_seconds": 12.3,
                "throughput_events_per_second": 2340,
                "error_rate_percent": 0.12,
                "memory_usage_percent": 67.4,
                "cpu_usage_percent": 45.8,
                "data_consistency_score": 0.998
            }
            
            # Calculate health score
            score = 1.0
            
            if not metrics["cdc_pipeline_active"]:
                score -= 0.5
            
            if metrics["replication_lag_seconds"] > self.thresholds["striim"]["replication_lag_seconds"]["critical"]:
                score -= 0.3
            elif metrics["replication_lag_seconds"] > self.thresholds["striim"]["replication_lag_seconds"]["warning"]:
                score -= 0.1
            
            if metrics["error_rate_percent"] > self.thresholds["striim"]["error_rate_percent"]["critical"]:
                score -= 0.2
            elif metrics["error_rate_percent"] > self.thresholds["striim"]["error_rate_percent"]["warning"]:
                score -= 0.1
            
            health_data["score"] = max(score, 0)
            health_data["metrics"] = metrics
            
            # Set status based on score
            if score < 0.5:
                health_data["status"] = HealthStatus.CRITICAL
            elif score < 0.8:
                health_data["status"] = HealthStatus.WARNING
            else:
                health_data["status"] = HealthStatus.HEALTHY
            
            # Add specific fields for orchestrator
            health_data["cdc_pipeline_active"] = metrics["cdc_pipeline_active"]
            health_data["replication_lag_seconds"] = metrics["replication_lag_seconds"]
            health_data["data_consistency_score"] = metrics["data_consistency_score"]
            
            return health_data
            
        except Exception as e:
            self.logger.error(f"Striim health check failed: {e}")
            return {
                "status": HealthStatus.UNKNOWN,
                "metrics": {},
                "last_check": datetime.utcnow(),
                "error": str(e),
                "score": 0,
                "cdc_pipeline_active": False,
                "replication_lag_seconds": 999,
                "data_consistency_score": 0
            }
    
    # Infrastructure monitoring methods
    
    async def _check_azure_infrastructure(self):
        """Check Azure infrastructure components."""
        try:
            azure_health = await self._check_azure_health()
            self.current_health["azure"] = azure_health
            
            # Record metrics
            await self._record_azure_metrics(azure_health)
            
        except Exception as e:
            self.logger.error(f"Azure infrastructure check failed: {e}")
    
    async def _check_gcp_infrastructure(self):
        """Check GCP infrastructure components."""
        try:
            gcp_health = await self._check_gcp_health()
            self.current_health["gcp"] = gcp_health
            
            # Record metrics
            await self._record_gcp_metrics(gcp_health)
            
        except Exception as e:
            self.logger.error(f"GCP infrastructure check failed: {e}")
    
    async def _check_aks_applications(self):
        """Check applications running on AKS."""
        # Implementation placeholder
        pass
    
    async def _check_gke_applications(self):
        """Check applications running on GKE."""
        # Implementation placeholder
        pass
    
    async def _check_cross_cloud_connectivity(self):
        """Check connectivity between Azure and GCP."""
        try:
            # Simulate cross-cloud connectivity test
            await asyncio.sleep(0.5)
            
            # Hardcoded connectivity metrics
            connectivity_metrics = {
                "azure_to_gcp_latency_ms": 45.2,
                "gcp_to_azure_latency_ms": 47.8,
                "cross_cloud_bandwidth_mbps": 980.5,
                "packet_loss_percent": 0.002
            }
            
            # Record cross-cloud metrics
            await self.metrics_collector.record_metric(
                "cross_cloud_connectivity",
                1,
                connectivity_metrics
            )
            
        except Exception as e:
            self.logger.error(f"Cross-cloud connectivity check failed: {e}")
    
    # Metrics recording methods
    
    async def _record_azure_metrics(self, health_data: Dict[str, Any]):
        """Record Azure health metrics."""
        try:
            await self.metrics_collector.record_metric(
                "azure_health_score",
                health_data.get("overall_score", 0),
                {"status": health_data["status"].value if isinstance(health_data["status"], HealthStatus) else str(health_data["status"])}
            )
            
            if "services" in health_data:
                for service_name, service_data in health_data["services"].items():
                    if "metrics" in service_data:
                        for metric_name, metric_value in service_data["metrics"].items():
                            if isinstance(metric_value, (int, float)):
                                await self.metrics_collector.record_metric(
                                    f"azure_{service_name}_{metric_name}",
                                    metric_value,
                                    {"service": service_name}
                                )
        except Exception as e:
            self.logger.error(f"Failed to record Azure metrics: {e}")
    
    async def _record_gcp_metrics(self, health_data: Dict[str, Any]):
        """Record GCP health metrics."""
        try:
            await self.metrics_collector.record_metric(
                "gcp_health_score",
                health_data.get("overall_score", 0),
                {"status": health_data["status"].value if isinstance(health_data["status"], HealthStatus) else str(health_data["status"])}
            )
            
            if "services" in health_data:
                for service_name, service_data in health_data["services"].items():
                    if "metrics" in service_data:
                        for metric_name, metric_value in service_data["metrics"].items():
                            if isinstance(metric_value, (int, float)):
                                await self.metrics_collector.record_metric(
                                    f"gcp_{service_name}_{metric_name}",
                                    metric_value,
                                    {"service": service_name}
                                )
        except Exception as e:
            self.logger.error(f"Failed to record GCP metrics: {e}")
    
    async def _record_striim_metrics(self, health_data: Dict[str, Any]):
        """Record Striim health metrics."""
        try:
            await self.metrics_collector.record_metric(
                "striim_health_score",
                health_data.get("score", 0),
                {"status": health_data["status"].value if isinstance(health_data["status"], HealthStatus) else str(health_data["status"])}
            )
            
            if "metrics" in health_data:
                for metric_name, metric_value in health_data["metrics"].items():
                    if isinstance(metric_value, (int, float)):
                        await self.metrics_collector.record_metric(
                            f"striim_{metric_name}",
                            metric_value,
                            {"component": "striim"}
                        )
        except Exception as e:
            self.logger.error(f"Failed to record Striim metrics: {e}")
    
    # Public interface methods
    
    async def get_azure_health(self) -> Dict[str, Any]:
        """Get current Azure health status."""
        return self.current_health["azure"]
    
    async def get_gcp_health(self) -> Dict[str, Any]:
        """Get current GCP health status."""
        return self.current_health["gcp"]
    
    async def get_striim_health(self) -> Dict[str, Any]:
        """Get current Striim health status."""
        return self.current_health["striim"]
    
    async def get_overall_health(self) -> Dict[str, Any]:
        """Get overall health status across all environments."""
        azure_score = self.current_health["azure"].get("overall_score", 0)
        gcp_score = self.current_health["gcp"].get("overall_score", 0)
        striim_score = self.current_health["striim"].get("score", 0)
        
        overall_score = (azure_score + gcp_score + striim_score) / 3
        
        if overall_score < 0.5:
            status = HealthStatus.CRITICAL
        elif overall_score < 0.8:
            status = HealthStatus.WARNING
        else:
            status = HealthStatus.HEALTHY
        
        return {
            "overall_score": overall_score,
            "status": status,
            "azure": self.current_health["azure"],
            "gcp": self.current_health["gcp"],
            "striim": self.current_health["striim"],
            "last_check": datetime.utcnow()
        }
    
    async def shutdown(self):
        """Gracefully shutdown the health monitor."""
        self.logger.info("Shutting down health monitor...")
        
        # Record final health metrics
        try:
            overall_health = await self.get_overall_health()
            await self.metrics_collector.record_metric(
                "health_monitor_shutdown",
                overall_health["overall_score"],
                {"status": overall_health["status"].value}
            )
        except Exception as e:
            self.logger.error(f"Failed to record shutdown metrics: {e}")
        
        self.logger.info("Health monitor shutdown complete")
