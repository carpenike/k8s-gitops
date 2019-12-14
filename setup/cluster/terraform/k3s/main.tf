provider "proxmox" {
  pm_tls_insecure = true
  pm_api_url      = "https://pve-01:8006/api2/json"
  pm_user         = "terraform@pve"
}

module "k3s-cluster" {
  source = "../tf-modules/generic-cluster"

  name_prefix = "k3s"

  # ssh_user = "k3s"

  ips = [
    "10.20.30.11",
    "10.20.30.12",
    "10.20.30.13",
  ]
  macs = [
    "DA:42:E5:28:86:7C",
    "BA:5B:64:97:59:8F",
    "52:7F:22:E5:1F:1F",
  ]
  nodes = [
    "pve-01",
    "pve-02",
    "pve-03",
  ]
  sshkeys      = <<EOF

EOF
  gateway      = "10.20.0.1"
  vlanid       = "20"
  bridge       = "vmbr0"
  storage_size = "64G"
  storage_pool = "proxmox"
  storage_type = "raw"
  memory       = "8192"
  # storage_size2 = "500G"
  # storage_pool2 = "proxmox"
  # storage_type2 = "raw"
  # target_node  = "proxmox"
}
