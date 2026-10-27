# Samsung SSD 870, 500GB class. Excludes the three 960GB OSD SSDs and any
# ~128GB disk. Serials are empty under Talos, so this does not match on serial.
# Known WWIDs are comments in topf.yaml.
apiVersion: v1alpha1
kind: UnattendedInstallConfig
installer:
  image: factory.talos.dev/metal-installer/{{ .SchematicID }}:{{ .TalosVersion }}
provisioning:
  diskSelector:
    match: disk.model.startsWith('Samsung SSD 870') && disk.size > 400u * GB && disk.size < 700u * GB
