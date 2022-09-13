resource "vyos_config_block_tree" "service-dns-dynamic" {
  path = "service dns dynamic"

  configs = merge(
    merge([
      for domain in ["family", "personal", "ingress"] : {
        "interface bond0.4000 service ${domain} host-name" = "ipv4.${var.domains[domain]}"
        "interface bond0.4000 service ${domain} server"    = "api.cloudflare.com/client/v4"
        "interface bond0.4000 service ${domain} protocol"  = "cloudflare"
        "interface bond0.4000 service ${domain} zone"      = "${var.domains[domain]}"
        "interface bond0.4000 service ${domain} login"     = "${var.secrets.cloudflare.login}"
        "interface bond0.4000 service ${domain} password"  = "${var.secrets.cloudflare.key}"
      }
    ]...),
  )
}
