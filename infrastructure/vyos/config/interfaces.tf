resource "vyos_config_block_tree" "interface-wan" {
  path = "interfaces bonding ${var.config.zones.wan.interface}"
  configs = {
    "hw-id"       = "00:01:c0:21:33:f2"

    "vif 4000 description" = "WAN"
    "vif 4000 address"     = "dhcp"
  }
}

resource "vyos_config_block_tree" "interface-mgmt" {
  path = "interfaces bonding ${var.config.zones.mgmt.interface}"
  configs = {
    "address"     = "${cidrhost(var.networks.mgmt, 1)}/16"
    "description" = "MGMT"
    "hw-id"       = "00:01:c0:21:33:f2"

    "vif 5 description" = "RESCUE"
    "vif 5 address"     = "${cidrhost(var.networks.rescue, 1)}/16"
    "vif 10 description" = "WIRED"
    "vif 10 address"     = "${cidrhost(var.networks.wired, 1)}/16"
    "vif 20 description" = "SERVERS"
    "vif 20 address"     = "${cidrhost(var.networks.servers, 1)}/16"
    "vif 30 description" = "WIRELESS"
    "vif 30 address"     = "${cidrhost(var.networks.wireless, 1)}/16"
    "vif 35 description" = "GUEST"
    "vif 35 address"     = "${cidrhost(var.networks.guest, 1)}/16"
    "vif 40 description" = "IOT"
    "vif 40 address"     = "${cidrhost(var.networks.iot, 1)}/16"
    "vif 50 description" = "VIDEO"
    "vif 50 address"     = "${cidrhost(var.networks.video, 1)}/16"

  }
}
