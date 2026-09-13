param(
    [string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime",
    [switch]$Once,
    [switch]$StatusOnly
)
$ErrorActionPreference = 'Stop'
$bmgPrototype = Split-Path $PSScriptRoot -Parent
$bmgDotnet = "$env:USERPROFILE\Documents\BmgPocTools\dotnet\dotnet.exe"
$bmgDll = Join-Path $bmgPrototype 'src\Bmg.Intake.Worker\bin\Release\net10.0\Bmg.Intake.Worker.dll'
if (!(Test-Path -LiteralPath $bmgDll)) { throw 'Build the worker with Build-Local.ps1 first.' }
$bmgArguments = @($bmgDll, '--simulate', '--root', $RuntimeRoot)
if ($Once) { $bmgArguments += '--once' }
if ($StatusOnly) { $bmgArguments += '--status' }
& $bmgDotnet @bmgArguments
exit $LASTEXITCODE
