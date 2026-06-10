if (Test-Path 'D:\DraftMind\backend_LOG') {
    Write-Host '--- backend_LOG full tail ---'
    Get-Content 'D:\DraftMind\backend_LOG' -Tail 60
} else {
    Write-Host '(no backend_LOG)'
}
