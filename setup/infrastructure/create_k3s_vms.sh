#!/bin/bash

qm clone 9101 200 --name k3s-0
qm set 200 --sshkey ~/.ssh/id_rsa_rymac.pub
qm set 200 --ipconfig0 ip=10.20.30.10/16,gw=10.20.0.1
qemu-img resize -f rbd rbd:pve_rbd/vm-200-disk-0 60G
qm migrate 200 pve-01

qm clone 9101 201 --name k3s-1
qm set 201 --sshkey ~/.ssh/id_rsa_rymac.pub
qm set 201 --ipconfig0 ip=10.20.30.11/16,gw=10.20.0.1
qemu-img resize -f rbd rbd:pve_rbd/vm-201-disk-0 60G

qm clone 9101 202 --name k3s-2
qm set 202 --sshkey ~/.ssh/id_rsa_rymac.pub
qm set 202 --ipconfig0 ip=10.20.30.12/16,gw=10.20.0.1
qemu-img resize -f rbd rbd:pve_rbd/vm-202-disk-0 60G
qm migrate 202 pve-03