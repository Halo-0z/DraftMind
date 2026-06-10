$since = (Get-Date).AddHours(-1)
Get-ChildItem 'D:\DraftMind' -Recurse -Filter '*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -gt $since } |
    Select-Object FullName, Length, LastWriteTime |
    Format-Table -AutoSize
Write-Host '---'
Get-ChildItem 'D:\DraftMind\backend_LOG' -ErrorAction SilentlyContinue | Format-List Name,Length,LastWriteTime
Write-Host '--- TAIL backend_LOG ---'
if (Test-Path 'D:\DraftMind\backend_LOG') {
    Get-Content 'D:\DraftMind\backend_LOG' -Tail 40
}
