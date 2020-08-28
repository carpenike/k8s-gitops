#!/usr/bin/env bash
#
# Fetch secrets for local development from Azure KeyVault
# and print them to stdout as a bunch of env var exports.
# These secrets should be added to your local .env file
# to enable running integration tests locally.
#
# Source KeyVault Credentials
source ./keyvault.env
# Login to KeyVault
az login --service-principal -u $APPID -p $SECRETKEY --tenant $TENANTID --allow-no-subscriptions &>/dev/null

function fetch_secret_from_keyvault() {
    local SECRET_NAME=$1

    az keyvault secret show --vault-name "${KEY_VAULT}" --name "${SECRET_NAME}" --query "value"
}

function store_secret_from_keyvault() {
    local SECRET_VAR=$1
    local SECRET_NAME=$2

    local SECRET_VALUE=`fetch_secret_from_keyvault "${SECRET_NAME}"`
    store_secret "${SECRET_VAR}" "${SECRET_VALUE}"
}

function store_secret() {
    local SECRET_VAR=$1
    local SECRET_VALUE=$2

    echo "export ${SECRET_VAR}=${SECRET_VALUE}"
}

echo "# ----------------------- "
echo "# Fetched the following secrets from ${KEY_VAULT} on "`date`

store_secret_from_keyvault "DOMAIN" "DOMAIN"

echo "# End of fetched secrets. "
echo "# ----------------------- "
