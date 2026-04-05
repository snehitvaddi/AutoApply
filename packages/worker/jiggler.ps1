# jiggler.ps1 — Prevents Windows from sleeping + jiggles the mouse every 10s
# Uses SetThreadExecutionState + SendInput (no external dependencies)
#
# Usage:
#   Start:  powershell -ExecutionPolicy Bypass -File jiggler.ps1
#   Stop:   powershell -ExecutionPolicy Bypass -File jiggler.ps1 stop

$PidFile = Join-Path $env:TEMP "jiggler.pid"
$MaxDurationSeconds = 86400  # 24h auto-stop safety cap

function Stop-Jiggler {
    if (Test-Path $PidFile) {
        $ProcId = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($ProcId) {
            try {
                Stop-Process -Id $ProcId -Force -ErrorAction Stop
                Write-Host "Jiggler stopped."
            } catch {
                Write-Host "Jiggler was not running (stale PID cleaned up)."
            }
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "Jiggler is not running."
    }
}

if ($args[0] -eq "stop") {
    Stop-Jiggler
    exit 0
}

# Stop existing instance first
if (Test-Path $PidFile) {
    $OldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($OldPid) { Stop-Process -Id $OldPid -Force -ErrorAction SilentlyContinue }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# Save our PID
$PID | Out-File -FilePath $PidFile -Encoding ASCII

# Load Win32 APIs
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PowerMgmt {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
    public const uint ES_CONTINUOUS = 0x80000000;
    public const uint ES_SYSTEM_REQUIRED = 0x00000001;
    public const uint ES_DISPLAY_REQUIRED = 0x00000002;
}
public class MouseJig {
    [DllImport("user32.dll")]
    public static extern bool GetCursorPos(out System.Drawing.Point lpPoint);
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);
}
"@ -ReferencedAssemblies System.Drawing

# Prevent system + display sleep
[PowerMgmt]::SetThreadExecutionState([PowerMgmt]::ES_CONTINUOUS -bor [PowerMgmt]::ES_SYSTEM_REQUIRED -bor [PowerMgmt]::ES_DISPLAY_REQUIRED) | Out-Null

Write-Host "Jiggler running (PID $PID) — mouse jiggles every 10s, sleep blocked."
Write-Host "Stop with: powershell -ExecutionPolicy Bypass -File $PSCommandPath stop"

# Jiggle loop (auto-stops after 24h safety cap)
$StartTime = Get-Date
try {
    while ($true) {
        $Elapsed = (New-TimeSpan -Start $StartTime -End (Get-Date)).TotalSeconds
        if ($Elapsed -ge $MaxDurationSeconds) {
            Write-Host "Jiggler auto-stopped after 24 hours."
            break
        }
        $pos = New-Object System.Drawing.Point
        [MouseJig]::GetCursorPos([ref]$pos) | Out-Null
        [MouseJig]::SetCursorPos($pos.X + 1, $pos.Y) | Out-Null
        Start-Sleep -Milliseconds 50
        [MouseJig]::SetCursorPos($pos.X, $pos.Y) | Out-Null
        Start-Sleep -Seconds 10
    }
} finally {
    # Release power management lock on exit
    [PowerMgmt]::SetThreadExecutionState([PowerMgmt]::ES_CONTINUOUS) | Out-Null
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
