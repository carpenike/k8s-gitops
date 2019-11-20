#######################################################
##
## Set-KCD.ps1, v1.1, 2012
##
## Created by Matthijs ten Seldam, Microsoft
##
#######################################################

<#
.SYNOPSIS
Configures Kerberos Constrained Delegation (KCD) on a computer object in Active Directory.

.DESCRIPTION
Set-KCD supports adding, replacing and removing delegation records for a specified distinguished user or computer object in Active Directory.

.PARAMETER AdDN
The distinguished name of the user or computer object.

.PARAMETER HostFQDN
The fully qualified domain name of the target computer.

.PARAMETER Service
The name of the service type to delegate.

.PARAMETER Add
Switch to specify the operation.

.PARAMETER Replace
Switch to specify the operation.

.PARAMETER Remove
Switch to specify the operation.

.EXAMPLE
Set-KCD -AdDN "cn=vmhos1,cn=computers,dc=contoso,dc=com" vmhost2.contoso.com cifs -Add

This command adds the CIFS service type to the computer object vmhost1.contoso.com for computer vmhost2.contoso.com to trust vmhost1 for delegation to vmhost2 for this service.

.EXAMPLE
Set-KCD.ps1 -AdDN "cn=vmhost2,cn=computers,dc=contoso,dc=com" vmhost3.contoso.com "Microsoft Virtual System Migration Service" -Add

This command adds the "Microsoft Virtual System Migration Service" type to the computer object vmhost2.contoso.com for computer vmhost3.contoso.com to trust vmhost2 for delegation to vmhost3 for this service.

.EXAMPLE
Set-KCD -AdDN "cn=vmhos1,cn=computers,dc=contoso,dc=com" vmhost2.contoso.com cifs -Replace

This command replaces the property set (vmhost2.contoso.com, cifs) on the computer object vmhost1.contoso.com

.INPUTS
None

.OUTPUTS
None

.NOTES
This script must be run using domain administrator credentials.
The script adds both entries for the target computer; unqualified and fully qualified host names.

.LINK
http://blogs.technet.com/matthts
#>

[CmdletBinding(DefaultParameterSetName="Add")]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string] $AdDN,
    [Parameter(Mandatory=$true, Position=1)]
    [string] $HostFQDN,
    [Parameter(Mandatory=$true, Position=2)]
    [string]$Service,
    [Parameter(Mandatory=$true, ParameterSetName="Add")]
    [switch]$Add,
    [Parameter(Mandatory=$true, ParameterSetName="Replace")]
    [switch] $Replace,
    [Parameter(Mandatory=$true, ParameterSetName="Remove")]
    [switch] $Remove
    )


$HostName=$HostFQDN.Remove($HostFQDN.IndexOf("."))

switch($PSCmdlet.ParameterSetName)
{
    "Add"
    {
        Set-ADObject $AdDN -Add @{"msDS-AllowedToDelegateTo"="$Service/$HostFQDN","$Service/$HostName"}
    }

    "Remove"
    {
        Set-ADObject $AdDN -Remove @{"msDS-AllowedToDelegateTo"="$Service/$HostFQDN","$Service/$HostName"}
    }

    "Replace"
    {
        Set-ADObject $AdDN -Replace @{"msDS-AllowedToDelegateTo"="$Service/$HostFQDN","$Service/$HostName"}
    }

}