# AI Employee Silver — Windows Task Scheduler Setup
# Run this script as Administrator (Right-click -> Run with PowerShell as Admin)

$TaskName   = "AI-Employee-Silver-Watchers"
$PythonExe  = "C:\Users\ASUS\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$Script     = "C:\Users\ASUS\Claude Projects\AI-Employee-Silver\watchers\launcher.py"
$WorkingDir = "C:\Users\ASUS\Claude Projects\AI-Employee-Silver"

Write-Host "Setting up AI Employee Silver Task Scheduler..." -ForegroundColor Cyan

# Remove old task if exists
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Create action
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$Script`"" `
    -WorkingDirectory $WorkingDir

# Trigger: run at logon (30 second delay so desktop loads first)
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = "PT30S"

# Settings: no time limit, restart on failure
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force

Write-Host ""
Write-Host "Task created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Verifying..." -ForegroundColor Yellow
schtasks /query /tn $TaskName /fo LIST
Write-Host ""
Write-Host "Done. Watchers will now auto-start every time you log into Windows." -ForegroundColor Green
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
