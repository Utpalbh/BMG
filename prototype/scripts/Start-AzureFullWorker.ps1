param(
 [string]$RuntimeRoot="$env:USERPROFILE/Documents/BmgPocRuntime/stage-f",
 [string]$Configuration="$env:USERPROFILE/Documents/BmgPocRuntime/azure/stage-f-config.json",
 [switch]$Once,[switch]$Status
)
$ErrorActionPreference='Stop'
$prototype=Split-Path $PSScriptRoot -Parent
$arguments=@((Join-Path $prototype 'src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll'),'--azure-full','--root',$RuntimeRoot,'--azure-config',$Configuration)
if($Once){$arguments+='--once'}
if($Status){$arguments+='--status'}
& "$env:USERPROFILE/Documents/BmgPocTools/dotnet/dotnet.exe" @arguments
exit $LASTEXITCODE
