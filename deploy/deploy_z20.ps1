#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BoardIP,
    [string]$UserName='xilinx',
    [string]$Python='python',
    [ValidateSet('ps','target')][string]$Profile='target',
    [string]$OverlayDir,
    [switch]$Offline,
    [switch]$AllowMotion
)
$ErrorActionPreference='Stop'
if ($BoardIP -notmatch '^[a-zA-Z0-9.-]+$' -or $UserName -notmatch '^[a-zA-Z0-9_-]+$') {throw 'Invalid host/user'}
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskRelease='release_'+[guid]::NewGuid().ToString('N')
$taskArchive=Join-Path ([IO.Path]::GetTempPath()) ($taskRelease+'.zip')
try {
    $taskArgs=@('-B',"$taskRoot\scripts\build_delivery.py",'--output',$taskArchive)
    if ($Profile -eq 'target') {
        if (-not $OverlayDir) {throw 'Target deployment requires -OverlayDir with drawing_target.bit/hwh/registers.json'}
        $taskArgs+=@('--overlay-dir',(Resolve-Path -LiteralPath $OverlayDir).Path,'--require-hardware')
    }
    & $Python @taskArgs
    if ($LASTEXITCODE -ne 0) {throw 'Release packaging failed; nothing uploaded'}
    & scp $taskArchive "${UserName}@${BoardIP}:$taskRelease.zip"
    if ($LASTEXITCODE -ne 0) {throw 'SCP failed'}
    $taskRemote="~/so101_releases/$taskRelease/so101_target_runtime"
    $taskSetup="mkdir -p ~/so101_releases/$taskRelease && python3 -m zipfile -e ~/$taskRelease.zip ~/so101_releases/$taskRelease && bash $taskRemote/deploy/install_z20.sh --profile $Profile"
    if ($Offline) {$taskSetup+=' --offline'}
    if ($AllowMotion) {$taskSetup+=' --allow-motion'}
    # PYNQ's login environment supplies XILINX_XRT/PYTHONPATH for target setup.
    & ssh -t "${UserName}@${BoardIP}" "bash -l -c '$taskSetup'"
    if ($LASTEXITCODE -ne 0) {throw 'Board installation failed; release retained for diagnosis'}
    Write-Output "Installed $taskRemote; shared data: ~/so101_data"
    Write-Output 'PC: deploy/tunnel.ps1 -BoardIP ..., then launch_pc.ps1'
} finally {
    if (Test-Path -LiteralPath $taskArchive) {Remove-Item -LiteralPath $taskArchive}
    if (Test-Path -LiteralPath ($taskArchive+'.sha256')) {Remove-Item -LiteralPath ($taskArchive+'.sha256')}
}
