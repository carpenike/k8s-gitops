#!/bin/sh

TEMPLATE=9002

#####################
## MASTER NODES
#####################
echo "#####################"
echo "## MASTER NODES"
echo "#####################"
qm clone "$TEMPLATE" 200 --name k8s-master-a
qm set 200 --sshkey /home/ryan/ryan_id_rsa.pub
qm set 200 --ipconfig0 ip=10.20.30.10/16,gw=10.20.0.1
qm set 200 --scsi1 /dev/disk/by-id/ata-SAMSUNG_MZ7WD960HMHP-00003_S1E4NYAG202916,discard=on,backup=0,ssd=1,replicate=0,serial=S1E4NYAG202916
qm set 200 --memory 12288

qm clone "$TEMPLATE" 201 --name k8s-master-b
qm set 201 --sshkey /home/ryan/ryan_id_rsa.pub
qm set 201 --ipconfig0 ip=10.20.30.11/16,gw=10.20.0.1
qm set 201 --memory 12288
qm migrate 201 pve-02

qm clone "$TEMPLATE" 202 --name k8s-master-c
qm set 202 --sshkey /home/ryan/ryan_id_rsa.pub 
qm set 202 --ipconfig0 ip=10.20.30.12/16,gw=10.20.0.1
qm set 202 --memory 12288
qm migrate 202 pve-03

qm start 200
ssh pve-02 'qm set 201 --scsi1 /dev/disk/by-id/ata-SAMSUNG_MZ7WD960HMHP-00003_S1E4NYAF801949,discard=on,backup=0,ssd=1,replicate=0,serial=S1E4NYAF801949 && qm start 201'
ssh pve-03 'qm set 202 --scsi1 /dev/disk/by-id/ata-SAMSUNG_MZ7WD960HMHP-00003_S1E4NYAG210767,discard=on,backup=0,ssd=1,replicate=0,serial=S1E4NYAG210767 && qm start 202'
#####################
## WORKER NODES
#####################
echo "#####################"
echo "## WORKER NODES"
echo "#####################"
qm clone "$TEMPLATE" 203 --name k8s-1
qm set 203 --sshkey /home/ryan/ryan_id_rsa.pub
qm set 203 --ipconfig0 ip=10.20.40.10/16,gw=10.20.0.1
qm set 203 --memory 32768

qm clone "$TEMPLATE" 204 --name k8s-2
qm set 204 --sshkey /home/ryan/ryan_id_rsa.pub
qm set 204 --ipconfig0 ip=10.20.40.11/16,gw=10.20.0.1
qm set 204 --memory 32768
qm migrate 204 pve-02

qm clone "$TEMPLATE" 205 --name k8s-3
qm set 205 --sshkey /home/ryan/ryan_id_rsa.pub
qm set 205 --ipconfig0 ip=10.20.40.12/16,gw=10.20.0.1
qm set 205 --memory 32768
qm migrate 205 pve-03

qm start 203
ssh pve-02 'qm start 204'
ssh pve-03 'qm start 205'