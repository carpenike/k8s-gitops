#!/usr/bin/env bash

export REPO_ROOT
REPO_ROOT=$(git rev-parse --show-toplevel)

need() {
    which "$1" &>/dev/null || die "Binary '$1' is missing but required"
}

need "kubectl"
need "sed"
need "envsubst"
need "az"

if [ "$(uname)" == "Darwin" ]; then
  set -a
  . "${REPO_ROOT}/secrets/.secrets.env"
  set +a
else
  . "${REPO_ROOT}/secrets/.secrets.env"
fi

# Login to Azure
az login --service-principal --username "$AZURE_KEYVAULT_CLIENT_ID" --password "$AZURE_KEYVAULT_CLIENT_SECRET" --tenant "$AZURE_KEYVAULT_TENANT_ID"

# Helper function to generate secrets
kseal() {
  echo "------------------------------------"
  # Get the path and basename of the txt file
  # e.g. "deployments/default/pihole/pihole-helm-values"
  secret="$(dirname "$@")/$(basename -s .txt "$@")"
  echo "Secret: ${secret}"
  # Get the filename without extension
  # e.g. "pihole-helm-values"
  secret_name=$(basename "${secret}")
  echo "Secret Name: ${secret_name}"
  # Extract the Kubernetes namespace from the secret path
  # e.g. default
  namespace="$(echo "${secret}" | awk -F /cluster/ '{ print $2; }' | awk -F / '{ print $1; }')"
  echo "Namespace: ${namespace}"
  # Create secret and put it in the applications deployment folder
  # e.g. "deployments/default/pihole/pihole-helm-values.yaml"
  envsubst < "$@" | tee values.yaml > /dev/null
  az keyvault secret set --name "${secret_name}" --vault-name holthome --file values.yaml > /dev/null
  # Clean up temp file
  rm values.yaml
}

#
# Objects
#

# HASS External
#envsubst < "${REPO_ROOT}/cluster/kube-system/nginx/nginx-external/external_ha.txt" | kubectl apply -f -

#
# Helm Secrets
#

#kseal "${REPO_ROOT}/cluster/default/minio/minio-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/blocky/blocky-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/nzbget/nzbget-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/nzbhydra/nzbhydra-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/bitwarden/bitwarden-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/gitea/gitea-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/bazarr/bazarr-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/dashmachine/dashmachine-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/default/unifi/unifi-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/default/ombi/ombi-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/tautulli/tautulli-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/jackett/jackett-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/radarr/radarr-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/sonarr/sonarr-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/qbittorrent/qbittorrent-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/default/plex/plex-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/default/jellyfin/jellyfin-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/bookstack/bookstack-mariadb-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/bookstack/bookstack-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/default/grocy/grocy-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/powerdns/powerdns-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/samba/samba-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/home-assistant/home-assistant-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/monica/monica-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/searx/searx-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/matrix/matrix-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/teedy/teedy-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/default/powerdns/powerdns-mariadb-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/default/powerdns/powerdns-admin-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/node-red/node-red-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/goldilocks/goldilocks-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/edms/edms-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/default/nextcloud/nextcloud-helm-values.txt"
kseal "${REPO_ROOT}/cluster/monitoring/kube-prometheus-stack/kube-prometheus-stack-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/monitoring/uptimerobot/uptimerobot-helm-values.txt"
kseal "${REPO_ROOT}/cluster/monitoring/thanos/thanos-helm-values.txt"
kseal "${REPO_ROOT}/cluster/monitoring/botkube/botkube-helm-values.txt"
kseal "${REPO_ROOT}/cluster/logs/loki/loki-helm-values.txt"
kseal "${REPO_ROOT}/cluster/kube-system/pomerium/pomerium-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/kube-system/azure-keyvault-injector/azure-keyvault-controller-helm-values.txt"
kseal "${REPO_ROOT}/cluster/kube-system/dex/dex-helm-values.txt"
kseal "${REPO_ROOT}/cluster/kube-system/dex/dex-k8s-authenticator-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/kube-system/registry-creds/dockerhub-secret.txt"
# # kseal "${REPO_ROOT}/cluster/kube-system/keycloak/keycloak-helm-values.txt"
# # kseal "${REPO_ROOT}/cluster/kube-system/external-dns/external-dns-helm-values.txt"
kseal "${REPO_ROOT}/cluster/kube-system/oauth2-proxy/oauth2-proxy-helm-values.txt"
kseal "${REPO_ROOT}/cluster/kube-system/democratic-csi/democratic-csi-helm-values.txt"
kseal "${REPO_ROOT}/cluster/kasten/k10/k10-helm-values.txt"
kseal "${REPO_ROOT}/cluster/security/hydra/hydra-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/kube-system/version-checker/version-checker-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/actions-runner-system/actions-runner-controller/dex-helm-values.txt"
# kseal "${REPO_ROOT}/cluster/velero/velero/velero-helm-values.txt"

#
# Generic Secrets
#

# # Vault Auto Unlock - kube-system namespace
# kubectl create secret generic kms-vault \
#  --from-literal=config.hcl="$(envsubst < "$REPO_ROOT"/cluster/kube-system/vault/kms-config.txt)" \
#  --namespace kube-system --dry-run=true -o json \
#  | \
#  kubeseal --format=yaml --cert="$PUB_CERT" \
#     > "$REPO_ROOT"/cluster/kube-system/vault/vault-kms-config.yaml


# AzureDNS - cert-manager namespace
# kubectl create secret generic azuredns-config  \
#  --from-literal=client-secret="$AZURE_CERTBOT_CLIENT_SECRET" \
#  --namespace cert-manager --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/cert-manager/azuredns/azuredns-config.yaml
az keyvault secret set --name "certbot-client-secret" --vault-name holthome --value $AZURE_CERTBOT_CLIENT_SECRET

# # Longhorn Backup - longhorn-system namespace
# kubectl create secret generic longhorn-backup-secret  \
#  --from-literal=AWS_ACCESS_KEY_ID=$MINIO_ACCESS_KEY \
#  --from-literal=AWS_SECRET_ACCESS_KEY=$MINIO_SECRET_KEY \
#  --from-literal=AWS_ENDPOINTS=http://minio.default:9000 \
#  --namespace longhorn-system --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/longhorn-system/longhorn/longhorn-backup-secret.yaml

az keyvault secret set --name "minio-accesskey" --vault-name holthome --value $MINIO_ACCESS_KEY
az keyvault secret set --name "minio-secretkey" --vault-name holthome --value $MINIO_SECRET_KEY
az keyvault secret set --name "minio-endpoint" --vault-name holthome --value https://nas.${SECRET_DOMAIN}:9000


# # Authelia Secrets - kube-system namespace
# kubectl create secret generic authelia-secrets \
#  --from-literal=jwt=$AUTHELIA_JWT \
#  --from-literal=session=$AUTHELIA_SESSION \
#  --namespace kube-system --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/kube-system/authelia/authelia-secrets.yaml

# # Authelia Users - kube-system namespace
# kubectl create secret generic authelia-users  \
#  --from-literal=users.yaml="$(envsubst < "$REPO_ROOT"/cluster/kube-system/authelia/authelia-users.txt)" \
#  --namespace kube-system --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/kube-system/authelia/authelia-users.yaml

# # Actions-Runner-system GH Creds - actions-runner-system namespace
# kubectl create secret generic controller-manager  \
#  --from-literal=github_app_id=$ACTIONS_RUNNER_CONTROLLER_GITHUB_APP_ID \
#  --from-literal=github_app_installation_id=$ACTIONS_RUNNER_CONTROLLER_GITHUB_APP_INSTALLATION_ID \
#  --from-literal=github_app_private_key="$(echo $ACTIONS_RUNNER_CONTROLLER_GITHUB_PRIVATE_KEY | base64 -d)" \
#  --namespace actions-runner-system --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/actions-runner-system/actions-runner-controller/actions-system-runner-gh-creds.yaml

az keyvault secret set --name "actions-runner-gh-app-id" --vault-name holthome --value $ACTIONS_RUNNER_CONTROLLER_GITHUB_APP_ID
az keyvault secret set --name "actions-runner-gh-app-installation-id" --vault-name holthome --value $ACTIONS_RUNNER_CONTROLLER_GITHUB_APP_INSTALLATION_ID
az keyvault secret set --name "actions-runner-gh-app-private-key" --vault-name holthome --value "$(echo $ACTIONS_RUNNER_CONTROLLER_GITHUB_PRIVATE_KEY | base64 -d)"

# # Alertmanager-Bot - monitoring namespace
# kubectl create secret generic alertmanager-bot  \
#  --from-literal=admin=$TELEGRAM_USER_ID \
#  --from-literal=token=$TELEGRAM_AM_BOT_TOKEN \
#  --namespace monitoring --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/monitoring/alertmanager-bot/alertmanager-telegram-creds.yaml

az keyvault secret set --name "alertmanager-bot-admin" --vault-name holthome --value $TELEGRAM_USER_ID
az keyvault secret set --name "alertmanager-bot-token" --vault-name holthome --value $TELEGRAM_AM_BOT_TOKEN
az keyvault secret set --name "flux-discord-address" --vault-name holthome --value $FLUX_DISCORD_ADDRESS

## Dockerhub
# az keyvault secret set --name "dockerhub-username" --vault-name holthome --value $DOCKER_USERNAME
# az keyvault secret set --name "dockerhub-password" --vault-name holthome --value $DOCKER_TOKEN
# az keyvault secret set --name "dockerhub-email" --vault-name holthome --value $EMAIL

# # Restic Password for Stash - default namespace
# # kubectl create secret generic restic-backup-credentials  \
# #  --from-literal=RESTIC_PASSWORD=$RESTIC_PASSWORD \
# #  --from-literal=AWS_ACCESS_KEY_ID=$MINIO_ACCESS_KEY \
# #  --from-literal=AWS_SECRET_ACCESS_KEY=$MINIO_SECRET_KEY \
# #  --namespace default --dry-run=true -o json \
# #  | \j
# # kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/cluster/stash/stash/restic-backup-credentials.yaml

# # # Keycloak Realm - kube-system namespace
# # kubectl create secret generic keycloak-realm  \
# #  --from-literal=realm.json="$(envsubst < "$REPO_ROOT"/cluster/kube-system/keycloak/keycloak-realm.txt)" \
# #  --namespace kube-system --dry-run=true -o json \
# #  | \
# # kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/cluster/kube-system/keycloak/keycloak-realm.yaml

# # # Keycloak admin password - kube-system namespace
# # kubectl create secret generic keycloak-password  \
# #  --from-literal=password="$KEYCLOAK_PASSWORD" \
# #  --namespace kube-system --dry-run=true -o json \
# #  | \
# # kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/cluster/kube-system/keycloak/keycloak-password.yaml


# # External-DNS PowerDNS API Key - kube-system namespace
# kubectl create secret generic powerdns-api-key  \
#  --from-literal=pdns_api_key=$PDNS_API_KEY \
#  --namespace kube-system --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/kube-system/external-dns/powerdns-api-key.yaml

# #NginX Basic Auth - default namespace
# kubectl create secret generic nginx-basic-auth \
#  --from-literal=auth="$NGINX_BASIC_AUTH" \
#  --namespace default --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/kube-system/nginx/basic-auth-default.yaml

# # NginX Basic Auth - kube-system namespace
# kubectl create secret generic nginx-basic-auth \
#  --from-literal=auth="$NGINX_BASIC_AUTH" \
#  --namespace kube-system --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/kube-system/nginx/basic-auth-kube-system.yaml

# # NginX Basic Auth - monitoring namespace
# kubectl create secret generic nginx-basic-auth \
#  --from-literal=auth="$NGINX_BASIC_AUTH" \
#  --namespace monitoring --dry-run=true -o json \
#  | \
# kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/cluster/kube-system/nginx/basic-auth-monitoring.yaml

# # Cloudflare API Key - cert-manager namespace
# #kubectl create secret generic cloudflare-api-key \
# #  --from-literal=api-key="$CF_API_KEY" \
# #  --namespace cert-manager --dry-run=client -o json \
# #  | \
# #kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/deployments/cert-manager/cloudflare/cloudflare-api-key.yaml

# # qBittorrent Prune - default namespace
# #kubectl create secret generic qbittorrent-prune \
# #  --from-literal=username="$QB_USERNAME" \
# #  --from-literal=password="$QB_PASSWORD" \
# #  --namespace default --dry-run=client -o json \
# #  | kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/deployments/default/qbittorrent-prune/qbittorrent-prune-values.yaml

# # sonarr episode prune - default namespace
# #kubectl create secret generic sonarr-episode-prune \
# #  --from-literal=api-key="$SONARR_APIKEY" \
# #  --namespace default --dry-run=client -o json \
# #  | kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/deployments/default/sonarr-episode-prune/sonarr-episode-prune-values.yaml

# # sonarr exporter
# #kubectl create secret generic sonarr-exporter \
# #  --from-literal=api-key="$SONARR_APIKEY" \
# #  --namespace monitoring --dry-run=client -o json \
# #  | kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/deployments/monitoring/sonarr-exporter/sonarr-exporter-values.yaml

# # radarr exporter
# #kubectl create secret generic radarr-exporter \
# #  --from-literal=api-key="$RADARR_APIKEY" \
# #  --namespace monitoring --dry-run=client -o json \
# #  | kubeseal --format=yaml --cert="$PUB_CERT" \
# #    > "$REPO_ROOT"/deployments/monitoring/radarr-exporter/radarr-exporter-values.yaml


# KUBE Secrets
## Registry Creds
kubectl delete -n kube-system secret registry-creds-secret
kubectl create -n kube-system secret docker-registry registry-creds-secret --namespace kube-system --docker-username=$DOCKER_USERNAME --docker-password=$DOCKER_TOKEN --docker-email=$EMAIL

# Flux Github Webhook
kubectl delete -n flux-system secret webhook-token
kubectl create -n flux-system secret generic webhook-token --from-literal=token=$FLUX_GITHUB_WEBHOOK_TOKEN
