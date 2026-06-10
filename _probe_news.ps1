$env:PYTHONPATH = 'D:\DraftMind\backend'
$env:PYTHONUNBUFFERED = '1'
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/news/refresh?limit=3' -Method POST -TimeoutSec 15 -UseBasicParsing
    Write-Host 'STATUS:' $r.StatusCode
    Write-Host 'BODY (first 800 chars):'
    Write-Host ($r.Content.Substring(0, [Math]::Min(800, $r.Content.Length)))
} catch {
    Write-Host 'EXCEPTION:' $_.Exception.Message
    if ($_.Exception.Response) {
        Write-Host 'STATUS:' $_.Exception.Response.StatusCode
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Host 'BODY:'
        Write-Host $reader.ReadToEnd()
    }
}
