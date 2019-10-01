# Distribute Files to HV Host
$vmPath = "C:\users\ryan\scratch\VM"
$vhdx = "$($vmPath)\k8s-template.vhdx"
$destinationPath = "\\hv01.ad.holthome.net\c$\clusterstorage\VD-VM-01"
$clean = $false
$vmHost = "HV01"

$VMs = Import-Csv -Path $PSScriptRoot\vmInventory.csv -Delimiter "|"

if ($vhdx) {
    Write-Host "Copying the template to HV"
    Copy-Item $vhdx "$destinationPath\k8s-template.vhdx"
    $vhdx = "$destinationPath\k8s-template.vhdx"
    Resize-VHD -Path "C:\ClusterStorage\VD-VM-01\k8s-template.vhdx" -SizeBytes 34359738368 -ComputerName $vmHost
    foreach ($VM in $VMs) {
        #Check for presence of VHD file
        IF (!$(Get-Item "$destinationPath\$($VM.Name)\Virtual Hard Disks\$($VM.Name).vhdx" -ErrorAction SilentlyContinue) -and $(!$clean)) {
            Write-Host "$($VM.Name) doesn't have any VHD files!"
            New-Item -ItemType Directory "$destinationPath\$($VM.Name)\Virtual Hard Disks" -ErrorAction SilentlyContinue
            Copy-Item -Path $vhdx -Destination "$destinationPath\$($VM.Name)\Virtual Hard Disks\$($VM.Name).vhdx"
        }
        ELSE {
            Write-Host "$($VM.Name) Already Exists"
            if ($clean) {
                Write-Host "Clean parameter set. Removing VHD Files."
                Remove-Item -Path "$destinationPath\$($VM.Name)\Virtual Hard Disks\$($VM.Name).vhdx" -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Write-Host "Removing Template file from HV"
    Remove-Item $vhdx
}