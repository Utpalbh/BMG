param([string]$RuntimeRoot="$env:USERPROFILE\Documents\BmgPocRuntime")
$ErrorActionPreference='Stop'
$bmgStopFile=Join-Path $RuntimeRoot 'overnight-stop-awake'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class BmgPowerLease {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern uint SetThreadExecutionState(uint flags);
}
'@
if([BmgPowerLease]::SetThreadExecutionState(2147483649) -eq 0){throw 'Could not hold the temporary system-awake lease.'}
Write-Output "Temporary system-awake lease active; PID $PID. No power-plan settings changed."
$bmgDeadline=(Get-Date).AddHours(3)
try {
    while(!(Test-Path -LiteralPath $bmgStopFile) -and (Get-Date) -lt $bmgDeadline){Start-Sleep -Seconds 10}
} finally { [BmgPowerLease]::SetThreadExecutionState(2147483648) | Out-Null }
Write-Output 'System-awake lease released.'
