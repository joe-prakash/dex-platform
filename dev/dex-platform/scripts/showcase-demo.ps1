$BaseUrl = "http://localhost:8000"
$Hostname = "DESKTOP-8KD58PM"

Write-Host ""
Write-Host "========================================"
Write-Host " DEX PLATFORM - LIVE SHOWCASE"
Write-Host "========================================"

Write-Host ""
Write-Host "1. PLATFORM STATUS"
Invoke-RestMethod "$BaseUrl/" |
    ConvertTo-Json -Depth 6

Write-Host ""
Write-Host "2. FLEET HEALTH"
Invoke-RestMethod "$BaseUrl/fleet/summary" |
    ConvertTo-Json -Depth 6

Write-Host ""
Write-Host "3. DEVICE INVENTORY"
Invoke-RestMethod "$BaseUrl/devices" |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "4. DEVICE HEALTH"
Invoke-RestMethod "$BaseUrl/devices/$Hostname/health" |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "5. TOP CPU PROCESSES"
Invoke-RestMethod "$BaseUrl/devices/$Hostname/top-processes?limit=5" |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "6. AUTOMATED INSIGHTS"
Invoke-RestMethod "$BaseUrl/devices/$Hostname/insights" |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "7. FLEET-WIDE INSIGHTS"
Invoke-RestMethod "$BaseUrl/insights" |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "8. REMEDIATION ACTIONS"
Invoke-RestMethod "$BaseUrl/remediations/actions" |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "9. CREATE REMEDIATION"

$body = @{
    hostname = $Hostname
    action = "COLLECT_DIAGNOSTICS"
    reason = "Automated DEX showcase remediation"
} | ConvertTo-Json

$remediation = Invoke-RestMethod `
    -Uri "$BaseUrl/remediations" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body

$remediation |
    ConvertTo-Json -Depth 8

$id = $remediation.remediation_id

Write-Host ""
Write-Host "10. EXECUTE REMEDIATION"

Invoke-RestMethod `
    -Uri "$BaseUrl/remediations/$id/execute" `
    -Method POST |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "11. REMEDIATION AUDIT TRAIL"

Invoke-RestMethod "$BaseUrl/remediations/$id" |
    ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "========================================"
Write-Host " SHOWCASE COMPLETE"
Write-Host "========================================"
