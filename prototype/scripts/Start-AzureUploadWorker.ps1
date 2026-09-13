param(
    [string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime\stage-d",
    [string]$ConfigurationPath = "$env:USERPROFILE\Documents\BmgPocRuntime\azure\stage-d-config.json",
    [switch]$Once,
    [switch]$StatusOnly,
    [switch]$VerifyIdentity
)
$ErrorActionPreference = 'Stop'
$prototype = Split-Path $PSScriptRoot -Parent
$dll = Join-Path $prototype 'src\Bmg.Intake.Worker\bin\Release\net10.0\Bmg.Intake.Worker.dll'
$arguments = @($dll,'--azure-upload','--azure-config',$ConfigurationPath,'--root',$RuntimeRoot)
if ($Once) { $arguments += '--once' }
if ($StatusOnly) { $arguments += '--status' }
if ($VerifyIdentity) { $arguments += '--verify-identity' }
& "$env:USERPROFILE\Documents\BmgPocTools\dotnet\dotnet.exe" @arguments
exit $LASTEXITCODE
