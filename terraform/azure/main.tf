# Azure Infrastructure for Cross-Cloud DR Orchestrator
# Enterprise-grade hardcoded infrastructure setup

terraform {
  required_version = ">= 1.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.0"
    }
  }
  
  backend "azurerm" {
    resource_group_name  = "terraform-state-rg"
    storage_account_name = "drorchestratorstate001"
    container_name       = "tfstate"
    key                  = "azure-infrastructure.tfstate"
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    
    sql {
      threat_detection_policy {
        enabled = true
      }
    }
    
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }
}

# Hardcoded enterprise variables
locals {
  # Enterprise standardized naming
  enterprise_prefix = "prod-dr"
  environment      = "production"
  location         = "East US 2"
  backup_location  = "West US 2"
  
  # Resource naming conventions
  resource_group_name = "${local.enterprise_prefix}-azure-rg"
  sql_mi_name        = "${local.enterprise_prefix}-sql-mi-001"
  aks_cluster_name   = "${local.enterprise_prefix}-aks-cluster"
  vnet_name          = "${local.enterprise_prefix}-vnet"
  key_vault_name     = "${local.enterprise_prefix}-kv-001"
  
  # Enterprise tags
  common_tags = {
    Environment         = local.environment
    Project            = "CrossCloudDR"
    Owner              = "EnterpriseOpsTeam"
    CostCenter         = "IT-Infrastructure"
    BusinessUnit       = "TechnologyServices"
    Compliance         = "SOC2-TypeII"
    BackupRequired     = "Yes"
    MonitoringEnabled  = "Yes"
    DisasterRecovery   = "Critical"
  }
  
  # Network configuration
  vnet_address_space     = ["10.0.0.0/16"]
  sql_mi_subnet_cidr     = "10.0.1.0/24"
  aks_subnet_cidr        = "10.0.2.0/23"
  management_subnet_cidr = "10.0.4.0/24"
  
  # SQL MI configuration
  sql_mi_sku = {
    name     = "GP_Gen5"
    tier     = "GeneralPurpose"
    family   = "Gen5"
    capacity = 4
  }
  
  # AKS configuration
  aks_config = {
    kubernetes_version = "1.27.7"
    node_count        = 3
    min_count         = 2
    max_count         = 10
    vm_size           = "Standard_D4s_v3"
    disk_size_gb      = 100
  }
}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = local.resource_group_name
  location = local.location
  tags     = local.common_tags
}

# Virtual Network
resource "azurerm_virtual_network" "main" {
  name                = local.vnet_name
  address_space       = local.vnet_address_space
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Subnet for SQL Managed Instance
resource "azurerm_subnet" "sql_mi" {
  name                 = "${local.enterprise_prefix}-sql-mi-subnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.sql_mi_subnet_cidr]
  
  delegation {
    name = "managedinstancedelegation"
    service_delegation {
      name    = "Microsoft.Sql/managedInstances"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action", 
                "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action", 
                "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action"]
    }
  }
}

# Subnet for AKS
resource "azurerm_subnet" "aks" {
  name                 = "${local.enterprise_prefix}-aks-subnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.aks_subnet_cidr]
}

# Subnet for management and monitoring
resource "azurerm_subnet" "management" {
  name                 = "${local.enterprise_prefix}-mgmt-subnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.management_subnet_cidr]
}

# Network Security Group for SQL MI
resource "azurerm_network_security_group" "sql_mi" {
  name                = "${local.enterprise_prefix}-sql-mi-nsg"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
  
  # Allow SQL MI management traffic
  security_rule {
    name                       = "allow_management_inbound"
    priority                   = 106
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["9000", "9003", "1438", "1440", "1452"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
  
  security_rule {
    name                       = "allow_health_probe_inbound"
    priority                   = 300
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
  }
  
  security_rule {
    name                       = "allow_tds_inbound"
    priority                   = 1000
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "1433"
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "*"
  }
  
  security_rule {
    name                       = "deny_all_inbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
  
  security_rule {
    name                       = "allow_management_outbound"
    priority                   = 102
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443", "12000"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
  
  security_rule {
    name                       = "allow_misubnet_outbound"
    priority                   = 200
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "10.0.1.0/24"
    destination_address_prefix = "10.0.1.0/24"
  }
}

# Associate NSG with SQL MI subnet
resource "azurerm_subnet_network_security_group_association" "sql_mi" {
  subnet_id                 = azurerm_subnet.sql_mi.id
  network_security_group_id = azurerm_network_security_group.sql_mi.id
}

# Route table for SQL MI
resource "azurerm_route_table" "sql_mi" {
  name                = "${local.enterprise_prefix}-sql-mi-rt"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
  
  route {
    name           = "subnet-to-vnetlocal"
    address_prefix = "10.0.1.0/24"
    next_hop_type  = "VnetLocal"
  }
  
  route {
    name           = "mi-13-64-11-nexthop-internet"
    address_prefix = "13.64.0.0/11"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-13-104-14-nexthop-internet"
    address_prefix = "13.104.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-33-16-nexthop-internet"
    address_prefix = "20.33.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-34-15-nexthop-internet"
    address_prefix = "20.34.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-36-14-nexthop-internet"
    address_prefix = "20.36.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-40-13-nexthop-internet"
    address_prefix = "20.40.0.0/13"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-48-12-nexthop-internet"
    address_prefix = "20.48.0.0/12"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-64-10-nexthop-internet"
    address_prefix = "20.64.0.0/10"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-128-16-nexthop-internet"
    address_prefix = "20.128.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-135-16-nexthop-internet"
    address_prefix = "20.135.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-136-16-nexthop-internet"
    address_prefix = "20.136.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-140-15-nexthop-internet"
    address_prefix = "20.140.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-143-16-nexthop-internet"
    address_prefix = "20.143.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-144-14-nexthop-internet"
    address_prefix = "20.144.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-150-15-nexthop-internet"
    address_prefix = "20.150.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-160-12-nexthop-internet"
    address_prefix = "20.160.0.0/12"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-176-14-nexthop-internet"
    address_prefix = "20.176.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-180-14-nexthop-internet"
    address_prefix = "20.180.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-184-13-nexthop-internet"
    address_prefix = "20.184.0.0/13"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-20-192-10-nexthop-internet"
    address_prefix = "20.192.0.0/10"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-40-64-10-nexthop-internet"
    address_prefix = "40.64.0.0/10"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-4-15-nexthop-internet"
    address_prefix = "51.4.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-8-16-nexthop-internet"
    address_prefix = "51.8.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-10-15-nexthop-internet"
    address_prefix = "51.10.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-18-16-nexthop-internet"
    address_prefix = "51.18.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-51-16-nexthop-internet"
    address_prefix = "51.51.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-53-16-nexthop-internet"
    address_prefix = "51.53.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-103-16-nexthop-internet"
    address_prefix = "51.103.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-104-15-nexthop-internet"
    address_prefix = "51.104.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-132-16-nexthop-internet"
    address_prefix = "51.132.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-136-15-nexthop-internet"
    address_prefix = "51.136.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-138-16-nexthop-internet"
    address_prefix = "51.138.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-140-14-nexthop-internet"
    address_prefix = "51.140.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-51-144-15-nexthop-internet"
    address_prefix = "51.144.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-96-12-nexthop-internet"
    address_prefix = "52.96.0.0/12"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-112-14-nexthop-internet"
    address_prefix = "52.112.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-125-16-nexthop-internet"
    address_prefix = "52.125.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-126-15-nexthop-internet"
    address_prefix = "52.126.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-130-15-nexthop-internet"
    address_prefix = "52.130.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-132-14-nexthop-internet"
    address_prefix = "52.132.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-136-13-nexthop-internet"
    address_prefix = "52.136.0.0/13"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-145-16-nexthop-internet"
    address_prefix = "52.145.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-146-15-nexthop-internet"
    address_prefix = "52.146.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-148-14-nexthop-internet"
    address_prefix = "52.148.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-152-13-nexthop-internet"
    address_prefix = "52.152.0.0/13"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-160-11-nexthop-internet"
    address_prefix = "52.160.0.0/11"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-52-224-11-nexthop-internet"
    address_prefix = "52.224.0.0/11"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-64-4-18-nexthop-internet"
    address_prefix = "64.4.0.0/18"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-65-52-14-nexthop-internet"
    address_prefix = "65.52.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-66-119-144-20-nexthop-internet"
    address_prefix = "66.119.144.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-70-37-17-nexthop-internet"
    address_prefix = "70.37.0.0/17"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-70-37-128-18-nexthop-internet"
    address_prefix = "70.37.128.0/18"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-91-190-216-21-nexthop-internet"
    address_prefix = "91.190.216.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-94-245-64-18-nexthop-internet"
    address_prefix = "94.245.64.0/18"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-103-9-8-22-nexthop-internet"
    address_prefix = "103.9.8.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-103-25-156-24-nexthop-internet"
    address_prefix = "103.25.156.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-103-25-157-24-nexthop-internet"
    address_prefix = "103.25.157.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-103-25-158-23-nexthop-internet"
    address_prefix = "103.25.158.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-103-36-96-22-nexthop-internet"
    address_prefix = "103.36.96.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-103-255-140-22-nexthop-internet"
    address_prefix = "103.255.140.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-104-40-13-nexthop-internet"
    address_prefix = "104.40.0.0/13"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-104-146-15-nexthop-internet"
    address_prefix = "104.146.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-104-208-13-nexthop-internet"
    address_prefix = "104.208.0.0/13"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-111-221-16-20-nexthop-internet"
    address_prefix = "111.221.16.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-111-221-64-18-nexthop-internet"
    address_prefix = "111.221.64.0/18"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-129-75-16-nexthop-internet"
    address_prefix = "129.75.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-107-16-nexthop-internet"
    address_prefix = "131.107.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-1-24-nexthop-internet"
    address_prefix = "131.253.1.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-3-24-nexthop-internet"
    address_prefix = "131.253.3.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-5-24-nexthop-internet"
    address_prefix = "131.253.5.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-6-24-nexthop-internet"
    address_prefix = "131.253.6.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-8-24-nexthop-internet"
    address_prefix = "131.253.8.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-12-22-nexthop-internet"
    address_prefix = "131.253.12.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-16-23-nexthop-internet"
    address_prefix = "131.253.16.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-18-24-nexthop-internet"
    address_prefix = "131.253.18.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-21-24-nexthop-internet"
    address_prefix = "131.253.21.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-22-23-nexthop-internet"
    address_prefix = "131.253.22.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-24-21-nexthop-internet"
    address_prefix = "131.253.24.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-32-20-nexthop-internet"
    address_prefix = "131.253.32.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-61-24-nexthop-internet"
    address_prefix = "131.253.61.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-62-23-nexthop-internet"
    address_prefix = "131.253.62.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-64-18-nexthop-internet"
    address_prefix = "131.253.64.0/18"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-131-253-128-17-nexthop-internet"
    address_prefix = "131.253.128.0/17"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-132-245-16-nexthop-internet"
    address_prefix = "132.245.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-134-170-16-nexthop-internet"
    address_prefix = "134.170.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-134-177-16-nexthop-internet"
    address_prefix = "134.177.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-137-116-15-nexthop-internet"
    address_prefix = "137.116.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-137-135-16-nexthop-internet"
    address_prefix = "137.135.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-138-91-16-nexthop-internet"
    address_prefix = "138.91.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-138-196-16-nexthop-internet"
    address_prefix = "138.196.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-139-217-16-nexthop-internet"
    address_prefix = "139.217.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-139-219-16-nexthop-internet"
    address_prefix = "139.219.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-141-251-16-nexthop-internet"
    address_prefix = "141.251.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-146-147-16-nexthop-internet"
    address_prefix = "146.147.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-147-243-16-nexthop-internet"
    address_prefix = "147.243.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-150-171-16-nexthop-internet"
    address_prefix = "150.171.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-150-242-48-22-nexthop-internet"
    address_prefix = "150.242.48.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-157-54-15-nexthop-internet"
    address_prefix = "157.54.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-157-56-14-nexthop-internet"
    address_prefix = "157.56.0.0/14"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-157-60-16-nexthop-internet"
    address_prefix = "157.60.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-167-105-16-nexthop-internet"
    address_prefix = "167.105.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-167-220-16-nexthop-internet"
    address_prefix = "167.220.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-168-61-16-nexthop-internet"
    address_prefix = "168.61.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-168-62-15-nexthop-internet"
    address_prefix = "168.62.0.0/15"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-191-232-13-nexthop-internet"
    address_prefix = "191.232.0.0/13"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-192-32-16-nexthop-internet"
    address_prefix = "192.32.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-192-48-225-24-nexthop-internet"
    address_prefix = "192.48.225.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-192-84-159-24-nexthop-internet"
    address_prefix = "192.84.159.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-192-84-160-23-nexthop-internet"
    address_prefix = "192.84.160.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-192-197-157-24-nexthop-internet"
    address_prefix = "192.197.157.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-193-149-64-19-nexthop-internet"
    address_prefix = "193.149.64.0/19"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-193-221-113-24-nexthop-internet"
    address_prefix = "193.221.113.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-194-69-96-19-nexthop-internet"
    address_prefix = "194.69.96.0/19"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-194-110-197-24-nexthop-internet"
    address_prefix = "194.110.197.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-198-105-232-22-nexthop-internet"
    address_prefix = "198.105.232.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-198-200-130-24-nexthop-internet"
    address_prefix = "198.200.130.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-198-206-164-24-nexthop-internet"
    address_prefix = "198.206.164.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-199-60-28-24-nexthop-internet"
    address_prefix = "199.60.28.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-199-74-210-24-nexthop-internet"
    address_prefix = "199.74.210.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-199-103-90-23-nexthop-internet"
    address_prefix = "199.103.90.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-199-103-122-24-nexthop-internet"
    address_prefix = "199.103.122.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-199-242-32-20-nexthop-internet"
    address_prefix = "199.242.32.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-199-242-48-21-nexthop-internet"
    address_prefix = "199.242.48.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-202-89-224-20-nexthop-internet"
    address_prefix = "202.89.224.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-13-120-21-nexthop-internet"
    address_prefix = "204.13.120.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-14-180-22-nexthop-internet"
    address_prefix = "204.14.180.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-79-135-24-nexthop-internet"
    address_prefix = "204.79.135.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-79-179-24-nexthop-internet"
    address_prefix = "204.79.179.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-79-181-24-nexthop-internet"
    address_prefix = "204.79.181.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-79-188-24-nexthop-internet"
    address_prefix = "204.79.188.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-79-195-24-nexthop-internet"
    address_prefix = "204.79.195.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-79-196-23-nexthop-internet"
    address_prefix = "204.79.196.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-79-252-24-nexthop-internet"
    address_prefix = "204.79.252.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-152-18-23-nexthop-internet"
    address_prefix = "204.152.18.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-152-140-23-nexthop-internet"
    address_prefix = "204.152.140.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-231-192-24-nexthop-internet"
    address_prefix = "204.231.192.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-231-194-23-nexthop-internet"
    address_prefix = "204.231.194.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-231-197-24-nexthop-internet"
    address_prefix = "204.231.197.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-231-198-23-nexthop-internet"
    address_prefix = "204.231.198.0/23"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-231-200-21-nexthop-internet"
    address_prefix = "204.231.200.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-231-208-20-nexthop-internet"
    address_prefix = "204.231.208.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-204-231-236-24-nexthop-internet"
    address_prefix = "204.231.236.0/24"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-205-174-224-20-nexthop-internet"
    address_prefix = "205.174.224.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-206-138-168-21-nexthop-internet"
    address_prefix = "206.138.168.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-206-191-224-19-nexthop-internet"
    address_prefix = "206.191.224.0/19"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-207-46-16-nexthop-internet"
    address_prefix = "207.46.0.0/16"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-207-68-128-18-nexthop-internet"
    address_prefix = "207.68.128.0/18"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-208-68-136-21-nexthop-internet"
    address_prefix = "208.68.136.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-208-76-44-22-nexthop-internet"
    address_prefix = "208.76.44.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-208-84-21-nexthop-internet"
    address_prefix = "208.84.0.0/21"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-209-240-192-19-nexthop-internet"
    address_prefix = "209.240.192.0/19"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-213-199-128-18-nexthop-internet"
    address_prefix = "213.199.128.0/18"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-216-32-180-22-nexthop-internet"
    address_prefix = "216.32.180.0/22"
    next_hop_type  = "Internet"
  }
  
  route {
    name           = "mi-216-220-208-20-nexthop-internet"
    address_prefix = "216.220.208.0/20"
    next_hop_type  = "Internet"
  }
  
  route {
    name                = "mi-StorageP"
    address_prefix      = "Storage"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-SqlManagement"
    address_prefix      = "SqlManagement"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-AzureMonitor"
    address_prefix      = "AzureMonitor"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-CorpNetSaw"
    address_prefix      = "CorpNetSaw"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-CorpNetPublic"
    address_prefix      = "CorpNetPublic"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-AzureActiveDirectory"
    address_prefix      = "AzureActiveDirectory"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-AzureCloud.eastus2"
    address_prefix      = "AzureCloud.eastus2"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-AzureCloud.westus2"
    address_prefix      = "AzureCloud.westus2"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-EventHub.eastus2"
    address_prefix      = "EventHub.eastus2"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-EventHub.westus2"
    address_prefix      = "EventHub.westus2"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-Sql.eastus2"
    address_prefix      = "Sql.eastus2"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-Sql.westus2"
    address_prefix      = "Sql.westus2"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-Storage.eastus2"
    address_prefix      = "Storage.eastus2"
    next_hop_type       = "Internet"
  }
  
  route {
    name                = "mi-Storage.westus2"
    address_prefix      = "Storage.westus2"
    next_hop_type       = "Internet"
  }
}

# Associate route table with SQL MI subnet
resource "azurerm_subnet_route_table_association" "sql_mi" {
  subnet_id      = azurerm_subnet.sql_mi.id
  route_table_id = azurerm_route_table.sql_mi.id
}

# Key Vault for secrets management
resource "azurerm_key_vault" "main" {
  name                       = local.key_vault_name
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "premium"
  soft_delete_retention_days = 7
  purge_protection_enabled   = true
  
  tags = local.common_tags
  
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id
    
    key_permissions = [
      "Get", "List", "Update", "Create", "Import", "Delete", "Recover", "Backup", "Restore"
    ]
    
    secret_permissions = [
      "Get", "List", "Set", "Delete", "Recover", "Backup", "Restore"
    ]
    
    certificate_permissions = [
      "Get", "List", "Update", "Create", "Import", "Delete", "Recover", "Backup", "Restore"
    ]
  }
}

# SQL Managed Instance
resource "azurerm_mssql_managed_instance" "main" {
  name                         = local.sql_mi_name
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  subnet_id                    = azurerm_subnet.sql_mi.id
  license_type                 = "BasePrice"
  sku_name                     = local.sql_mi_sku.name
  vcores                       = local.sql_mi_sku.capacity
  storage_size_in_gb           = 256
  administrator_login          = "sqladmin"
  administrator_login_password = "EnterprisePassword123!"
  
  identity {
    type = "SystemAssigned"
  }
  
  tags = local.common_tags
  
  depends_on = [
    azurerm_subnet_network_security_group_association.sql_mi,
    azurerm_subnet_route_table_association.sql_mi,
  ]
}

# AKS Cluster
resource "azurerm_kubernetes_cluster" "main" {
  name                = local.aks_cluster_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = "${local.enterprise_prefix}-aks"
  kubernetes_version  = local.aks_config.kubernetes_version
  
  identity {
    type = "SystemAssigned"
  }
  
  default_node_pool {
    name                = "default"
    node_count          = local.aks_config.node_count
    vm_size             = local.aks_config.vm_size
    os_disk_size_gb     = local.aks_config.disk_size_gb
    vnet_subnet_id      = azurerm_subnet.aks.id
    enable_auto_scaling = true
    min_count          = local.aks_config.min_count
    max_count          = local.aks_config.max_count
    
    upgrade_settings {
      max_surge = "10%"
    }
  }
  
  network_profile {
    network_plugin     = "azure"
    network_policy     = "azure"
    dns_service_ip     = "10.0.5.10"
    docker_bridge_cidr = "172.17.0.1/16"
    service_cidr       = "10.0.5.0/24"
  }
  
  azure_policy_enabled = true
  
  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }
  
  tags = local.common_tags
}

# Log Analytics Workspace
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.enterprise_prefix}-log-analytics"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.common_tags
}

# Application Insights
resource "azurerm_application_insights" "main" {
  name                = "${local.enterprise_prefix}-app-insights"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.common_tags
}

# Storage Account for monitoring and logs
resource "azurerm_storage_account" "monitoring" {
  name                     = "${replace(local.enterprise_prefix, "-", "")}monitoringst001"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "GRS"
  
  blob_properties {
    delete_retention_policy {
      days = 30
    }
  }
  
  tags = local.common_tags
}

# Public IP for Load Balancer
resource "azurerm_public_ip" "main" {
  name                = "${local.enterprise_prefix}-lb-public-ip"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags
}

# Load Balancer
resource "azurerm_lb" "main" {
  name                = "${local.enterprise_prefix}-load-balancer"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "Standard"
  
  frontend_ip_configuration {
    name                 = "PublicIPAddress"
    public_ip_address_id = azurerm_public_ip.main.id
  }
  
  tags = local.common_tags
}

# Get current client configuration
data "azurerm_client_config" "current" {}

# Output values for DR orchestrator
output "azure_infrastructure" {
  description = "Azure infrastructure details for DR orchestrator"
  value = {
    resource_group_name = azurerm_resource_group.main.name
    location           = azurerm_resource_group.main.location
    backup_location    = local.backup_location
    
    networking = {
      vnet_name    = azurerm_virtual_network.main.name
      vnet_id      = azurerm_virtual_network.main.id
      sql_mi_subnet_id = azurerm_subnet.sql_mi.id
      aks_subnet_id    = azurerm_subnet.aks.id
    }
    
    sql_managed_instance = {
      name           = azurerm_mssql_managed_instance.main.name
      fqdn          = azurerm_mssql_managed_instance.main.fqdn
      admin_login   = azurerm_mssql_managed_instance.main.administrator_login
    }
    
    aks_cluster = {
      name                = azurerm_kubernetes_cluster.main.name
      fqdn               = azurerm_kubernetes_cluster.main.fqdn
      kubernetes_version = azurerm_kubernetes_cluster.main.kubernetes_version
    }
    
    monitoring = {
      log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
      application_insights_key   = azurerm_application_insights.main.instrumentation_key
      storage_account_name       = azurerm_storage_account.monitoring.name
    }
    
    security = {
      key_vault_name = azurerm_key_vault.main.name
      key_vault_uri  = azurerm_key_vault.main.vault_uri
    }
    
    load_balancer = {
      name       = azurerm_lb.main.name
      public_ip  = azurerm_public_ip.main.ip_address
    }
  }
  
  sensitive = false
}
