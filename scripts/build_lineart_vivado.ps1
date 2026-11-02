param([string]$HlsDirectory='C:\fpga_build\tcb705_lineart_20261020',
      [string]$ProjectDirectory='',
      [ValidateSet('create','build','all')][string]$Stage='all')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(!$ProjectDirectory){$ProjectDirectory=Join-Path $root 'hw\vivado_lineart'}
$vivado='D:\Xilinx\Vivado\2024.2\bin\vivado.bat'
$env:PROCESSOR_ARCHITECTURE='AMD64'
$logs=Join-Path $root 'build\tcb705\lineart_build'
New-Item -ItemType Directory -Force $logs | Out-Null
if($Stage -eq 'all' -or $Stage -eq 'create') {
    $ip=Join-Path $root 'hw\ip\lineart'
    $package=Join-Path $HlsDirectory 'hls\hls\impl\ip'
    if(Test-Path "$ip\component.xml") {
        # Source deliveries contain the exact packaged IP. Reuse it; never overwrite
        # a different package silently when a newer HLS build exists.
        if(Test-Path "$package\component.xml") {
            $package=(Get-Item -LiteralPath $package).FullName
            $sourceFiles=@(Get-ChildItem -LiteralPath $package -File -Recurse)
            $installedFiles=@(Get-ChildItem -LiteralPath $ip -File -Recurse)
            if($sourceFiles.Count -ne $installedFiles.Count){throw 'Packaged IP differs; explicitly archive old hw/ip/lineart first'}
            foreach($sourceFile in $sourceFiles) {
                $relative=$sourceFile.FullName.Substring($package.Length).TrimStart('\','/')
                $installed=Join-Path $ip $relative
                if(!(Test-Path -LiteralPath $installed) -or (Get-FileHash -LiteralPath $sourceFile.FullName).Hash -ne (Get-FileHash -LiteralPath $installed).Hash){throw "Packaged IP differs: $relative"}
            }
        }
        Write-Output 'Using existing packaged lineart IP'
    }else{
        if(Test-Path $ip){throw 'Incomplete IP directory; choose or restore a complete package'}
        if(!(Test-Path "$package\component.xml")){throw 'Run the HLS package stage first'}
        Copy-Item -LiteralPath $package -Destination $ip -Recurse
    }
    & $vivado -mode batch -source "$root\hw\lineart\create_lineart.tcl" -log "$logs\create.log" -journal "$logs\create.jou" -tclargs $root $ip $ProjectDirectory *> "$logs\create_console.log"
    if($LASTEXITCODE -ne 0){throw "Vivado create failed: $logs\create_console.log"}
}
if($Stage -eq 'all' -or $Stage -eq 'build') {
    & $vivado -mode batch -source "$root\hw\md0700r\build_fused.tcl" -log "$logs\build.log" -journal "$logs\build.jou" -tclargs "$ProjectDirectory\tcb705_lineart.xpr" *> "$logs\build_console.log"
    if($LASTEXITCODE -ne 0){throw "Vivado build failed: $logs\build_console.log"}
}
Write-Output "LINEART_VIVADO_$Stage COMPLETE: $ProjectDirectory"
