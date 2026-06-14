# Registreert de 'API' deep-research runner: draait ~elke minuut, vensterloos,
# pakt research-verzoeken op (die de Railway-worker logt) en draait Claude Code
# headless om de samenvatting naar Telegram te sturen.
#
# Vereist: 'claude' eenmalig ingelogd (draai 'claude' en /login) + de .venv.
# Eenmalig draaien:
#   powershell -ExecutionPolicy Bypass -File register_research_runner.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "EU Tax Research Runner"

# venv-pythonw heeft de packages (requests) en is onafhankelijk van user-site.
$venvw = Join-Path $here ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvw)) {
    $python = (Get-Command python).Source
    $venvw = $python -replace "python\.exe$", "pythonw.exe"
}
Write-Host "Interpreter: $venvw"

$action = New-ScheduledTaskAction -Execute $venvw -Argument "research_runner.py" -WorkingDirectory $here

# Tijd-trigger met herhaling elke minuut (AtLogOn vereist hier admin).
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(45) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
    -Hidden

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Limited `
    -Description "Draait 'API' deep-research via Claude Code op de laptop; stuurt samenvatting naar Telegram." | Out-Null

Write-Host "Taak '$taskName' geregistreerd: elke minuut, vensterloos."
Write-Host "Uitzetten met:  Disable-ScheduledTask -TaskName '$taskName'"
