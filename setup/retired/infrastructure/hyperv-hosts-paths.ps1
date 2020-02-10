Configuration HyperVHostPaths
{
    param
    (
        [Parameter(Mandatory=$true, Position=0)]
        #[ValidateScript({Test-Path $_})]
        $VirtualHardDiskPath,

        [Parameter(Mandatory=$true, Position=1)]
        #[ValidateScript({Test-Path $_})]
        $VirtualMachinePath
    )

    Import-DscResource -moduleName xHyper-V
    Node HV02 {
        xVMHost HyperVHostPaths
        {
            IsSingleInstance    = 'Yes'
            VirtualHardDiskPath = $VirtualHardDiskPath
            VirtualMachinePath  = $VirtualMachinePath
        }
    }
    Node HV03 {
        xVMHost HyperVHostPaths
        {
            IsSingleInstance    = 'Yes'
            VirtualHardDiskPath = $VirtualHardDiskPath
            VirtualMachinePath  = $VirtualMachinePath
        }
    }

}
HyperVHostPaths -VirtualHardDiskPath "C:\ClusterStorage\" -VirtualMachinePath "C:\ClusterStorage\"
