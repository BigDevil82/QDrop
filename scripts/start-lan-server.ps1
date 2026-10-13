param([int]$Port=8000)

# Personal LAN mode: keep the matching firewall rule scoped to Private networks.
& "$PSScriptRoot/start-server.ps1" -Port $Port -BindHost "0.0.0.0"
