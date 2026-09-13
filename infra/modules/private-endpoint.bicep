@description('Azure region.')
param location string
@description('POC ownership and lifetime tags.')
param tags object
@description('Short logical service name.')
param serviceName string
@description('Target PaaS resource ID.')
param serviceId string
@description('Private Link group ID, case sensitive.')
param groupId string
@description('Private DNS zone FQDN.')
param zoneName string
@description('Private endpoint subnet resource ID.')
param subnetId string
@description('Resolver virtual network ID.')
param vnetId string

resource zone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: zoneName
  location: 'global'
  tags: tags
}
resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: 'bmg-vnet-link'
  location: 'global'
  tags: tags
  properties: { registrationEnabled: false, virtualNetwork: { id: vnetId } }
}
resource endpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  name: 'pe-bmg-${serviceName}'
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [{
      name: 'bmg-${serviceName}'
      properties: { privateLinkServiceId: serviceId, groupIds: [groupId] }
    }]
  }
}
resource group 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = {
  parent: endpoint
  name: 'default'
  properties: { privateDnsZoneConfigs: [{ name: serviceName, properties: { privateDnsZoneId: zone.id } }] }
}
output endpointId string = endpoint.id
