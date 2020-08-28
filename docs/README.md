# Introduction

Shamelessly stolen a lot of this from https://github.com/billimek/k8s-gitops. Thank you for the inspiration!

# Security

- Helpful in setting up git to sign with gpg key: https://medium.com/@devmount/signed-git-commits-in-vs-code-476fb74b8773
- GPG Signing requires the following ~/.bashrc: `export GPG_TTY=$(tty)`

# Helpful Links

## General

Sort Events by TimeStamp: `kubectl get events --sort-by='{.lastTimestamp}'`

## Prometheus

Enabling monitoring via annotations: https://medium.com/@dmitrio_/installing-rook-v1-0-on-aks-f8c22a75d93d

## Rook CEPH

Access toolbox: `kubectl -n rook-ceph exec -it $(kubectl -n rook-ceph get pod -l "app=rook-ceph-tools" -o jsonpath='{.items[0].metadata.name}') bash`

Add to bash aliases (~/.bash_aliases): `alias toolbox='kubectl -n rook-ceph exec -it $(kubectl -n rook-ceph get pod -l "app=rook-ceph-tools" -o jsonpath='{.items[0].metadata.name}') bash'`

Decode admin password: `kubectl -n rook-ceph get secret rook-ceph-dashboard-password -o jsonpath="{['data']['password']}" | base64 --decode && echo`

## Fix Rook Ceph Dashboard

```
ceph dashboard ac-role-create admin-no-iscsi

for scope in dashboard-settings log rgw prometheus grafana nfs-ganesha manager hosts rbd-image config-opt rbd-mirroring cephfs user osd pool monitor; do
    ceph dashboard ac-role-add-scope-perms admin-no-iscsi ${scope} create delete read update;
done

ceph dashboard ac-user-set-roles admin admin-no-iscsi
```

## Creating the Base Template

qm create 9001 --memory 4096 --cores 4 --net0 virtio,bridge=vmbr0,tag=20
qm importdisk 9001 /root/ubuntu-18.10-server-cloudimg-amd64.img rbd
qm set 9001 --scsihw virtio-scsi-pci --scsi0 rbd:vm-9001-disk-0,ssd=1,discard=on
qm resize 9001 scsi0 32G
qm set 9001 --ide2 rbd:cloudinit
qm set 9001 --boot c --bootdisk scsi0
qm set 9001 --serial0 socket --vga serial0
qm set 9001 --ostype l26
qm set 9001 --agent enabled=1,fstrim_cloned_disks=1
qm template 9001

## Creating the RKE Template

qm clone 9001 9002 --name rke-template
qm set 9002 --sshkey /home/ryan/ryan_id_rsa.pub
qm set 9002 --ipconfig0 ip=10.20.20.20/16,gw=10.20.0.1

## Configuring the RKE Template

qm start 9002
ssh ubuntu@10.20.20.20

sudo apt-get install htop glances iotop zsh jq ceph-common gdisk iperf qemu-guest-agent nfs-common linux-image-extra-virtual docker.io
sudo usermod -aG docker ubuntu
sudo rm /etc/resolv.conf
sudo ln -s /run/systemd/resolve/resolv.conf /etc/resolv.conf
exit

qm shutdown 9002
qm template 9002

## Removing Disks from S2D for Passthrough

Identity all the disks and retire them:

```
Get-PhysicalDisk

Get-PhysicalDisk -SerialNumber S1E4NYAF801949 | set-physicaldisk -Usage Retired

$disks = Get-PhysicalDisk -Usage Retired
Set-ClusterS2DDisk -CanBeClaimed 0 -PhysicalDisk $Disks
```

## Setup Networking in Hyper-V Host

http://blog.mscloud.guru/2016/12/08/create-a-set-team-in-server-2016-howto/

## Add CEPH Storage to KVM

https://blog.modest-destiny.com/posts/kvm-libvirt-add-ceph-rbd-pool/

## Set application info on CephFS

Sometimes needed for CephFS. Likely to be fixed in future

```
ceph osd pool application set cephfs-metadata cephfs metadata cephfs
ceph osd pool application set cephfs-data0 cephfs data cephfs
```

## Enable Glances web service

https://github.com/nicolargo/glances/wiki/Start-Glances-through-Systemd

## GPG Configuration & GPT-Crypt setup

Looking to use this to encrypt the vault unlock key -- allows storage of everything needed by Ansible for deployment in the repository. Works quite well

- Generate GPG Keys: https://www.thesecuritybuddy.com/pgp-and-gpg/how-to-generate-gpg-key
- Backup GPG Keys: https://tunjos.co/blog/backup-your-gpg-key/
- Use Keys with Git-Crypt: https://wwsean08.com/2018/05/git-crypt/
- Setup pre-commit to ensure ansible-vault is encrypted before pushing to repo: https://www.pre-commit.com
- Use Ansible-Vault plugin from this guy to hook into pre-commit: https://git.iamthefij.com/iamthefij/ansible-pre-commit

## Integrate Vault auth with Keycloak

For exploration. https://devopstales.github.io/sso/hashicorp-sso/

## Storage Perf testing
https://thesanguy.com/2018/01/24/storage-performance-benchmarking-with-fio/
