resource "proxmox_vm_qemu" "generic-vm" {
  count = "${length(var.ips)}"

  name = "${var.name_prefix}-${count.index}"
  desc = "generic terraform-created vm"

  target_node = "${var.nodes[count.index]}"

  # target_node = "${var.target_node}"

  clone    = "disco-server-cloudimg-amd64"
  cores    = "${var.cores}"
  sockets  = 1
  memory   = "${var.memory}"
  agent    = 1
  bootdisk = "scsi0"
  scsihw   = "virtio-scsi-pci"
  disk {
    id           = 0
    type         = "scsi"
    storage      = "${var.storage_pool}"
    size         = "${var.storage_size}"
    storage_type = "${var.storage_type}"
  }
#  disk {
#    id           = 1
#    type         = "scsi"
#    storage      = "${var.storage_pool2}"
#    size         = "${var.storage_size2}"
#    storage_type = "${var.storage_type2}"
#  }
  network {
    id      = 0
    model   = "virtio"
    bridge  = "${var.bridge}"
    tag     = "${var.vlanid}"
    macaddr = "${var.macs[count.index]}"
  }
  # network {
  #   id     = 1
  #   model  = "virtio"
  #   bridge = "${var.bridge1}"
  #   tag    = "${var.vlanid1}"
  # }
  ssh_user = "${var.ssh_user}"
  os_type   = "cloud-init"
  ipconfig0 = "ip=dhcp"
  sshkeys = "${var.sshkeys}"
}
