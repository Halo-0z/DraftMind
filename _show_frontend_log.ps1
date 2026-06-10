if (Test-Path 'D:\DraftMind\frontend\_frontend.log') {
    Write-Host '--- frontend log ---'
    Get-Content 'D:\DraftMind\frontend\_frontend.log' -Tail 40
} else {
    Write-Host '(no frontend log)'
}
