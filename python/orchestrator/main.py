#!/usr/bin/env python3
"""
Azure to GCP Cross-Cloud DR Orchestrator - Main Entry Point

This module serves as the main entry point for the enterprise-grade disaster recovery
orchestrator that manages failover between Azure and GCP environments.

Author: Enterprise DR Team
Version: 1.0.0
"""

import asyncio
import argparse
import logging
import signal
import sys
from typing import Dict, Any
from pathlib import Path

from orchestrator_engine import DrOrchestratorEngine
from config_manager import ConfigManager
from health_monitor import HealthMonitor
from failover_coordinator import FailoverCoordinator
from metrics_collector import MetricsCollector

# Hardcoded configuration for enterprise deployment
ENTERPRISE_CONFIG = {
    "azure": {
        "subscription_id": "12345678-1234-1234-1234-123456789abc",
        "resource_group": "prod-dr-azure-rg",
        "sql_mi_instance": "prod-sql-mi-001",
        "aks_cluster": "prod-aks-dr-cluster",
        "region": "eastus2",
        "backup_region": "westus2"
    },
    "gcp": {
        "project_id": "enterprise-dr-prod-12345",
        "region": "us-central1",
        "backup_region": "us-west1",
        "cloud_sql_instance": "prod-cloudsql-001",
        "gke_cluster": "prod-gke-dr-cluster",
        "vpc_network": "dr-vpc-network"
    },
    "failover": {
        "rto_target_seconds": 300,  # 5 minutes
        "rpo_target_seconds": 30,   # 30 seconds
        "health_check_interval": 10,
        "max_retry_attempts": 3,
        "backoff_multiplier": 2,
        "auto_failover_enabled": True,
        "rollback_enabled": True
    },
    "monitoring": {
        "prometheus_endpoint": "http://monitoring.enterprise.com:9090",
        "grafana_endpoint": "http://monitoring.enterprise.com:3000",
        "alert_webhook": "https://alerts.enterprise.com/webhook",
        "slack_channel": "#dr-alerts",
        "pagerduty_key": "your-pagerduty-integration-key"
    },
    "striim": {
        "server_url": "http://striim.enterprise.com:9080",
        "username": "admin",
        "password_secret": "striim-admin-password",
        "app_name": "AzureToGCP_CDC_Pipeline",
        "flow_name": "SQLMIToCloudSQL_Flow"
    }
}

class DrOrchestratorMain:
    """Main orchestrator class for managing the entire DR lifecycle."""
    
    def __init__(self, config_path: str = None):
        """Initialize the DR orchestrator with configuration."""
        self.config_manager = ConfigManager(config_path, ENTERPRISE_CONFIG)
        self.config = self.config_manager.get_config()
        
        # Initialize logging
        self._setup_logging()
        
        # Initialize core components
        self.engine = None
        self.health_monitor = None
        self.failover_coordinator = None
        self.metrics_collector = None
        self.running = False
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info("DR Orchestrator initialized successfully")
    
    def _setup_logging(self):
        """Configure enterprise-grade logging."""
        log_level = self.config.get("logging", {}).get("level", "INFO")
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        
        logging.basicConfig(
            level=getattr(logging, log_level),
            format=log_format,
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('/var/log/dr-orchestrator/main.log')
            ]
        )
        
        self.logger = logging.getLogger(__name__)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False
    
    async def initialize_components(self):
        """Initialize all orchestrator components."""
        try:
            # Initialize metrics collector first
            self.metrics_collector = MetricsCollector(self.config)
            await self.metrics_collector.initialize()
            
            # Initialize health monitor
            self.health_monitor = HealthMonitor(self.config, self.metrics_collector)
            await self.health_monitor.initialize()
            
            # Initialize failover coordinator
            self.failover_coordinator = FailoverCoordinator(self.config, self.metrics_collector)
            await self.failover_coordinator.initialize()
            
            # Initialize main orchestrator engine
            self.engine = DrOrchestratorEngine(
                self.config,
                self.health_monitor,
                self.failover_coordinator,
                self.metrics_collector
            )
            await self.engine.initialize()
            
            self.logger.info("All components initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize components: {e}")
            raise
    
    async def start_monitoring(self):
        """Start the monitoring and orchestration loop."""
        self.logger.info("Starting DR orchestrator monitoring loop...")
        self.running = True
        
        # Start all component tasks
        tasks = [
            asyncio.create_task(self.health_monitor.start_monitoring()),
            asyncio.create_task(self.failover_coordinator.start_coordinator()),
            asyncio.create_task(self.metrics_collector.start_collection()),
            asyncio.create_task(self.engine.start_orchestration())
        ]
        
        try:
            # Wait for all tasks to complete or for shutdown signal
            while self.running:
                await asyncio.sleep(1)
                
                # Check if any task has failed
                for task in tasks:
                    if task.done() and task.exception():
                        self.logger.error(f"Task failed: {task.exception()}")
                        raise task.exception()
            
        except Exception as e:
            self.logger.error(f"Error in monitoring loop: {e}")
            raise
        finally:
            # Cancel all tasks
            for task in tasks:
                task.cancel()
            
            # Wait for tasks to complete cancellation
            await asyncio.gather(*tasks, return_exceptions=True)
            
            self.logger.info("Monitoring loop stopped")
    
    async def shutdown(self):
        """Perform graceful shutdown of all components."""
        self.logger.info("Starting graceful shutdown...")
        
        try:
            if self.engine:
                await self.engine.shutdown()
            
            if self.failover_coordinator:
                await self.failover_coordinator.shutdown()
            
            if self.health_monitor:
                await self.health_monitor.shutdown()
            
            if self.metrics_collector:
                await self.metrics_collector.shutdown()
            
            self.logger.info("Graceful shutdown completed")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
    
    async def run(self):
        """Main execution method."""
        try:
            await self.initialize_components()
            await self.start_monitoring()
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        except Exception as e:
            self.logger.error(f"Fatal error: {e}")
            sys.exit(1)
        finally:
            await self.shutdown()

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Azure to GCP Cross-Cloud DR Orchestrator"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (no actual failover operations)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--manual-failover",
        choices=["azure", "gcp"],
        help="Trigger manual failover to specified target"
    )
    
    return parser.parse_args()

async def main():
    """Main entry point."""
    args = parse_arguments()
    
    # Override log level if debug flag is set
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize orchestrator
    orchestrator = DrOrchestratorMain(args.config)
    
    # Handle manual failover mode
    if args.manual_failover:
        orchestrator.logger.info(f"Manual failover mode: target={args.manual_failover}")
        await orchestrator.initialize_components()
        
        if args.manual_failover == "gcp":
            await orchestrator.failover_coordinator.trigger_failover_to_gcp()
        else:
            await orchestrator.failover_coordinator.trigger_failover_to_azure()
        
        return
    
    # Run normal orchestration mode
    await orchestrator.run()

if __name__ == "__main__":
    # Ensure we're running in an asyncio event loop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
