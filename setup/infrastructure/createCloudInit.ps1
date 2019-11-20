# Helper function for no error file cleanup
Function cleanupFile ([string]$file) {
  if (test-path $file) {Remove-Item $file}
}

$tempPath = [System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid().ToString()
$VMs = Import-Csv -Path $PSScriptRoot\vmInventory.csv -Delimiter "|"
$oscdimgPath = "C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
$vmPath = "C:\users\ryan\scratch\VM"
$imageCachePath = "C:\users\ryan\scratch"
$destinationPath = "\\hv01.ad.holthome.net\c$\ClusterStorage\VD-VM-01"

foreach ($VM in $VMs) {
  $cloudInitISO = "$($vmPath)\$($VM.Name)-cloudinit.iso"
  $metadata = @"
    instance-id: $($VM.GuestOSID)
    local-hostname: $($VM.Name)
"@
  
  $userdata = @"
    #cloud-config
    runcmd:
      - usermod -aG docker ubuntu
      - rm /etc/resolv.conf
      - ln -s /run/systemd/resolve/resolv.conf /etc/resolv.conf
      - systemctl start docker
      - systemctl enable docker
    ssh_import_id: gh:carpenike
    packages:
      - htop
      - glances
      - iotop
      - zsh
      - jq
      - ceph-common
      - nethogs
      - iperf
      - nfs-common
    package_upgrade: true
"@
  
  $netdata = @"
  version: 2
  ethernets:
    eth0:
      addresses:
      - $($VM.IPADDRESS)
      gateway4: $($VM.GATEWAY)
      nameservers:
        search: [$($VM.DNSNAMESEARCH)]
        addresses: [$($VM.DNSSERVERS)]
"@

  # Check Paths
  if (!(test-path $vmPath)) {mkdir $vmPath}
  if (!(test-path $imageCachePath)) {mkdir $imageCachePath}

  # Remove any leftover Cloud-Init ISO
  cleanupFile $cloudInitISO
  # Make temp location
  md -Path $tempPath
  md -Path "$($tempPath)\Bits"

  # Output meta and user data to files
  sc "$($tempPath)\Bits\meta-data" ([byte[]][char[]] "$metadata") -Encoding Byte
  sc "$($tempPath)\Bits\user-data" ([byte[]][char[]] "$userdata") -Encoding Byte
  sc "$($tempPath)\Bits\network-config" ([byte[]][char[]] "$netdata") -Encoding Byte


  # Create meta data ISO image
  & $oscdimgPath "$($tempPath)\Bits" $cloudInitISO -j2 -lcidata

  if (!(Test-Path "$($destinationPath)\cloud-init")) {
    Write-Host "Destination folder not present, creating"
    New-Item -ItemType Directory "$($destinationPath)\cloud-init"
  }

  Move-Item -Path $cloudInitISO -Destination "$($destinationPath)\cloud-init" -Force
  # Clean up temp directory
  rd -Path $tempPath -Recurse -Force
  
}