param(
    [string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime\stage-e",
    [string]$Configuration = "$env:USERPROFILE\Documents\BmgPocRuntime\azure\stage-e-config.json",
    [switch]$Once,
    [switch]$Status
)
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot -Parent
$bmgArgs=@((Join-Path $project 'src\Bmg.Intake.Worker\bin\Release\net10.0\Bmg.Intake.Worker.dll'),'--azure-documents','--root',$RuntimeRoot,'--azure-config',$Configuration)
if($Once){$bmgArgs+='--once'}
if($Status){$bmgArgs+='--status'}
& "$env:USERPROFILE\Documents\BmgPocTools\dotnet\dotnet.exe" @bmgArgs
exit $LASTEXITCODE
