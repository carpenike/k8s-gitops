# Helpful Links

## General

Sort Events by TimeStamp: `kubectl get events --sort-by='{.lastTimestamp}'`

## Prometheus

Enabling monitoring via annotations: https://medium.com/@dmitrio_/installing-rook-v1-0-on-aks-f8c22a75d93d

## Rook CEPH

Access toolbox: `kubectl -n rook-ceph exec -it $(kubectl -n rook-ceph get pod -l "app=rook-ceph-tools" -o jsonpath='{.items[0].metadata.name}') bash`

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
