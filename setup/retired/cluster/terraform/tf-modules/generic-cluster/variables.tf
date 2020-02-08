variable "ips" {
  description = "List of IPs for cluster nodes"
  type        = "list"
}

variable "macs" {
  description = "List of MAC addresses for cluster nodes for network 0"
  type        = "list"
}

# variable "macs-1" {
#   description = "List of MAC addresses for cluster nodes for network 1"
#   type        = "list"
# }

variable "nodes" {
  description = "proxmox Cluster nodes"
  type        = "list"
}

variable "name_prefix" {
  description = "Prefix for node names"
  type        = "string"
}

variable "cores" {
  description = "integer of cores to give each vm"
  type        = "string"
  default     = 4
}

variable "memory" {
  description = "amount of memory in MB give each vm"
  type        = "string"
  default     = 4096
}

variable "sshkeys" {
  description = "ssh keys to drop onto each vm"
  type        = "string"
}

variable "ssh_user" {
  description = "user to put ssh keys under"
  type        = "string"
  default     = "ubuntu"
}

variable "gateway" {
  description = "gateway for cluster"
  type        = "string"
}

variable "bridge" {
  description = "bridge to use for network"
  type        = "string"
  default     = "vmbr0"
}

variable "vlanid" {
  description = "VLAN ID to use for network"
  type        = "string"
  default     = "-1"
}

variable "bridge1" {
  description = "bridge to use for network 1"
  type        = "string"
  default     = "vmbr1"
}

# variable "vlanid1" {
#   description = "VLAN ID to use for network 1"
#   type        = "string"
#   default     = "-1"
# }

variable "storage_size" {
  description = "amount of storage to give nodes"
  type        = "string"
  default     = "32G"
}

variable "storage_pool" {
  description = "storage pool to use for disk"
  type        = "string"
  default     = "proxmox"
}

variable "storage_type" {
  description = "storage type to use for disk"
  type        = "string"
  default     = "raw"
}

variable "storage_size2" {
  description = "amount of storage to give nodes"
  type        = "string"
  default     = "64G"
}

variable "storage_pool2" {
  description = "storage pool to use for disk"
  type        = "string"
  default     = "proxmox"
}

variable "storage_type2" {
  description = "storage type to use for disk"
  type        = "string"
  default     = "raw"
}

# variable "target_node" {
#   description = "node to deploy on"
#   type        = "string"
# }

variable "template_name" {
  description = "template to use"
  type        = "string"
  default     = "ubuntu-ci"
}
