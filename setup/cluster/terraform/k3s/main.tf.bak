provider "proxmox" {
  pm_tls_insecure = true
  pm_api_url      = "https://pve-02.holthome.net:8006/api2/json"
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
    "pve-01.holthome.net",
    "pve-02.holthome.net",
    "pve-03.holthome.net",
  ]
  sshkeys      = <<EOF
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCeHXfsp4E0Wz2yY0oD5TcAVL35B9H36Vt64e3xIoSMg8K9IykmBJgbo6GizQEWyOx8SZOVAidRmHmtbZAKvaKovN45YKii7BjUOO/dWB3ELvt9o0ExCibzFReeajKaiIDOmjXeKFf4i8f01fFFC9a/SfM+jJK+8Ukd4LWrE8kgJriR/iR1P/fed01kmVF6+JzjmTC2mDcva8zkDCS21zssQG5Vap1U1yYa7UzZSlVHYJIlL29y/l3M9Wl/ABeT/iX4kWDIesvKFmhyeCehi6UBFtWzfQ216loCopXUGPUlTT0YidUEKkk5Zs1mz5kMhv21C48ATs3bkFnEAV2TF5ff ryan@RyMac.local
EOF
  gateway      = "10.20.0.1"
  vlanid       = "20"
  bridge       = "vmbr0"
  storage_size = "64G"
  storage_pool = "pve_rbd"
  storage_type = "raw"
  memory       = "8192"
  # storage_size2 = "500G"
  # storage_pool2 = "proxmox"
  # storage_type2 = "raw"
  # target_node  = "proxmox"
}
