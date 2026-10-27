apiVersion: v1alpha1
kind: UnattendedInstallConfig
provisioning:
  diskSelector:
    match: disk.dev_path == "{{ .Node.Data.installDisk }}" || "{{ .Node.Data.installDisk }}" in disk.symlinks
