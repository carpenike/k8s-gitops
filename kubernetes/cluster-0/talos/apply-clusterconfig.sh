#!/usr/bin/env bash

# Deploy the configuration to the nodes
/opt/homebrew/bin/talosctl apply-config -n cp-0.holthome.net -f ./clusterconfig/cluster-0-cp-0.holthome.net.yaml
/opt/homebrew/bin/talosctl apply-config -n node-0.holthome.net -f ./clusterconfig/cluster-0-node-0.holthome.net.yaml
/opt/homebrew/bin/talosctl apply-config -n node-1.holthome.net -f ./clusterconfig/cluster-0-node-1.holthome.net.yaml
/opt/homebrew/bin/talosctl apply-config -n node-2.holthome.net -f ./clusterconfig/cluster-0-node-2.holthome.net.yaml
/opt/homebrew/bin/talosctl apply-config -n node-3.holthome.net -f ./clusterconfig/cluster-0-node-3.holthome.net.yaml
