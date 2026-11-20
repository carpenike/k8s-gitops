{{- if .Node.Data.encryptDisk }}
# nodeID, not TPM. sled-1 dmesg on 27 Oct 2026: "No TPM chip found" /
# "TPM device is not available". These X10DRT-P boards have no AOM-TPM.
# The node id lives in the unencrypted META partition. Wiping META makes
# STATE and EPHEMERAL unreadable. Secure Boot stays off.
apiVersion: v1alpha1
kind: VolumeConfig
name: STATE
encryption:
  provider: luks2
  keys:
    - slot: 0
      nodeID: {}
---
apiVersion: v1alpha1
kind: VolumeConfig
name: EPHEMERAL
encryption:
  provider: luks2
  keys:
    - slot: 0
      nodeID: {}
{{- end }}
