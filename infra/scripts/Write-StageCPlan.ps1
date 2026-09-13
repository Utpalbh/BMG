$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$defs = @(
 @('rg-bmg-poc','Microsoft.Resources/resourceGroups','Resource group',''),
 @('vnet-bmg-poc','Microsoft.Network/virtualNetworks','10.84.0.0/16','rg-bmg-poc'),
 @('dnspr-bmg-poc','Microsoft.Network/dnsResolvers','Inbound only','vnet-bmg-poc'),
 @('dnsin-bmg-poc','Microsoft.Network/dnsResolvers/inboundEndpoints','Static 10.84.2.4','dnspr-bmg-poc'),
 @('pip-bmg-poc-vpn','Microsoft.Network/publicIPAddresses','Standard Static zone redundant','rg-bmg-poc'),
 @('vgw-bmg-poc','Microsoft.Network/virtualNetworkGateways','VpnGw1AZ Generation1','vnet-bmg-poc,pip-bmg-poc-vpn'),
 @('stbmgpoc-SUFFIX','Microsoft.Storage/storageAccounts','Standard_LRS','rg-bmg-poc'),
 @('kv-bmg-SUFFIX','Microsoft.KeyVault/vaults','standard','rg-bmg-poc'),
 @('di-bmg-SUFFIX','Microsoft.CognitiveServices/accounts','FormRecognizer S0','rg-bmg-poc'),
 @('oai-bmg-SUFFIX','Microsoft.CognitiveServices/accounts','OpenAI S0','rg-bmg-poc'),
 @('cosmos-bmg-SUFFIX','Microsoft.DocumentDB/databaseAccounts','Serverless NoSQL','rg-bmg-poc')
)
$refs = @(
 @{title='Private endpoint DNS pairings';url='https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns'},
 @{title='VPN gateway SKUs';url='https://learn.microsoft.com/en-us/azure/vpn-gateway/vpn-gateway-about-vpngateways'},
 @{title='Resolver endpoints';url='https://learn.microsoft.com/en-us/azure/dns/private-resolver-endpoints-rulesets'},
 @{title='Serverless Cosmos';url='https://learn.microsoft.com/en-us/azure/cosmos-db/serverless'},
 @{title='Naming rules';url='https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-name-rules'}
)
$resources = @($defs | ForEach-Object {
 @{name=$_[0];type=$_[1];location='eastus2';sku=$_[2];dependencies=@($_[3].Split(',') | Where-Object {$_});reasoning=@{whyChosen='Approved Stage A private, short-lived synthetic POC foundation.';alternativesConsidered=@('Public access: does not prove the approved private network flow.','Production tiers: unnecessary for a bounded single-laptop POC.');tradeoffs='Managed hourly networking; single-region data services; teardown required.'};references=$refs}
})
$services = @('blob','vault','di','openai','cosmos')
foreach ($service in $services) {
 $resources += @{name="pe-bmg-$service";type='Microsoft.Network/privateEndpoints';location='eastus2';sku='Private endpoint';dependencies=@('vnet-bmg-poc');properties=@{dnsZoneGroup='default';privateDnsZoneLinkRegistrationEnabled=$false};reasoning=@{whyChosen='Private service connectivity through P2S VPN.';alternativesConsidered=@('Public firewall access');tradeoffs='Hourly charge, DNS dependence.'};references=$refs}
}
$plan = @{meta=@{planId='bmg-stage-c';generatedAt=[DateTime]::UtcNow.ToString('o');version='1.0';status='approved';approval='User approved Stage A design/cost context, then explicitly requested Stage C deployment. Existing authorization persists.'};inputs=@{userGoal='Lets proceed with stage C';subGoals=@('Private networking and reproducible teardown','Low-volume synthetic POC, not production availability','Reuse Stage B worker; real adapters remain later stages');insightsApplied=@('approved-stage-a: use approved region, SKUs, network ranges and dedicated new resource group; retain all existing subscription resources')};plan=@{resources=$resources;overallReasoning=@{summary='New isolated RG, VNet, P2S VPN, inbound DNS resolver, five restricted PaaS services and five private endpoints/DNS zones.';tradeoffs='No existing resource is integrated or changed. LRS and single-region serverless Cosmos are deliberate cost choices. No APIM, VM, Firewall, Bastion, or Log Analytics is needed for the single-laptop proof; retain local evidence and Azure Activity Log/platform metrics. No trained classifier/model calls/application identities until later stages. Key Vault purge protection retains a soft-deleted vault for seven days after deletion; do not promise immediate name reuse. VPN public IP is required tunnel ingress, data endpoints stay private. Azure GlobalStandard later permits global processing. Tags state intended expiry but do not enforce automatic deletion.'};validation='Bicep build, Checkov scan, ARM validation/what-if before incremental deployment; live resource/private connectivity validation afterwards.';architecturePrinciples=@('Entra authorization','Private data planes','Non-exportable VPN certificate keys','Deterministic names and incremental deployment','No pre-existing resource changes');references=$refs}}
$plan | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $projectRoot '.azure\infrastructure-plan.json')
