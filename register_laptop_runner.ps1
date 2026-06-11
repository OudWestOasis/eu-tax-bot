# Registreert de laptop-runner als geplande taak: draait ~elke minuut zolang je
# bent ingelogd (laptop open/in gebruik), vensterloos. Staat de laptop dicht /
# in slaap / uitgelogd, dan draait de taak niet -> heartbeat veroudert -> de
# cloud neemt het automatisch over.
#
# Eenmalig draaien:
#   powershell -ExecutionPolicy Bypass -File register_laptop_runner.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "EU Tax Laptop Runner"

# pythonw = vensterloos (geen flikkerend scherm).
# Gebruik bij voorkeur de zelfstandige venv in de repo: die heeft alle packages
# en werkt onafhankelijk van het gebruikersprofiel (Taakplanner laadt user-site
# niet altijd). Val anders terug op de systeem-python.
$venvw = Join-Path $here ".venv\Scripts\pythonw.exe"
if (Test-Path $venvw) {
    $pythonw = $venvw
} else {
    $python  = (Get-Command python).Source
    $pythonw = $python -replace "python\.exe$", "pythonw.exe"
    if (-not (Test-Path $pythonw)) { $pythonw = $python }
}
Write-Host "Gebruikt interpreter: $pythonw"

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "laptop_runner.py" -WorkingDirectory $here

# Trigger: tijd-gebaseerd met herhaling elke minuut (oneindig). Geen AtLogOn,
# want dat vereist op deze machine verhoogde rechten. StartWhenAvailable zorgt
# dat de taak na een reboot/slaap gewoon weer oppakt.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

# Laptop-vriendelijk: ook op accu draaien, niet stoppen bij overschakelen,
# overlappende runs negeren, en een ronde mag max 5 min duren (scan ~90s).
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -Hidden

# Verwijder bestaande taak met dezelfde naam, registreer opnieuw.
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Limited `
    -Description "Draait de Tax-bot lokaal elke minuut zolang de laptop aan is; valt anders terug op de cloud." | Out-Null

Write-Host "Taak '$taskName' geregistreerd: elke minuut, vensterloos, ook op accu."
Write-Host "Start nu meteen met:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Uitzetten met:        Disable-ScheduledTask -TaskName '$taskName'"
