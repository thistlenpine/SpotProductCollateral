# run_weekly.ps1
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

& "$repoRoot\.venv\Scripts\python.exe" "$repoRoot\main.py" *>> "$repoRoot\run_weekly.log"

# Propagate main.py's exit status so a failed/unverified run is recorded as a
# failed task by Windows Task Scheduler instead of silently succeeding.
exit $LASTEXITCODE
