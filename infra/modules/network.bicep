@description('Azure region.')
param location string
@description('POC ownership and lifetime tags.')
param tags object

resource vnet 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  // checkov:skip=CKV_AZURE_182:Approved single-laptop short-lived POC uses one managed resolver inbound endpoint; a second endpoint would add cost without meeting a requested HA target.
  name: 'vnet-bmg-poc'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.84.0.0/16'] }
    // P2S client XML also receives this resolver explicitly after gateway provisioning.
    dhcpOptions: { dnsServers: ['10.84.2.4'] }
    subnets: [
      {
        name: 'GatewaySubnet'
        properties: { addressPrefix: '10.84.0.0/27' }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: '10.84.1.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-dns-inbound'
        properties: {
          addressPrefix: '10.84.2.0/28'
          delegations: [{ name: 'dns-resolver', properties: { serviceName: 'Microsoft.Network/dnsResolvers' } }]
        }
      }
    ]
  }
}
resource resolver 'Microsoft.Network/dnsResolvers@2025-05-01' = {
  name: 'dnspr-bmg-poc'
  location: location
  tags: tags
  properties: { virtualNetwork: { id: vnet.id } }
}
resource inbound 'Microsoft.Network/dnsResolvers/inboundEndpoints@2025-05-01' = {
  parent: resolver
  name: 'dnsin-bmg-poc'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [{
      privateIpAllocationMethod: 'Static'
      privateIpAddress: '10.84.2.4'
      subnet: { id: '${vnet.id}/subnets/snet-dns-inbound' }
    }]
  }
}
output vnetId string = vnet.id
output privateEndpointSubnetId string = '${vnet.id}/subnets/snet-private-endpoints'
output gatewaySubnetId string = '${vnet.id}/subnets/GatewaySubnet'
output dnsResolverAddress string = inbound.properties.ipConfigurations[0].privateIpAddress
