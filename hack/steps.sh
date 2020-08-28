#!/usr/bin/env bash

# This script used to manually build manifests off of helm chart. Not in use currently

namespace="kube-system"
chart_name="nfs-server-provisioner"
chart_version="1.0.0"

helm fetch --repo https://kubernetes-charts.storage.googleapis.com/ --untar --untardir ./charts --version $chart_version $chart_name
helm template $chart_name --values ./values/$chart_name/values.yml --output-dir ./manifests/$namespace ./charts/$chart_name -n $namespace

mv ./manifests/$namespace/$chart_name/templates/* ./manifests/$namespace/$chart_name/.
rmdir ./manifests/$namespace/$chart_name/templates
