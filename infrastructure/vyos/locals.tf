locals {
  _config = yamldecode(
    templatefile(
      "settings.yaml",
      {
        address_book = local.address_book
        domains      = local.domains
        networks     = local.networks
        secrets      = yamldecode(nonsensitive(data.sops_file.vyos_secrets.raw))
      }
    )
  )

  domains        = yamldecode(nonsensitive(data.sops_external.domains.raw))
  networks       = yamldecode(chomp(data.http.carpenike_common_networks.response_body))
  address_book   = yamldecode(chomp(data.http.address_book.response_body))
  firewall_rules = yamldecode(file(pathexpand("${path.module}/firewall_rules.yaml")))

  config       = local._config.config
  vyos_secrets = sensitive(yamldecode(nonsensitive(data.sops_file.vyos_secrets.raw)))
}