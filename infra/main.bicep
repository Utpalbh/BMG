targetScope = 'subscription'

@description('Approved deployment region.')
param location string = 'eastus2'
@description('Dedicated POC resource group.')
param resourceGroupName string = 'rg-bmg-poc'
@description('UTC session start, recorded once and retained for reruns.')
param sessionStartedAt string
@description('Intended UTC expiry; informational tag, not an automatic deletion timer.')
param expiresAt string
@description('Public Base64 DER VPN root certificate; contains no private key.')
param vpnRootPublicCertificate string
@description('Signed-in operator object ID for foundation checks; AI user roles also permit inference.')
param operatorObjectId string
@description('Optional fresh-session salt to avoid names retained by Key Vault/Cognitive Services soft delete. Empty preserves the original names.')
param nameSalt string = ''

var tags = {
  project: 'BMG-POC'
  managedBy: 'BMG-StageC-Bicep'
  environment: 'synthetic-poc'
  sessionStartedAt: sessionStartedAt
  expiresAt: expiresAt
}
resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}
module network './modules/network.bicep' = {
  name: 'bmg-network'
  scope: rg
  params: { location: location, tags: tags }
}
module services './modules/services.bicep' = {
  name: 'bmg-services'
  scope: rg
  params: {
    location: location
    tags: tags
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    vnetId: network.outputs.vnetId
    operatorObjectId: operatorObjectId
    nameSalt: nameSalt
  }
}
module gateway './modules/gateway.bicep' = {
  name: 'bmg-gateway'
  scope: rg
  params: {
    location: location
    tags: tags
    gatewaySubnetId: network.outputs.gatewaySubnetId
    vpnRootPublicCertificate: vpnRootPublicCertificate
  }
}
output resourceGroupId string = rg.id
output serviceInventory object = services.outputs.inventory
output dnsResolverAddress string = network.outputs.dnsResolverAddress
output gatewayId string = gateway.outputs.gatewayId
output vnetId string = network.outputs.vnetId
