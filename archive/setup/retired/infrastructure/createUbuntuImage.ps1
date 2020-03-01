# Download qemu-img from here: http://www.cloudbase.it/qemu-img-windows/
$qemuImgPath = "C:\users\ryan\bin\qemu-img\qemu-img.exe"

# Update this to the release of Ubuntu that you want
$ubuntuPath = "http://cloud-images.ubuntu.com/bionic/current/bionic-server-cloudimg-amd64"

$vmPath = "C:\users\ryan\scratch\VM"
$imageCachePath = "C:\users\ryan\scratch"
$vhdx = "$($vmPath)\k8s-template.vhdx"

# Get the timestamp of the latest build on the Ubuntu cloud-images site
$stamp = (Invoke-WebRequest "$($ubuntuPath).manifest").BaseResponse.LastModified.ToFileTimeUtc()

# Check Paths
if (!(test-path $vmPath)) {mkdir $vmPath}
if (!(test-path $imageCachePath)) {mkdir $imageCachePath}

# Helper function for no error file cleanup
Function cleanupFile ([string]$file) {if (test-path $file) {Remove-Item $file}}

# # Delete the VM if it is around
# If ((Get-VM | ? name -eq $VMName).Count -gt 0)
#       {stop-vm $VMName -TurnOff -Confirm:$false -Passthru | Remove-VM -Force}

cleanupFile $vhdx


if (!(test-path "$($imageCachePath)\ubuntu-$($stamp).img")) {
      # If we do not have a matching image - delete the old ones and download the new one
      Remove-Item "$($imageCachePath)\ubuntu-*.img"
      Invoke-WebRequest "$($ubuntuPath).img" -UseBasicParsing -OutFile "$($imageCachePath)\ubuntu-$($stamp).img"
}

# Convert cloud image to VHDX
& $qemuImgPath convert -f qcow2 "$($imageCachePath)\ubuntu-$($stamp).img" -O vhdx -o subformat=dynamic $vhdx
#Resize-VHD -Path $vhdx -SizeBytes 32GB

# # Create new virtual machine and start it
# new-vm $VMName -MemoryStartupBytes 2048mb -VHDPath $vhdx -Generation 1 `
#                -SwitchName $virtualSwitchName -Path $vmPath | Out-Null
# set-vm -Name $VMName -ProcessorCount 2
# Set-VMDvdDrive -VMName $VMName -Path $metaDataIso
# Start-VM $VMName

# # Open up VMConnect
# Invoke-Expression "vmconnect.exe localhost `"$VMName`""

# $VMName = "k8s-master-b"
# New-VM -Name $($VMName) -MemoryStartupBytes 1024mb -SwitchName "VMNetwork" -VHDPath "C:\ClusterStorage\disk0\$($VMName)\$($VMName).vhdx" -Path "C:\ClusterStorage\disk0" -Generation 1 -ComputerName HV02
# Set-VMDvdDrive -vmname $($VMName) -Path "C:\ClusterStorage\disk0\cloud-init\$($VMName)-cloudinit.iso" -ComputerName HV02
# Start-VM $VMName -ComputerName HV02
