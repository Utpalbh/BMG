@description('Azure region.')
param location string
@description('POC ownership and lifetime tags.')
param tags object
@description('Dedicated GatewaySubnet resource ID; must not have an NSG.')
param gatewaySubnetId string
@description('Public root certificate only, Base64 DER.')
param vpnRootPublicCertificate string

resource publicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  name: 'pip-bmg-poc-vpn'
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Regional' }
  zones: ['1', '2', '3']
  properties: { publicIPAllocationMethod: 'Static', publicIPAddressVersion: 'IPv4' }
}
resource gateway 'Microsoft.Network/virtualNetworkGateways@2024-07-01' = {
  name: 'vgw-bmg-poc'
  location: location
  tags: tags
  properties: {
    gatewayType: 'Vpn'
    vpnType: 'RouteBased'
    vpnGatewayGeneration: 'Generation1'
    activeActive: false
    enableBgp: false
    sku: { name: 'VpnGw1AZ', tier: 'VpnGw1AZ' }
    ipConfigurations: [{
      name: 'gateway-ip-config'
      properties: {
        privateIPAllocationMethod: 'Dynamic'
        subnet: { id: gatewaySubnetId }
        publicIPAddress: { id: publicIp.id }
      }
    }]
    vpnClientConfiguration: {
      vpnClientAddressPool: { addressPrefixes: ['172.28.84.0/24'] }
      vpnClientProtocols: ['OpenVPN']
      vpnAuthenticationTypes: ['Certificate']
      vpnClientRootCertificates: [{ name: 'BMG-POC-VPN-Root', properties: { publicCertData: vpnRootPublicCertificate } }]
      vpnClientRevokedCertificates: []
    }
  }
}
output gatewayId string = gateway.id
