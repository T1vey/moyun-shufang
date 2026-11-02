# SO-101 display: phone-cannot-connect diagnostics. Read-only, changes nothing.
param([int]$Port = 8090)
$ErrorActionPreference = 'SilentlyContinue'
$out = Join-Path $PSScriptRoot '..\diag_report.txt'
$sb = New-Object System.Text.StringBuilder
function W($s) { [void]$sb.AppendLine($s) }
function Sec($t) { W ''; W ('===== ' + $t + ' =====') }

W ("time: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "   port: $Port")
W ("windows: " + [Environment]::OSVersion.VersionString)

Sec 'network profiles (Public blocks inbound by default)'
Get-NetConnectionProfile | ForEach-Object { W ("{0} | SSID/name={1} | category={2} | ipv4={3}" -f $_.InterfaceAlias, $_.Name, $_.NetworkCategory, $_.IPv4Connectivity) }

Sec 'adapters with IPv4'
Get-NetIPConfiguration | Where-Object { $_.IPv4Address } | ForEach-Object {
  $gw = ($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop }) -join ','
  W ("{0} | {1} | ip={2}/{3} | gw={4} | status={5}" -f $_.InterfaceAlias, $_.InterfaceDescription, $_.IPv4Address.IPAddress, $_.IPv4Address.PrefixLength, $gw, $_.NetAdapter.Status)
}

Sec 'default routes'
Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | ForEach-Object { W ("{0} via {1} metric={2}+{3}" -f $_.InterfaceAlias, $_.NextHop, $_.RouteMetric, (Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4).InterfaceMetric) }

Sec "who listens on port $Port"
Get-NetTCPConnection -LocalPort $Port -State Listen | ForEach-Object {
  $p = Get-Process -Id $_.OwningProcess
  W ("{0}:{1} pid={2} {3} {4}" -f $_.LocalAddress, $_.LocalPort, $_.OwningProcess, $p.ProcessName, $p.Path)
}
if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen)) { W "NOTHING is listening on $Port  -> server not running (run run_display.bat first)" }

Sec 'firewall profiles'
Get-NetFirewallProfile | ForEach-Object { W ("{0}: enabled={1} defaultInbound={2} allowLocalRules={3}" -f $_.Name, $_.Enabled, $_.DefaultInboundAction, $_.AllowLocalFirewallRules) }

Sec 'firewall rules for python / port'
$rules = Get-NetFirewallRule -Direction Inbound | Where-Object { $_.DisplayName -match 'python|so-?101|8090' }
foreach ($r in $rules) {
  $app = ($r | Get-NetFirewallApplicationFilter).Program
  $pf = $r | Get-NetFirewallPortFilter
  W ("[{0}] enabled={1} action={2} profile={3} proto={4} port={5} app={6}" -f $r.DisplayName, $r.Enabled, $r.Action, $r.Profile, $pf.Protocol, $pf.LocalPort, $app)
}
if (-not $rules) { W 'no inbound rule mentions python / 8090' }

Sec 'third-party security / VPN processes'
Get-Process | Where-Object { $_.ProcessName -match 'sangfor|EasyConnect|aTrust|leigod|clash|v2ray|mihomo|sing-box|360|huorong|HipsDaemon|kav|McAfee|Norton|Tailscale|ZeroTier|wireguard|openvpn|VirtualBox|MuMu' } |
  Select-Object -Unique ProcessName | ForEach-Object { W $_.ProcessName }

Sec 'self test via each LAN ip'
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127|169\.254)\.' } | ForEach-Object {
  $ip = $_.IPAddress
  try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 ("http://{0}:{1}/api/ping" -f $ip, $Port); W ("{0}  OK {1}" -f $ip, $r.StatusCode) }
  catch { W ("{0}  FAIL {1}" -f $ip, $_.Exception.Message) }
}

[System.IO.File]::WriteAllText((Resolve-Path (Split-Path $out)).Path + '\diag_report.txt', $sb.ToString(), (New-Object System.Text.UTF8Encoding $true))
Write-Host $sb.ToString()
Write-Host ''
Write-Host "Report saved: $out"
