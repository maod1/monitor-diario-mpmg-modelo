# Registra no Agendador de Tarefas do Windows a verificação diária do Diário Oficial do MPMG.
# Reserva do GitHub Actions: roda às 10:00, 13:00 e 17:00, uma hora depois do GitHub, caso ele falhe
# (o script não repete a análise nem a notificação depois que a edição do dia foi lida).
$pasta  = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $pasta "monitor_diario.py"
$python = (& py -c "import sys; print(sys.executable)").Trim()
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (Test-Path $pythonw) { $python = $pythonw }

$acao = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $pasta
$gatilhos = @("10:00", "13:00", "17:00") | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "Monitor Diario Oficial MPMG" -Action $acao -Trigger $gatilhos `
    -Settings $config -Description "Procura o nome no Diário Oficial do MPMG e avisa via ntfy." -Force | Out-Null
Write-Host "Tarefa 'Monitor Diario Oficial MPMG' registrada (10:00, 13:00, 17:00) usando $script"
