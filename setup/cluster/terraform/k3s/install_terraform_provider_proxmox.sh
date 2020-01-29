#!/bin/bash

if [[ "$OSTYPE" == "linux-gnu" ]]; then
  OS=linux
elif [[ "$OSTYPE" == "darwin"* ]]; then
  OS=darwin
fi

ARCH=amd64

go get github.com/Telmate/terraform-provider-proxmox/cmd/terraform-provider-proxmox
go get github.com/Telmate/terraform-provider-proxmox/cmd/terraform-provisioner-proxmox

mkdir -p ~/.terraform.d/plugins/${OS}_${ARCH}/
ln -sf "$GOPATH"/bin/terraform-provider-proxmox    ~/.terraform.d/plugins/${OS}_${ARCH}/
ln -sf "$GOPATH"/bin/terraform-provisioner-proxmox ~/.terraform.d/plugins/${OS}_${ARCH}/
