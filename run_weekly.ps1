# run_weekly.ps1
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

& "$repoRoot\.venv\Scripts\python.exe" "$repoRoot\main.py" *>> "$repoRoot\run_weekly.log"
