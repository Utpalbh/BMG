[CmdletBinding(SupportsShouldProcess, ConfirmImpact='High')]
param([switch]$Delete, [string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime")
$ErrorActionPreference = 'Stop'
$sub = '6f841b52-7a6d-4287-b0e3-4591621bb363'
$rg = 'rg-bmg-poc'
$expectedId = "/subscriptions/$sub/resourceGroups/$rg"
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$evidenceDir = Join-Path $projectRoot 'outputs\stage-c'
$sessionPath = Join-Path $RuntimeRoot 'azure\cloud-session.json'
if (!(Test-Path -LiteralPath $sessionPath)) { throw 'Missing local POC session inventory; refusing deletion.' }
$session = Get-Content -Raw -LiteralPath $sessionPath | ConvertFrom-Json
if ($session.subscriptionId -ne $sub -or $session.resourceGroup -ne $rg) { throw 'Session scope mismatch.' }
$exists = az group exists --name $rg --subscription $sub -o tsv
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify Azure resource group.' }
if ($exists -ne 'true') { Write-Output 'POC resource group is already absent.'; return }
$group = az group show --name $rg --subscription $sub -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $group.id -ne $expectedId -or $group.tags.project -ne 'BMG-POC' -or $group.tags.managedBy -ne 'BMG-StageC-Bicep') { throw 'POC scope or ownership tags mismatch; refusing deletion.' }
az resource list --resource-group $rg --subscription $sub -o json > (Join-Path $evidenceDir 'inventory-before-teardown.json')
if ($LASTEXITCODE -ne 0) { throw 'Cannot export resource inventory.' }
Write-Output "Verified deletion scope: $expectedId"
Write-Output 'Deletes all resources inside this POC group, including future stages. Export their results first. Key Vault purge protection retains its deleted vault for seven days. VPN profiles/certificates and Entra apps are separate local/directory cleanup items.'
if (!$Delete) { Write-Output 'Preview only. Use -Delete when the POC is finished.'; return }
if ($PSCmdlet.ShouldProcess($expectedId,'Delete the inventoried BMG POC resource group and all its contents')) {
    az group delete --name $rg --subscription $sub --yes --no-wait
    if ($LASTEXITCODE -ne 0) { throw 'Resource group deletion request failed.' }
    @{requestedAt=[DateTime]::UtcNow.ToString('o');resourceGroupId=$expectedId;status='Deletion requested; not yet verified complete'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceDir 'teardown-status.json')
    Write-Output 'Deletion requested. Poll az group exists until false; billing does not stop merely because this command returned.'
}
