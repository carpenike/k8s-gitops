#!/usr/bin/env bash

export REPO_ROOT
REPO_ROOT=$(git rev-parse --show-toplevel)

need() {
    which "$1" &>/dev/null || die "Binary '$1' is missing but required"
}

need "kubeseal"
need "kubectl"
need "sed"
need "envsubst"

if [ "$(uname)" == "Darwin" ]; then
  set -a
  . "${REPO_ROOT}/secrets/.secrets.env"
  set +a
else
  . "${REPO_ROOT}/secrets/.secrets.env"
fi

PUB_CERT="${REPO_ROOT}/secrets/pub-cert.pem"

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
  envsubst < "$@" | tee values.yaml \
    | \
  kubectl -n "${namespace}" create secret generic "${secret_name}" \
    --from-file=values.yaml --dry-run -o json \
    | \
  kubeseal --format=yaml --cert="$PUB_CERT" \
    > "${secret}.yaml"
  # Clean up temp file
  rm values.yaml
}

#
# Helm Secrets
#

kseal "${REPO_ROOT}/cluster/default/minio/minio-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/nzbget/nzbget-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/nzbhydra/nzbhydra-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/bitwarden/bitwarden-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/bazarr/bazarr-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/dashmachine/dashmachine-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/unifi/unifi-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/ombi/ombi-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/tautulli/tautulli-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/jackett/jackett-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/radarr/radarr-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/sonarr/sonarr-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/qbittorrent/qbittorrent-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/plex/plex-helm-values.txt"
kseal "${REPO_ROOT}/cluster/default/bookstack/bookstack-mariadb-helm-values.txt"
kseal "${REPO_ROOT}/cluster/monitoring/prometheus-operator/prometheus-operator-helm-values.txt"

#
# Generic Secrets
#

# Vault Auto Unlock - kube-system namespace
kubectl create secret generic kms-vault \
 --from-literal=config.hcl="$(envsubst < "$REPO_ROOT"/cluster/kube-system/vault/kms-config.txt)" \
 --namespace kube-system --dry-run -o json \
 | \
 kubeseal --format=yaml --cert="$PUB_CERT" \
    > "$REPO_ROOT"/cluster/kube-system/vault/vault-kms-config.yaml


# AzureDNS - cert-manager namespace
kubectl create secret generic azuredns-config  \
 --from-literal=client-secret="$AZURE_CERTBOT_CLIENT_SECRET" \
 --namespace cert-manager --dry-run -o json \
 | \
kubeseal --format=yaml --cert="$PUB_CERT" \
   > "$REPO_ROOT"/cluster/cert-manager/azuredns/azuredns-config.yaml

# Restic Password for Stash - default namespace
kubectl create secret generic restic-backup-credentials  \
 --from-literal=RESTIC_PASSWORD=$RESTIC_PASSWORD \
 --from-literal=AWS_ACCESS_KEY_ID=$MINIO_ACCESS_KEY \
 --from-literal=AWS_SECRET_ACCESS_KEY=$MINIO_SECRET_KEY \
 --namespace default --dry-run -o json \
 | \
kubeseal --format=yaml --cert="$PUB_CERT" \
   > "$REPO_ROOT"/cluster/stash/stash/restic-backup-credentials.yaml

# NginX Basic Auth - default namespace
#kubectl create secret generic nginx-basic-auth \
#  --from-literal=auth="$NGINX_BASIC_AUTH" \
#  --namespace default --dry-run -o json \
#  | \
#kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/kube-system/nginx-ingress/basic-auth-default.yaml

# NginX Basic Auth - kube-system namespace
#kubectl create secret generic nginx-basic-auth \
#  --from-literal=auth="$NGINX_BASIC_AUTH" \
#  --namespace kube-system --dry-run -o json \
#  | \
#kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/kube-system/nginx-ingress/basic-auth-kube-system.yaml

# NginX Basic Auth - monitoring namespace
#kubectl create secret generic nginx-basic-auth \
#  --from-literal=auth="$NGINX_BASIC_AUTH" \
#  --namespace monitoring --dry-run -o json \
#  | \
#kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/kube-system/nginx-ingress/basic-auth-monitoring.yaml

# Cloudflare API Key - cert-manager namespace
#kubectl create secret generic cloudflare-api-key \
#  --from-literal=api-key="$CF_API_KEY" \
#  --namespace cert-manager --dry-run -o json \
#  | \
#kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/cert-manager/cloudflare/cloudflare-api-key.yaml

# qBittorrent Prune - default namespace
#kubectl create secret generic qbittorrent-prune \
#  --from-literal=username="$QB_USERNAME" \
#  --from-literal=password="$QB_PASSWORD" \
#  --namespace default --dry-run -o json \
#  | kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/default/qbittorrent-prune/qbittorrent-prune-values.yaml

# sonarr episode prune - default namespace
#kubectl create secret generic sonarr-episode-prune \
#  --from-literal=api-key="$SONARR_APIKEY" \
#  --namespace default --dry-run -o json \
#  | kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/default/sonarr-episode-prune/sonarr-episode-prune-values.yaml

# sonarr exporter
#kubectl create secret generic sonarr-exporter \
#  --from-literal=api-key="$SONARR_APIKEY" \
#  --namespace monitoring --dry-run -o json \
#  | kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/monitoring/sonarr-exporter/sonarr-exporter-values.yaml

# radarr exporter
#kubectl create secret generic radarr-exporter \
#  --from-literal=api-key="$RADARR_APIKEY" \
#  --namespace monitoring --dry-run -o json \
#  | kubeseal --format=yaml --cert="$PUB_CERT" \
#    > "$REPO_ROOT"/deployments/monitoring/radarr-exporter/radarr-exporter-values.yaml
