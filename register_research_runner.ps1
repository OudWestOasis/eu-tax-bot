# Zet de 'API' deep-research runner op als persistent achtergrondproces dat bij
# inloggen start (via een verborgen launcher in de Startup-map). Dat draait in je
# VOLLEDIGE gebruikerssessie, zodat Claude/Railway-CLI + hun auth bereikbaar zijn
# (een geplande taak doet dat NIET — die kan AppData\npm niet zien).
#
# Vereist: 'claude' eenmalig ingelogd (draai 'claude' en /login) + de .venv.
# Eenmalig draaien:
#   powershell -ExecutionPolicy Bypass -File register_research_runner.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Ruim de eerdere (niet-werkende) geplande taak op.
Unregister-ScheduledTask -TaskName "EU Tax Research Runner" -Confirm:$false -ErrorAction SilentlyContinue

# venv-pythonw (heeft requests) — vensterloos.
$venvw = Join-Path $here ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvw)) { throw "venv niet gevonden: $venvw (draai eerst: python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt)" }

# Verborgen launcher in de Startup-map.
$startup = [Environment]::GetFolderPath('Startup')
$vbsPath = Join-Path $startup "EU Tax Research Runner.vbs"
$vbs = @"
' Auto-start EU Tax deep-research runner (verborgen, volledige gebruikerssessie).
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "$here"
sh.Run """$venvw"" research_runner.py", 0, False
"@
Set-Content -Path $vbsPath -Value $vbs -Encoding ASCII
Write-Host "Launcher geplaatst: $vbsPath"

# Stop een eventueel lopende instance en start nu opnieuw.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*research_runner.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$wsh = New-Object -ComObject WScript.Shell
$wsh.CurrentDirectory = $here
$wsh.Run("`"$venvw`" research_runner.py", 0, $false) | Out-Null
Write-Host "Research-runner gestart (achtergrond, start voortaan bij inloggen)."
Write-Host "Uitzetten: verwijder '$vbsPath' en stop pythonw."
