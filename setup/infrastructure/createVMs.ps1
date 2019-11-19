# # Create VMs
# $VMs = Import-Csv -Path $PSScriptRoot\vmInventory.csv -Delimiter "|"
# $Remove = $true
# $Create = $false
# $destinationPath = "c:\clusterstorage\disk0"
# $vmHost = "HV02"
# $HVCluster = "hvclu"

# if ($Remove) {
#     foreach ($VM in $VMs) {
#         if ($(Get-ClusterGroup -Name $($VM.Name) -Cluster $HVCluster -ErrorAction SilentlyContinue) -or ($(Get-VM -Name ($VM.Name) -ComputerName $vmHost -ErrorAction SilentlyContinue))) {
#             Write-Host "$($VM.Name) Already Exists!"
#             Remove-ClusterGroup -VMId (Get-VM -Name $($VM.Name) -ComputerName $vmHost).vmid -RemoveResources -Cluster $HVCluster -Force -ErrorAction SilentlyContinue
#             Stop-Vm -Name $($VM.Name) -ComputerName $vmHost -Force
#             Remove-VM -Name $($VM.Name) -ComputerName $vmHost -Force
#         }
#         ELSE {
#             Write-Host "$($VM.Name) Does Not Exist"
#         }
#     }
# }

# if ($Create) {
#     foreach ($VM in $VMs) {
#         if (!$(Get-VM -Name $($VM.Name) -ComputerName $vmHost -ErrorAction SilentlyContinue)) {
#             Write-Host "Creating $($VM.Name)"
#             New-VM -Name $($VM.Name) -MemoryStartupBytes $($VM.Memory) -SwitchName $($VM.Network) -VHDPath "$($destinationPath)\$($VM.Name)\Virtual Hard Disks\$($VM.Name).vhdx" -Path $destinationPath -Generation $($VM.Generation) -ComputerName $vmHost
#             Set-VMDvdDrive -VMName $($VM.Name) -Path "$($destinationPath)\cloud-init\$($VM.Name)-cloudinit.iso" -ComputerName $vmHost
#             Set-VMNetworkAdapterVlan -VMName $($VM.Name) -Access -VlanId $($VM.VLAN) -ComputerName $vmHost
#             Set-VMMemory -VMName $($VM.Name) -DynamicMemoryEnabled $true -StartupBytes $($VM.Memory) -ComputerName $vmHost
#             Set-VM -Name $($VM.Name) -ProcessorCount ($VM.CPU) -ComputerName $vmHost
#             Start-VM -Name $($VM.Name) -ComputerName $vmHost
#             Add-ClusterVirtualMachineRole -VMName $($VM.Name) -Cluster $HVCluster #-ComputerName $vmHost
#         }
#     }
# }