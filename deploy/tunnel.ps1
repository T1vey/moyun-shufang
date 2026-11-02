#Requires -Version 5.1
param([Parameter(Mandatory)][string]$BoardIP,[string]$UserName='xilinx',[int]$LocalPort=8768)
if ($BoardIP -notmatch '^[a-zA-Z0-9.-]+$' -or $UserName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid host/user' }
if ($LocalPort -lt 1024 -or $LocalPort -gt 65535) { throw 'Invalid local port' }
Write-Output "保持本终端打开，然后在另一终端执行 launch_pc.ps1。板端转发端口：$LocalPort"
$editionFile=Join-Path (Split-Path $PSScriptRoot -Parent) 'config/edition.json'
$edition=if(Test-Path -LiteralPath $editionFile){(Get-Content -Raw -LiteralPath $editionFile | ConvertFrom-Json).ik_engine}else{'wls'}
if($edition -notin @('wls','upstream')){throw 'Unsupported package edition'}
$boardPort=if($edition -eq 'upstream'){8766}else{8765}
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -L "${LocalPort}:127.0.0.1:${boardPort}" "${UserName}@${BoardIP}"
exit $LASTEXITCODE
