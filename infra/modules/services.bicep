@description('Azure region.')
param location string
@description('POC ownership and lifetime tags.')
param tags object
@description('PE subnet resource ID.')
param privateEndpointSubnetId string
@description('Resolver virtual network ID.')
param vnetId string
@description('Operator object ID for verification roles, removed with RG; AI user roles also permit inference.')
param operatorObjectId string
param nameSalt string = ''

var suffix = empty(nameSalt) ? uniqueString(resourceGroup().id) : uniqueString(resourceGroup().id, nameSalt)
resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  // checkov:skip=CKV_AZURE_36:Private-only runtime intentionally denies trusted-service firewall bypass; any DI training exception is a separate later-stage change.
  // checkov:skip=CKV_AZURE_43:Scanner cannot evaluate uniqueString; ARM-validated name is stbmgpoc plus 13 lowercase alphanumeric characters (21 total).
  // checkov:skip=CKV_AZURE_206:Approved bounded synthetic POC uses Standard_LRS; originals and immutable snapshots are retained locally.
  name: 'stbmgpoc${suffix}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { bypass: 'None', defaultAction: 'Deny', ipRules: [], virtualNetworkRules: [] }
    encryption: {
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
      services: { blob: { enabled: true, keyType: 'Account' }, file: { enabled: true, keyType: 'Account' } }
    }
  }
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
  name: 'default'
  properties: { deleteRetentionPolicy: { enabled: true, days: 1 }, containerDeleteRetentionPolicy: { enabled: true, days: 1 }, isVersioningEnabled: true }
}
resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = [for name in ['training', 'submissions', 'analysis']: {
  parent: blobService
  name: name
  properties: { publicAccess: 'None' }
}]
resource vault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: 'kv-bmg-${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: { bypass: 'None', defaultAction: 'Deny', ipRules: [], virtualNetworkRules: [] }
    accessPolicies: []
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
  }
}
resource di 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'di-bmg-${suffix}'
  location: location
  tags: tags
  kind: 'FormRecognizer'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'di-bmg-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', ipRules: [], virtualNetworkRules: [] }
  }
}
resource openai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'oai-bmg-${suffix}'
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'oai-bmg-${suffix}'
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', ipRules: [], virtualNetworkRules: [] }
  }
}
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' = {
  name: 'cosmos-bmg-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [{ name: 'EnableServerless' }]
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    disableKeyBasedMetadataWriteAccess: true
    isVirtualNetworkFilterEnabled: true
    ipRules: []
    virtualNetworkRules: []
    networkAclBypass: 'None'
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    backupPolicy: { type: 'Periodic', periodicModeProperties: { backupIntervalInMinutes: 240, backupRetentionIntervalInHours: 8, backupStorageRedundancy: 'Local' } }
  }
}
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2025-04-15' = {
  parent: cosmos
  name: 'bmg-poc'
  properties: { resource: { id: 'bmg-poc' } }
}
resource resultContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2025-04-15' = {
  parent: database
  name: 'submissions'
  properties: {
    resource: {
      id: 'submissions'
      partitionKey: { paths: ['/submissionId'], kind: 'Hash', version: 2 }
      indexingPolicy: { indexingMode: 'consistent', automatic: true, includedPaths: [{ path: '/*' }], excludedPaths: [{ path: '/"_etag"/?' }] }
    }
  }
}
var pairs = [
  { name: 'blob', id: storage.id, group: 'blob', zone: 'privatelink.blob.${environment().suffixes.storage}' }
  { name: 'vault', id: vault.id, group: 'vault', zone: 'privatelink.vaultcore.azure.net' }
  { name: 'di', id: di.id, group: 'account', zone: 'privatelink.cognitiveservices.azure.com' }
  { name: 'openai', id: openai.id, group: 'account', zone: 'privatelink.openai.azure.com' }
  { name: 'cosmos', id: cosmos.id, group: 'Sql', zone: 'privatelink.documents.azure.com' }
]
module endpoints './private-endpoint.bicep' = [for pair in pairs: {
  name: 'bmg-pe-${pair.name}'
  params: { location: location, tags: tags, serviceName: pair.name, serviceId: pair.id, groupId: pair.group, zoneName: pair.zone, subnetId: privateEndpointSubnetId, vnetId: vnetId }
}]
resource storageReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, operatorObjectId, 'blob-reader')
  scope: storage
  properties: { principalId: operatorObjectId, principalType: 'User', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1') }
}
resource vaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, operatorObjectId, 'secrets-user')
  scope: vault
  properties: { principalId: operatorObjectId, principalType: 'User', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') }
}
resource diReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(di.id, operatorObjectId, 'cognitive-user')
  scope: di
  properties: { principalId: operatorObjectId, principalType: 'User', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908') }
}
resource openaiReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openai.id, operatorObjectId, 'openai-user')
  scope: openai
  properties: { principalId: operatorObjectId, principalType: 'User', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') }
}
resource cosmosReader 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, operatorObjectId, 'cosmos-reader')
  properties: { principalId: operatorObjectId, roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000001', scope: cosmos.id }
}
output inventory object = {
  storage: { name: storage.name, id: storage.id, endpoint: storage.properties.primaryEndpoints.blob }
  keyVault: { name: vault.name, id: vault.id, endpoint: vault.properties.vaultUri }
  documentIntelligence: { name: di.name, id: di.id, endpoint: di.properties.endpoint, managedIdentityPrincipalId: di.identity.principalId }
  openAI: { name: openai.name, id: openai.id, endpoint: 'https://${openai.name}.openai.azure.com/' }
  cosmos: { name: cosmos.name, id: cosmos.id, endpoint: cosmos.properties.documentEndpoint, database: database.name, container: resultContainer.name }
}
