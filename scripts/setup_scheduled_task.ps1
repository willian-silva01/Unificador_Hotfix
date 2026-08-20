#Requires -RunAsAdministrator
# Configura o Hotfix Unifier para iniciar automaticamente no boot do Windows
# e libera a porta 8501 no Firewall para acesso pela rede local.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath = Join-Path $ScriptDir "start_hotfix_unifier.bat"

$Action = New-ScheduledTaskAction -Execute $BatPath
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Unregister-ScheduledTask -TaskName "HotfixUnifier" -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName "HotfixUnifier" `
    -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description "Inicia o Hotfix Unifier (Streamlit) automaticamente no boot, mesmo sem login."

New-NetFirewallRule -DisplayName "Hotfix Unifier (Streamlit 8501)" `
    -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow `
    -ErrorAction SilentlyContinue | Out-Null

Start-ScheduledTask -TaskName "HotfixUnifier"

Start-Sleep -Seconds 5
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -notlike "169.*" } | Select-Object -First 1).IPAddress

Write-Output ""
Write-Output "Tarefa 'HotfixUnifier' registrada e iniciada."
Write-Output "Acesse pela rede local em: http://$ip`:8501"
