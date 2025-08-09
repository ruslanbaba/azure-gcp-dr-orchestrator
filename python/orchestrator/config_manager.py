#!/usr/bin/env python3
"""
Configuration Manager - Manages enterprise configuration for DR orchestrator

This module handles configuration loading, validation, and management for the
cross-cloud disaster recovery orchestrator with enterprise-grade settings.

Author: Enterprise DR Team
Version: 1.0.0
"""

import os
import yaml
import json
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class CloudConfig:
    """Cloud provider configuration"""
    subscription_id: str = ""
    project_id: str = ""
    region: str = ""
    backup_region: str = ""
    resource_group: str = ""
    vpc_network: str = ""

@dataclass
class FailoverConfig:
    """Failover configuration"""
    rto_target_seconds: int = 300
    rpo_target_seconds: int = 30
    health_check_interval: int = 10
    max_retry_attempts: int = 3
    backoff_multiplier: int = 2
    auto_failover_enabled: bool = True
    rollback_enabled: bool = True

@dataclass
class MonitoringConfig:
    """Monitoring configuration"""
    prometheus_endpoint: str = ""
    grafana_endpoint: str = ""
    alert_webhook: str = ""
    slack_channel: str = ""
    pagerduty_key: str = ""

class ConfigManager:
    """
    Enterprise configuration manager for DR orchestrator.
    
    Handles loading, validation, and management of configuration from multiple
    sources including files, environment variables, and enterprise secrets.
    """
    
    def __init__(self, config_path: Optional[str] = None, default_config: Optional[Dict[str, Any]] = None):
        """Initialize the configuration manager."""
        self.logger = logging.getLogger(__name__)
        self.config_path = config_path
        self.default_config = default_config or {}
        
        # Configuration hierarchy (order matters - later sources override earlier ones)
        self.config_sources = [
            "default_hardcoded",
            "config_file",
            "environment_variables",
            "enterprise_secrets"
        ]
        
        # Loaded configuration
        self.config = {}
        self.config_metadata = {
            "loaded_from": [],
            "load_timestamp": None,
            "validation_errors": [],
            "warnings": []
        }
        
        # Enterprise configuration schema (hardcoded validation rules)
        self.config_schema = {
            "azure": {
                "required": ["subscription_id", "resource_group", "region"],
                "optional": ["backup_region", "sql_mi_instance", "aks_cluster"]
            },
            "gcp": {
                "required": ["project_id", "region"],
                "optional": ["backup_region", "cloud_sql_instance", "gke_cluster", "vpc_network"]
            },
            "failover": {
                "required": ["rto_target_seconds", "rpo_target_seconds"],
                "optional": ["health_check_interval", "max_retry_attempts", "auto_failover_enabled"]
            },
            "monitoring": {
                "required": [],
                "optional": ["prometheus_endpoint", "grafana_endpoint", "alert_webhook"]
            },
            "striim": {
                "required": ["server_url", "app_name"],
                "optional": ["username", "password_secret", "flow_name"]
            }
        }
        
        # Environment variable mappings (enterprise standard naming)
        self.env_mappings = {
            "AZURE_SUBSCRIPTION_ID": "azure.subscription_id",
            "AZURE_RESOURCE_GROUP": "azure.resource_group",
            "AZURE_REGION": "azure.region",
            "AZURE_BACKUP_REGION": "azure.backup_region",
            "AZURE_SQL_MI_INSTANCE": "azure.sql_mi_instance",
            "AZURE_AKS_CLUSTER": "azure.aks_cluster",
            
            "GCP_PROJECT_ID": "gcp.project_id",
            "GCP_REGION": "gcp.region",
            "GCP_BACKUP_REGION": "gcp.backup_region",
            "GCP_CLOUD_SQL_INSTANCE": "gcp.cloud_sql_instance",
            "GCP_GKE_CLUSTER": "gcp.gke_cluster",
            "GCP_VPC_NETWORK": "gcp.vpc_network",
            
            "DR_RTO_TARGET": "failover.rto_target_seconds",
            "DR_RPO_TARGET": "failover.rpo_target_seconds",
            "DR_HEALTH_CHECK_INTERVAL": "failover.health_check_interval",
            "DR_AUTO_FAILOVER": "failover.auto_failover_enabled",
            
            "PROMETHEUS_ENDPOINT": "monitoring.prometheus_endpoint",
            "GRAFANA_ENDPOINT": "monitoring.grafana_endpoint",
            "ALERT_WEBHOOK": "monitoring.alert_webhook",
            "SLACK_CHANNEL": "monitoring.slack_channel",
            "PAGERDUTY_KEY": "monitoring.pagerduty_key",
            
            "STRIIM_SERVER_URL": "striim.server_url",
            "STRIIM_USERNAME": "striim.username",
            "STRIIM_PASSWORD_SECRET": "striim.password_secret",
            "STRIIM_APP_NAME": "striim.app_name",
            "STRIIM_FLOW_NAME": "striim.flow_name"
        }
        
        # Load configuration on initialization
        self._load_configuration()
        
        self.logger.info("Configuration manager initialized")
    
    def _load_configuration(self):
        """Load configuration from all sources."""
        try:
            self.config_metadata["load_timestamp"] = datetime.utcnow()
            
            # Start with default hardcoded configuration
            if self.default_config:
                self.config = self._deep_merge(self.config, self.default_config)
                self.config_metadata["loaded_from"].append("default_hardcoded")
                self.logger.debug("Loaded default hardcoded configuration")
            
            # Load from configuration file
            if self.config_path:
                file_config = self._load_from_file(self.config_path)
                if file_config:
                    self.config = self._deep_merge(self.config, file_config)
                    self.config_metadata["loaded_from"].append("config_file")
                    self.logger.info(f"Loaded configuration from file: {self.config_path}")
            
            # Load from environment variables
            env_config = self._load_from_environment()
            if env_config:
                self.config = self._deep_merge(self.config, env_config)
                self.config_metadata["loaded_from"].append("environment_variables")
                self.logger.info("Loaded configuration from environment variables")
            
            # Load from enterprise secrets (placeholder)
            secrets_config = self._load_from_enterprise_secrets()
            if secrets_config:
                self.config = self._deep_merge(self.config, secrets_config)
                self.config_metadata["loaded_from"].append("enterprise_secrets")
                self.logger.info("Loaded configuration from enterprise secrets")
            
            # Validate final configuration
            self._validate_configuration()
            
            # Apply enterprise defaults and transformations
            self._apply_enterprise_defaults()
            
            self.logger.info(f"Configuration loaded successfully from sources: {self.config_metadata['loaded_from']}")
            
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _load_from_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Load configuration from file."""
        try:
            path = Path(file_path)
            if not path.exists():
                self.config_metadata["warnings"].append(f"Configuration file not found: {file_path}")
                return None
            
            with open(path, 'r', encoding='utf-8') as f:
                if path.suffix.lower() == '.yaml' or path.suffix.lower() == '.yml':
                    config = yaml.safe_load(f)
                elif path.suffix.lower() == '.json':
                    config = json.load(f)
                else:
                    self.config_metadata["warnings"].append(f"Unsupported config file format: {path.suffix}")
                    return None
            
            return config
            
        except Exception as e:
            self.config_metadata["validation_errors"].append(f"Failed to load config file {file_path}: {e}")
            return None
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        try:
            env_config = {}
            
            for env_var, config_path in self.env_mappings.items():
                value = os.getenv(env_var)
                if value is not None:
                    # Convert string values to appropriate types
                    converted_value = self._convert_env_value(value)
                    self._set_nested_value(env_config, config_path, converted_value)
            
            return env_config
            
        except Exception as e:
            self.config_metadata["validation_errors"].append(f"Failed to load environment variables: {e}")
            return {}
    
    def _load_from_enterprise_secrets(self) -> Dict[str, Any]:
        """Load configuration from enterprise secret management system."""
        try:
            # Placeholder for enterprise secret management integration
            # In real implementation, this would integrate with HashiCorp Vault,
            # Azure Key Vault, AWS Secrets Manager, or similar
            
            secrets_config = {}
            
            # Simulate loading sensitive configuration from secrets
            secret_mappings = {
                "azure-sql-connection": "azure.sql_connection_string",
                "gcp-sql-connection": "gcp.sql_connection_string",
                "striim-admin-password": "striim.password",
                "webhook-auth-token": "monitoring.webhook_auth_token"
            }
            
            for secret_name, config_path in secret_mappings.items():
                # In real implementation, this would make API calls to secret store
                secret_value = self._get_enterprise_secret(secret_name)
                if secret_value:
                    self._set_nested_value(secrets_config, config_path, secret_value)
            
            return secrets_config
            
        except Exception as e:
            self.config_metadata["validation_errors"].append(f"Failed to load enterprise secrets: {e}")
            return {}
    
    def _get_enterprise_secret(self, secret_name: str) -> Optional[str]:
        """Get secret from enterprise secret store."""
        # Placeholder implementation
        # In real enterprise environment, this would integrate with:
        # - HashiCorp Vault
        # - Azure Key Vault
        # - AWS Secrets Manager
        # - Kubernetes Secrets
        # - etc.
        
        hardcoded_secrets = {
            "azure-sql-connection": "Server=prod-sql-mi-001.database.windows.net;Database=primary_db;",
            "gcp-sql-connection": "postgresql://user@prod-cloudsql-001:5432/secondary_db",
            "striim-admin-password": "SecureStriimPassword123!",
            "webhook-auth-token": "webhook-auth-token-12345"
        }
        
        return hardcoded_secrets.get(secret_name)
    
    def _convert_env_value(self, value: str) -> Any:
        """Convert environment variable string to appropriate type."""
        # Handle boolean values
        if value.lower() in ('true', 'yes', '1', 'on'):
            return True
        if value.lower() in ('false', 'no', '0', 'off'):
            return False
        
        # Handle numeric values
        if value.isdigit():
            return int(value)
        
        try:
            return float(value)
        except ValueError:
            pass
        
        # Return as string
        return value
    
    def _set_nested_value(self, config: Dict[str, Any], path: str, value: Any):
        """Set a nested configuration value using dot notation."""
        keys = path.split('.')
        current = config
        
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries."""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _validate_configuration(self):
        """Validate the loaded configuration against schema."""
        try:
            validation_errors = []
            
            # Validate each section
            for section_name, schema in self.config_schema.items():
                if section_name not in self.config:
                    if schema["required"]:
                        validation_errors.append(f"Missing required configuration section: {section_name}")
                    continue
                
                section_config = self.config[section_name]
                
                # Check required fields
                for required_field in schema["required"]:
                    if required_field not in section_config:
                        validation_errors.append(
                            f"Missing required field: {section_name}.{required_field}"
                        )
                
                # Validate field types and values
                validation_errors.extend(
                    self._validate_section_values(section_name, section_config)
                )
            
            # Store validation errors
            self.config_metadata["validation_errors"].extend(validation_errors)
            
            if validation_errors:
                self.logger.warning(f"Configuration validation errors: {validation_errors}")
            else:
                self.logger.info("Configuration validation passed")
            
        except Exception as e:
            self.config_metadata["validation_errors"].append(f"Configuration validation failed: {e}")
    
    def _validate_section_values(self, section_name: str, section_config: Dict[str, Any]) -> List[str]:
        """Validate values in a configuration section."""
        errors = []
        
        try:
            if section_name == "failover":
                # Validate failover configuration
                rto = section_config.get("rto_target_seconds", 0)
                if rto <= 0 or rto > 3600:  # Max 1 hour RTO
                    errors.append("failover.rto_target_seconds must be between 1 and 3600")
                
                rpo = section_config.get("rpo_target_seconds", 0)
                if rpo < 0 or rpo > 300:  # Max 5 minutes RPO
                    errors.append("failover.rpo_target_seconds must be between 0 and 300")
                
                health_check = section_config.get("health_check_interval", 0)
                if health_check <= 0 or health_check > 300:
                    errors.append("failover.health_check_interval must be between 1 and 300")
            
            elif section_name == "azure":
                # Validate Azure configuration
                subscription_id = section_config.get("subscription_id", "")
                if subscription_id and not self._is_valid_uuid(subscription_id):
                    errors.append("azure.subscription_id must be a valid UUID")
            
            elif section_name == "gcp":
                # Validate GCP configuration
                project_id = section_config.get("project_id", "")
                if project_id and not self._is_valid_gcp_project_id(project_id):
                    errors.append("gcp.project_id must be a valid GCP project ID")
            
            elif section_name == "striim":
                # Validate Striim configuration
                server_url = section_config.get("server_url", "")
                if server_url and not self._is_valid_url(server_url):
                    errors.append("striim.server_url must be a valid URL")
            
        except Exception as e:
            errors.append(f"Error validating {section_name}: {e}")
        
        return errors
    
    def _is_valid_uuid(self, uuid_string: str) -> bool:
        """Validate UUID format."""
        try:
            import uuid
            uuid.UUID(uuid_string)
            return True
        except ValueError:
            return False
    
    def _is_valid_gcp_project_id(self, project_id: str) -> bool:
        """Validate GCP project ID format."""
        import re
        # GCP project IDs must be 6-30 characters, lowercase letters, digits, and hyphens
        pattern = r'^[a-z][a-z0-9-]{4,28}[a-z0-9]$'
        return re.match(pattern, project_id) is not None
    
    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format."""
        try:
            from urllib.parse import urlparse
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    def _apply_enterprise_defaults(self):
        """Apply enterprise-specific defaults and transformations."""
        try:
            # Set enterprise default values if not specified
            enterprise_defaults = {
                "failover": {
                    "max_retry_attempts": 3,
                    "backoff_multiplier": 2,
                    "auto_failover_enabled": True,
                    "rollback_enabled": True
                },
                "monitoring": {
                    "collection_interval": 30,
                    "retention_days": 30,
                    "alert_threshold_critical": 0.5,
                    "alert_threshold_warning": 0.8
                },
                "enterprise": {
                    "environment": "production",
                    "compliance_level": "SOC2",
                    "encryption_enabled": True,
                    "audit_logging": True
                }
            }
            
            self.config = self._deep_merge(enterprise_defaults, self.config)
            
            # Apply enterprise transformations
            self._apply_enterprise_transformations()
            
            self.logger.info("Applied enterprise defaults and transformations")
            
        except Exception as e:
            self.config_metadata["warnings"].append(f"Failed to apply enterprise defaults: {e}")
    
    def _apply_enterprise_transformations(self):
        """Apply enterprise-specific configuration transformations."""
        try:
            # Ensure all regions have backup regions
            if "azure" in self.config and "backup_region" not in self.config["azure"]:
                primary_region = self.config["azure"].get("region", "eastus2")
                backup_mapping = {
                    "eastus2": "westus2",
                    "westus2": "eastus2",
                    "northeurope": "westeurope",
                    "westeurope": "northeurope"
                }
                self.config["azure"]["backup_region"] = backup_mapping.get(primary_region, "westus2")
            
            if "gcp" in self.config and "backup_region" not in self.config["gcp"]:
                primary_region = self.config["gcp"].get("region", "us-central1")
                backup_mapping = {
                    "us-central1": "us-west1",
                    "us-west1": "us-central1",
                    "europe-west1": "europe-west2",
                    "europe-west2": "europe-west1"
                }
                self.config["gcp"]["backup_region"] = backup_mapping.get(primary_region, "us-west1")
            
            # Ensure monitoring endpoints are configured
            if "monitoring" in self.config:
                if not self.config["monitoring"].get("prometheus_endpoint"):
                    self.config["monitoring"]["prometheus_endpoint"] = "http://monitoring.enterprise.com:9090"
                
                if not self.config["monitoring"].get("grafana_endpoint"):
                    self.config["monitoring"]["grafana_endpoint"] = "http://monitoring.enterprise.com:3000"
            
        except Exception as e:
            self.config_metadata["warnings"].append(f"Failed to apply enterprise transformations: {e}")
    
    # Public interface methods
    
    def get_config(self) -> Dict[str, Any]:
        """Get the complete configuration."""
        return self.config.copy()
    
    def get_section(self, section_name: str) -> Dict[str, Any]:
        """Get a specific configuration section."""
        return self.config.get(section_name, {}).copy()
    
    def get_value(self, path: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation."""
        try:
            keys = path.split('.')
            current = self.config
            
            for key in keys:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return default
            
            return current
            
        except Exception:
            return default
    
    def set_value(self, path: str, value: Any) -> bool:
        """Set a configuration value using dot notation."""
        try:
            keys = path.split('.')
            current = self.config
            
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            
            current[keys[-1]] = value
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to set config value {path}: {e}")
            return False
    
    def reload_configuration(self):
        """Reload configuration from all sources."""
        self.logger.info("Reloading configuration...")
        self.config = {}
        self.config_metadata = {
            "loaded_from": [],
            "load_timestamp": None,
            "validation_errors": [],
            "warnings": []
        }
        self._load_configuration()
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get configuration metadata."""
        return self.config_metadata.copy()
    
    def is_valid(self) -> bool:
        """Check if the configuration is valid."""
        return len(self.config_metadata["validation_errors"]) == 0
    
    def get_validation_errors(self) -> List[str]:
        """Get configuration validation errors."""
        return self.config_metadata["validation_errors"].copy()
    
    def get_warnings(self) -> List[str]:
        """Get configuration warnings."""
        return self.config_metadata["warnings"].copy()
    
    def export_config(self, file_path: str, format: str = "yaml") -> bool:
        """Export current configuration to file."""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            if format.lower() == "yaml":
                with open(path, 'w', encoding='utf-8') as f:
                    yaml.dump(self.config, f, default_flow_style=False, indent=2)
            elif format.lower() == "json":
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
            else:
                self.logger.error(f"Unsupported export format: {format}")
                return False
            
            self.logger.info(f"Configuration exported to: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export configuration: {e}")
            return False
    
    def __str__(self) -> str:
        """String representation of configuration (sanitized)."""
        sanitized_config = self._sanitize_config_for_display(self.config)
        return json.dumps(sanitized_config, indent=2)
    
    def _sanitize_config_for_display(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize configuration for display (hide sensitive values)."""
        sanitized = {}
        sensitive_keys = ["password", "secret", "key", "token", "connection_string"]
        
        for key, value in config.items():
            if isinstance(value, dict):
                sanitized[key] = self._sanitize_config_for_display(value)
            elif any(sensitive_key in key.lower() for sensitive_key in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value
        
        return sanitized
