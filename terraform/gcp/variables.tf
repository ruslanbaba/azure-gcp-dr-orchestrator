# Security-sensitive variables for GCP infrastructure

variable "gcp_sql_user_password" {
  description = "Password for the Cloud SQL database user"
  type        = string
  sensitive   = true
  
  validation {
    condition     = length(var.gcp_sql_user_password) >= 12
    error_message = "Password must be at least 12 characters long."
  }
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone for resources"
  type        = string
  default     = "us-central1-a"
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

variable "striim_admin_password" {
  description = "Striim administrator password"
  type        = string
  sensitive   = true
  
  validation {
    condition     = length(var.striim_admin_password) >= 8
    error_message = "Striim password must be at least 8 characters long."
  }
}
