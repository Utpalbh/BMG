[CmdletBinding()]
param([switch]$ValidateOnly, [string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$sub = '6f841b52-7a6d-4287-b0e3-4591621bb363'
$tenant = 'e06201f9-0ec7-4863-80fc-85f43be49c1e'
$rg = 'rg-bmg-poc'
$deploymentName = 'bmg-stage-c'
$evidence = Join-Path $projectRoot 'work\stage-c'
$runtimeAzure = Join-Path $RuntimeRoot 'azure'
$account = az account show --subscription $sub -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $account.tenantId -ne $tenant) { throw 'Azure subscription or tenant check failed.' }
$plan = Get-Content -Raw -LiteralPath (Join-Path $projectRoot '.azure\infrastructure-plan.json') | ConvertFrom-Json
if ($plan.meta.status -notin @('approved','deployed')) { throw 'Stage C plan is not approved.' }
$exists = az group exists --name $rg --subscription $sub -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Cannot check target resource group.' }
if ($exists -eq 'true') {
    $group = az group show --name $rg --subscription $sub -o json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $group.tags.managedBy -ne 'BMG-StageC-Bicep' -or $group.tags.project -ne 'BMG-POC') { throw 'Target group exists without expected POC ownership tags; refusing deployment.' }
}
$operatorId = az ad signed-in-user show --query id -o tsv
if ($LASTEXITCODE -ne 0 -or $operatorId -notmatch '^[0-9a-f-]{36}$') { throw 'Unable to determine operator object ID.' }
$certs = Get-Content -Raw -LiteralPath (Join-Path $runtimeAzure 'vpn-certificates.json') | ConvertFrom-Json
$sessionPath = Join-Path $runtimeAzure 'cloud-session.json'
if (Test-Path -LiteralPath $sessionPath) {
    $session = Get-Content -Raw -LiteralPath $sessionPath | ConvertFrom-Json
} else {
    $now = [DateTime]::UtcNow
    $session = [ordered]@{subscriptionId=$sub;tenantId=$tenant;resourceGroup=$rg;deploymentName=$deploymentName;startedAt=$now.ToString('o');intendedExpiry=$now.AddHours(10).ToString('o');automaticDeletion=$false}
    if (!$ValidateOnly) { $session | ConvertTo-Json | Set-Content -LiteralPath $sessionPath -Encoding utf8 }
}
$parameters = @{
    '$schema'='https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#';contentVersion='1.0.0.0';parameters=@{
        location=@{value='eastus2'};resourceGroupName=@{value=$rg};sessionStartedAt=@{value=$session.startedAt};expiresAt=@{value=$session.intendedExpiry};vpnRootPublicCertificate=@{value=$certs.rootPublicCertificateData};operatorObjectId=@{value=$operatorId}
    }
}
$paramPath = Join-Path $runtimeAzure 'stage-c.parameters.json'
$parameters | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $paramPath -Encoding utf8
$template = Join-Path $projectRoot 'infra\main.bicep'
az deployment sub validate --name $deploymentName --location eastus2 --subscription $sub --template-file $template --parameters "@$paramPath" -o json > (Join-Path $evidence 'arm-validation.json')
if ($LASTEXITCODE -ne 0) { throw 'Azure ARM validation failed.' }
az deployment sub what-if --name $deploymentName --location eastus2 --subscription $sub --template-file $template --parameters "@$paramPath" --no-pretty-print -o json > (Join-Path $evidence 'what-if.json')
if ($LASTEXITCODE -ne 0) { throw 'Azure what-if failed.' }
$preview = Get-Content -Raw -LiteralPath (Join-Path $evidence 'what-if.json') | ConvertFrom-Json
$unexpected = @($preview.changes | Where-Object { $_.changeType -in @('Delete','Modify') -and $_.resourceId -notlike "/subscriptions/$sub/resourceGroups/$rg*" })
if ($unexpected.Count -gt 0) { throw 'Preview would change resources outside the dedicated POC group.' }
if (@($preview.changes | Where-Object changeType -eq 'Delete').Count -gt 0) { throw 'Preview contains deletions; refusing deployment.' }
$preview.changes | Group-Object changeType | Select-Object Name,Count | Format-Table
Write-Output 'ARM validation and incremental deployment preview completed.'
if ($ValidateOnly) { return }
az deployment sub create --name $deploymentName --location eastus2 --subscription $sub --template-file $template --parameters "@$paramPath" --no-wait -o json
if ($LASTEXITCODE -ne 0) { throw 'Azure deployment submission failed; inspect partial resources before retry.' }
$session | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'outputs\stage-c\cloud-session.json') -Encoding utf8
Write-Output 'Stage C deployment submitted. Hourly networking charges continue until resources are deleted.'
