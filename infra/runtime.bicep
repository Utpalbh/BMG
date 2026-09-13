targetScope = 'resourceGroup'
@description('Names from the foundation deployment inventory.')
param openAiAccountName string
param cosmosAccountName string
param workerPrincipalId string
param deploymentName string = 'bmg-gpt5-mini'
param modelName string = 'gpt-5-mini'
param modelVersion string = '2025-08-07'
param capacity int = 30
resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = { name: openAiAccountName }
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' existing = { name: cosmosAccountName }
resource model 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: deploymentName
  sku: { name: 'GlobalStandard', capacity: capacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}
resource inferenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openai
  name: guid(openai.id, workerPrincipalId, 'openai-user')
  properties: {
    principalId: workerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}
resource roleDefinition 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2025-04-15' = {
  parent: cosmos
  name: '6a70bb22-c5d9-4345-a5c9-18c719276c26'
  properties: {
    roleName: 'BMG POC create and read results'
    type: 'CustomRole'
    assignableScopes: [cosmos.id]
    permissions: [{dataActions: [
      'Microsoft.DocumentDB/databaseAccounts/readMetadata'
      'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/create'
      'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/read'
    ]}]
  }
}
resource resultRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, workerPrincipalId, 'bmg-result-writer')
  properties: { principalId: workerPrincipalId, roleDefinitionId: roleDefinition.id, scope: '${cosmos.id}/dbs/bmg-poc/colls/submissions' }
}
output modelDeploymentId string = model.id
