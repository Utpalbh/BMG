[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$outDir = Join-Path $projectRoot 'outputs\stage-c'
$sub = '6f841b52-7a6d-4287-b0e3-4591621bb363'
$rg = 'rg-bmg-poc'
$services = az deployment group show --name bmg-services --resource-group $rg --subscription $sub -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $services.properties.provisioningState -ne 'Succeeded') { throw 'Service deployment is not yet successful; inventory would be incomplete.' }
$inventory = $services.properties.outputs.inventory.value
$inventory | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $outDir 'deployment-inventory.json') -Encoding utf8
az resource list --resource-group $rg --subscription $sub -o json > (Join-Path $outDir 'resource-inventory.json')
if ($LASTEXITCODE -ne 0) { throw 'Resource inventory query failed.' }
$states = @()
foreach ($entry in $inventory.PSObject.Properties) {
    $resource = az resource show --ids $entry.Value.id -o json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Cannot read resource $($entry.Name)." }
    $states += @{service=$entry.Name;id=$resource.id;state=$resource.properties.provisioningState;publicNetworkAccess=$resource.properties.publicNetworkAccess;disableLocalAuth=$resource.properties.disableLocalAuth;allowSharedKeyAccess=$resource.properties.allowSharedKeyAccess;enableRbacAuthorization=$resource.properties.enableRbacAuthorization;minimumTlsVersion=$resource.properties.minimumTlsVersion;minimalTlsVersion=$resource.properties.minimalTlsVersion}
}
$endpoints = az network private-endpoint list --resource-group $rg --subscription $sub -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Private endpoint inventory failed.' }
$peStates = @($endpoints | ForEach-Object { @{name=$_.name;state=$_.provisioningState;connections=@($_.privateLinkServiceConnections | ForEach-Object { @{serviceId=$_.privateLinkServiceId;groupIds=$_.groupIds;state=$_.privateLinkServiceConnectionState.status} })} })
$allRestricted = @($states | Where-Object {$_.publicNetworkAccess -ne 'Disabled'}).Count -eq 0
$allApproved = $peStates.Count -eq 5 -and @($peStates | Where-Object {$_.state -ne 'Succeeded' -or @($_.connections | Where-Object state -ne 'Approved').Count -gt 0}).Count -eq 0
@{timestamp=[DateTime]::UtcNow.ToString('o');services=$states;privateEndpoints=$peStates;allPublicNetworkAccessDisabled=$allRestricted;allFivePrivateEndpointsApproved=$allApproved} | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $outDir 'foundation-validation.json') -Encoding utf8
Write-Output "All data service public endpoints disabled: $allRestricted"
Write-Output "All five private endpoints approved: $allApproved"
if (!$allRestricted -or !$allApproved) { exit 2 }
