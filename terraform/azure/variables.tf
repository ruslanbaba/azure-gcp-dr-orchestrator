# Security-sensitive variables for Azure infrastructure

variable "azure_sql_admin_password" {
  description = "Administrator password for Azure SQL Managed Instance"
  type        = string
  sensitive   = true
  
  validation {
    condition     = length(var.azure_sql_admin_password) >= 12
    error_message = "Password must be at least 12 characters long."
  }
}

variable "azure_client_secret" {
  description = "Azure service principal client secret"
  type        = string
  sensitive   = true
}

variable "striim_admin_password" {
  description = "Striim administrator password"
  type        = string
  sensitive   = true
  
  validation {
    condition     = length(var.striim_admin_password) >= 8
    error_message = "Striim password must be at least 8 characters long."
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"
  
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "dr-orchestrator"
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "East US"
}
