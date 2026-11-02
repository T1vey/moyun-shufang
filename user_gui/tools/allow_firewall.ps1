# Allow phones on the LAN to reach the display server: one inbound TCP rule for the port,
# limited to local-subnet sources, on all network profiles (incl. Public Wi-Fi). Needs admin.
param([int]$Port = 8090)
$name = "SO-101 Display (TCP $Port)"
Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
  -RemoteAddress LocalSubnet -Profile Any | Out-Null
Get-NetFirewallRule -DisplayName $name | Format-Table DisplayName, Enabled, Action, Profile -AutoSize
Write-Host "Done. Remove later with:  Remove-NetFirewallRule -DisplayName '$name'"
