[CmdletBinding()]
param([switch]$Execute,[string]$RuntimeRoot="$env:USERPROFILE\Documents\BmgPocRuntime")
$ErrorActionPreference='Stop'
$bmgProject=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$bmgEvidence=Join-Path $bmgProject 'outputs\overnight\ready-to-shut-down.json'
if(!(Test-Path -LiteralPath $bmgEvidence)){throw 'The verified overnight checkpoint has not been saved.'}
$bmgReady=Get-Content -LiteralPath $bmgEvidence -Raw | ConvertFrom-Json
if(!$bmgReady.stageEComplete -or !$bmgReady.privateStorageVerified -or !$bmgReady.trainingRolesRemoved -or !$bmgReady.networkRetained){throw 'Overnight verification is incomplete.'}
$bmgWorkers=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('dotnet.exe','Bmg.Intake.Worker.exe') -and $_.CommandLine -like '*Bmg.Intake.Worker*' })
if($bmgWorkers.Count -gt 0){throw 'A POC worker is still running; finish and stop it before shutdown.'}
if(!$Execute){Write-Output 'Ready: Stage E saved, private access restored, network retained, workers stopped. Preview only.';exit 0}
[System.IO.File]::WriteAllText((Join-Path $RuntimeRoot 'overnight-stop-awake'),'Release temporary awake lease before shutdown.')
$bmgPowerRecord=Join-Path $bmgProject 'outputs\overnight\power-action.json'
@{action='Shutdown requested';requestedAt=(Get-Date).ToUniversalTime().ToString('o');delaySeconds=60;networkRetained=$true;physicalPowerOffObserved=$false} | ConvertTo-Json | Set-Content -LiteralPath $bmgPowerRecord -Encoding utf8
# The user explicitly authorized shutdown, including forced application closure if necessary.
& "$env:SystemRoot\System32\shutdown.exe" /s /f /t 60 /c 'BMG Stage E work and handover saved. Requested overnight shutdown.'
if($LASTEXITCODE -eq 0){Write-Output 'Windows accepted shutdown in 60 seconds.';exit 0}
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class BmgSleepFallback {
    [DllImport("powrprof.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetSuspendState(bool hibernate, bool forceCritical, bool disableWakeEvent);
}
'@
@{action='Sleep fallback requested';requestedAt=(Get-Date).ToUniversalTime().ToString('o');networkRetained=$true;physicalSleepObserved=$false} | ConvertTo-Json | Set-Content -LiteralPath $bmgPowerRecord -Encoding utf8
Start-Sleep -Seconds 12
if(![BmgSleepFallback]::SetSuspendState($false,$false,$false)){throw 'Windows rejected both shutdown and sleep.'}
