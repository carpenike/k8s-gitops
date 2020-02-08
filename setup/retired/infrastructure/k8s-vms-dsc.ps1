configuration k8s-vms
{
    param
    (
        [string[]]$NodeName = 'localhost',

        [Parameter(Mandatory)]
        [string]$VMName,

        [Parameter(Mandatory)]
        [string]$Generation,
        
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$CPU,

        [Parameter(Mandatory)]
        [string]$SwitchName,

        [Parameter(Mandatory)]
        [string]$Ensure,

        [Parameter(Mandatory)]
        [int]$VLANID,

        [Parameter(Mandatory)]
        [Uint64]$Memory
    )

    Import-DscResource -module xHyper-V
    Import-DscResource -module cHyper-V -Name cVMNetworkAdapterVlan

    Node $NodeName
    {
        # Install HyperV feature, if not installed - Server SKU only
        WindowsFeature HyperV
        {
            Ensure = 'Present'
            Name   = 'Hyper-V'
        }
        WindowsFeature HyperVPowerShell
        {
            Ensure = 'Present'
            Name   = 'Hyper-V-PowerShell'
            Dependson = '[WindowsFeature]HyperV'
        }

        xVHD k8s-vm-disk
        {
            Ensure = $Ensure
            Name = $VMName
            Generation = "vhdx"
            Path = Join-Path $Path -ChildPath "$($VMName)\Virtual Hard Disks\"
            MaximumSizeBytes = 34359738368
        }

        # Ensures a VM with dynamic memory
        xVMHyperV K8s-VMS
        {
            Ensure        = $Ensure
            Name          = $VMName
            Path          = $Path
            VhdPath       = Join-Path $Path -ChildPath "$($VMName)\Virtual Hard Disks\$($VMName).vhdx"
            Switchname    = $SwitchName
            ProcessorCount =  $CPU
            Generation    = $Generation
            State   = 'Off'
            StartupMemory = $Memory
            DependsOn     = '[WindowsFeature]HyperVPowerShell', '[xVHD]k8s-vm-disk'
        }
        xVMDvdDrive K8S-VMS-DVD
        {
            Ensure = $Ensure
            VMName = $VMName
            ControllerNumber = 1
            ControllerLocation = 0
            Path = Join-Path $Path -ChildPath "cloud-init\$($VMName)-cloudinit.iso"
            DependsOn = '[xVMHyperV]K8s-VMS'
        }
        cVMNetworkAdapterVlan k8s-vlan {
            Id = $VMName
            Name = "Network Adapter"
            VMName = $VMName
            AdapterMode = 'Access'
            VlanId = $VLANID
            DependsOn = '[xVMHyperV]K8s-VMS'
         }
    }
}

$VMs = Import-Csv -Path $PSScriptRoot\vmInventory.csv -Delimiter "|"

foreach ($VM in $VMS) {
    k8s-vms -NodeName HV02 -VMName $($VM.Name) -Memory $($VM.Memory) -Ensure 'Present' -Path "C:\ClusterStorage\VD-VM-01" -SwitchName "VMNetwork" -VLANID $($VM.VLAN) -Generation $($VM.Generation) -CPU $($VM.CPU)
    Start-DscConfiguration -Verbose -Force -Wait -Path .\k8s-vms
}
#k8s-vms -NodeName HV02 -VMName k8s-master-a -StartupMemory 1073741824 -MinimumMemory 1073741824 -MaximumMemory 25769803776 -Path "c:\ClusterStorage\disk0\" -SwitchName "VMNetwork" -VLANID 20 -Generation 1 -CPU 2