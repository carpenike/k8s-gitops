terraform {
  cloud {
    organization = "BigHead-Ltd"
    workspaces {
      name = "home-vyos-provisioner"
    }
  }

  required_providers {
    vyos = {
      source  = "TGNThump/vyos"
      version = "2.1.0"
    }
    sops = {
      source  = "carlpett/sops"
      version = "1.1.1"
    }
    remote = {
      source  = "tenstad/remote"
      version = "0.1.2"
    }
    http = {
      source  = "hashicorp/http"
      version = "3.4.2"
    }
  }
}

data "sops_file" "vyos_secrets" {
  source_file = "secret.sops.yaml"
}

data "http" "carpenike_common_domains" {
  url = "https://raw.githubusercontent.com/carpenike/k8s-gitops/main/infrastructure/_shared/domains.sops.yaml"
}

data "sops_external" "domains" {
  source     = data.http.carpenike_common_domains.response_body
  input_type = "yaml"
}

data "http" "address_book" {
  url = "https://raw.githubusercontent.com/carpenike/k8s-gitops/main/infrastructure/_shared/address_book.yaml"
}

data "http" "carpenike_common_networks" {
  url = "https://raw.githubusercontent.com/carpenike/k8s-gitops/main/infrastructure/_shared/networks.yaml"
}

module "config" {
  source = "./modules/config"

  config         = local.config
  networks       = local.networks
  domains        = local.domains
  address_book   = local.address_book
  firewall_rules = local.firewall_rules
  secrets        = local.vyos_secrets

  providers = {
    vyos   = vyos.vyos
    remote = remote.vyos
  }
}
