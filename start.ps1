# Tizimni ishga tushiradi: Qdrant konteyneri + backend.
# Ishlatish: PowerShell da .\start.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "XATO: .venv topilmadi. Avval quyidagini bajaring:" -ForegroundColor Red
    Write-Host "  py -3.12 -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

# port band bo'lsa, uvicorn tushunarsiz xato beradi, shuning uchun oldindan aytamiz
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    $owner = (Get-Process -Id $busy.OwningProcess[0] -ErrorAction SilentlyContinue).ProcessName
    Write-Host "XATO: 8000-port allaqachon band ($owner, PID $($busy.OwningProcess[0]))." -ForegroundColor Red
    Write-Host "Uni to'xtatish:  Stop-Process -Id $($busy.OwningProcess[0]) -Force"
    Write-Host "Yoki boshqa portda ishga tushiring:  .\start.ps1 -Port 8001"
    exit 1
}

Write-Host "Qdrant tekshirilmoqda..." -ForegroundColor Cyan
docker compose up -d | Out-Null
$ok = $false
foreach ($i in 1..30) {
    try {
        Invoke-RestMethod -TimeoutSec 2 http://localhost:6333/collections | Out-Null
        $ok = $true
        break
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $ok) {
    Write-Host "XATO: Qdrant javob bermadi. Docker Desktop ishga tushganini tekshiring." -ForegroundColor Red
    exit 1
}

try {
    $info = Invoke-RestMethod -TimeoutSec 5 http://localhost:6333/collections/uz_legal
    Write-Host "Qdrant tayyor: $($info.result.points_count) nuqta" -ForegroundColor Green
} catch {
    Write-Host "Ogohlantirish: uz_legal kolleksiyasi yo'q. Avval indexatsiya qiling:" -ForegroundColor Yellow
    Write-Host "  .\.venv\Scripts\python.exe scripts\index.py"
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -notmatch 'Loopback|WSL|vEthernet' -and $_.IPAddress -notmatch '^169\.' } |
    Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "  Kompyuterda:  http://localhost:8000" -ForegroundColor Green
if ($ip) { Write-Host "  Telefondan:   http://${ip}:8000" -ForegroundColor Green }
Write-Host "  To'xtatish:   Ctrl+C"
Write-Host ""

$env:PYTHONIOENCODING = "utf-8"
& $python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
