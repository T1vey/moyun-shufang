#Requires -Version 5.1
param(
    [string]$Python='python',
    [string]$BoardURL='http://127.0.0.1:8768',
    [int]$Port=8765,
    [string]$CloudConfig,
    [string]$SecretsFile
)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
$taskArgs=@('-B',"$taskRoot\app.py",'--port',"$Port",'--board-url',$BoardURL)
if ($CloudConfig) {$taskArgs+=@('--cloud-config',(Resolve-Path -LiteralPath $CloudConfig).Path)}
if ($SecretsFile) {$taskArgs+=@('--secrets-file',(Resolve-Path -LiteralPath $SecretsFile).Path)}
Write-Host "电脑控制页：http://127.0.0.1:$Port；板端转发：$BoardURL"
& $Python @taskArgs
exit $LASTEXITCODE
