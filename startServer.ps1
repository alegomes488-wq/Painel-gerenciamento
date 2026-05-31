# Pressione qualquer tecla para parar o servidor
Write-Host '=== CyberCore IA Server ===' -ForegroundColor Cyan

# Garante porta 7860 livre
$portCheck = netstat -ano | findstr ':7860.*LISTENING'
if ($portCheck) {
    $ownerPid = ($portCheck -split '\s+')[-1]
    Write-Host "Porta 7860 ocupada pelo PID $ownerPid - liberando..." -ForegroundColor Yellow
    taskkill /F /PID $ownerPid 2>$null
    Start-Sleep 1
}

Push-Location "$PSScriptRoot"
Write-Host 'Servidor iniciando em http://localhost:7860' -ForegroundColor Green
python backend/main.py
Pop-Location
