# Registers a Windows scheduled task that sends tomorrow's hearings daily at 8:00 PM.
# Run once from PowerShell:  powershell -ExecutionPolicy Bypass -File .\install_task.ps1
param(
    [string]$Time = "20:00",
    [string]$TaskName = "ABI Hearing WhatsApp Reminder"
)

$dir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python).Source

$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$dir\main.py`" send" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Daily -At $Time
# StartWhenAvailable: if the PC was off/asleep at 8 PM, run as soon as it is back.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
            -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)
# Interactive: runs in your logged-in session so Chrome can use the saved profile.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Scheduled '$TaskName' daily at $Time using $python"
Write-Host "Test it now with:  Start-ScheduledTask -TaskName '$TaskName'"
