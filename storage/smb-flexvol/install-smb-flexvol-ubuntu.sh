#!/bin/sh
VER="1.0.0"

echo "install jq,cifs-utils packages ..."
apt update
apt-get install jq cifs-utils -y

echo "install smb flexvolume driver ..."
PLUGIN_DIR=/var/lib/kubelet/plugins/microsoft.com~smb
mkdir -p $PLUGIN_DIR
wget -O $PLUGIN_DIR/smb https://raw.githubusercontent.com/Azure/kubernetes-volume-drivers/master/flexvolume/smb/deployment/smb-flexvol-installer/smb
chmod a+x $PLUGIN_DIR/smb

echo "install complete."
