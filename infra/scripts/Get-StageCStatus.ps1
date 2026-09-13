[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$sub = '6f841b52-7a6d-4287-b0e3-4591621bb363'
az deployment sub show --name bmg-stage-c --subscription $sub --query '{state:properties.provisioningState,error:properties.error}' -o json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
az resource list --resource-group rg-bmg-poc --subscription $sub --query '[].{name:name,type:type}' -o table
az network vnet-gateway show --resource-group rg-bmg-poc --name vgw-bmg-poc --subscription $sub --query '{state:provisioningState,sku:sku.name,vpnType:vpnType,protocols:vpnClientConfiguration.vpnClientProtocols}' -o json
