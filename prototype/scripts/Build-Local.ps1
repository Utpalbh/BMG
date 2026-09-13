$ErrorActionPreference = 'Stop'
$bmgPrototype = Split-Path $PSScriptRoot -Parent
$bmgTools = "$env:USERPROFILE\Documents\BmgPocTools"
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:DOTNET_CLI_HOME = Join-Path $bmgTools 'dotnet-home'
$env:NUGET_PACKAGES = Join-Path $bmgTools 'nuget-packages'
Push-Location $bmgPrototype
try {
    & (Join-Path $bmgTools 'dotnet\dotnet.exe') restore '.\src\Bmg.Intake.Worker\Bmg.Intake.Worker.csproj' --locked-mode --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Dependency restore failed.' }
    & (Join-Path $bmgTools 'dotnet\dotnet.exe') build '.\src\Bmg.Intake.Worker\Bmg.Intake.Worker.csproj' -c Release --no-restore --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
} finally { Pop-Location }
