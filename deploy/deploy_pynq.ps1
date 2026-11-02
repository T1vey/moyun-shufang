#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BoardIP,
    [Alias('User')][string]$UserName='xilinx',
    [string]$Python='python',
    [ValidateSet('ps','target')][string]$Profile='target',
    [string]$OverlayDir,
    [switch]$Offline,
    [switch]$AllowMotion
)
$ErrorActionPreference='Stop'
# Compatibility entry point; all bound parameters keep their names and types.
& "$PSScriptRoot\deploy_z20.ps1" @PSBoundParameters
exit $LASTEXITCODE
