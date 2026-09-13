param([string]$RuntimeRoot="$env:USERPROFILE/Documents/BmgPocRuntime")
$ErrorActionPreference='Stop'
$record=Get-Content (Join-Path $RuntimeRoot 'azure/stage-d-identity.json') -Raw|ConvertFrom-Json
$sub=$record.subscriptionId
$inventoryPath=if($env:BMG_INVENTORY_PATH){$env:BMG_INVENTORY_PATH}else{Join-Path $PSScriptRoot '../../outputs/stage-c/deployment-inventory.json'}
$inventory=Get-Content $inventoryPath -Raw|ConvertFrom-Json
$rg=($inventory.openAI.id -split '/')[4];$account=$inventory.openAI.name;$cosmos=$inventory.cosmos.name
$worker=$record.worker.servicePrincipalObjectId
$project=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$out=if($env:BMG_EVIDENCE_ROOT){Join-Path $env:BMG_EVIDENCE_ROOT 'stage-f'}else{Join-Path $project 'outputs/stage-f'};New-Item -ItemType Directory -Force $out|Out-Null
$models=az cognitiveservices model list -l eastus2 --subscription $sub -o json|ConvertFrom-Json
$usage=az cognitiveservices usage list -l eastus2 --subscription $sub -o json|ConvertFrom-Json
$model=@($models|Where-Object {$_.model.name -eq 'gpt-5-mini' -and $_.model.version -eq '2025-08-07'})[0]
$quota=@($usage|Where-Object {$_.name.value -eq 'OpenAI.GlobalStandard.gpt-5-mini'})[0]
if (!$model -or 'GlobalStandard' -notin $model.model.skus.name -or !$quota -or $quota.limit-$quota.currentValue -lt 30) {throw 'Model availability or capacity check failed'}
@{model=$model;quota=$quota;checkedAt=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Depth 30|Set-Content "$out/model-preflight.json"
$existing=az cognitiveservices account deployment list -g $rg -n $account --subscription $sub -o json|ConvertFrom-Json
if (!($existing|Where-Object name -eq 'bmg-gpt5-mini')) {
 $body=@{sku=@{name='GlobalStandard';capacity=30};properties=@{model=@{format='OpenAI';name='gpt-5-mini';version='2025-08-07'};versionUpgradeOption='NoAutoUpgrade';raiPolicyName='Microsoft.DefaultV2'}}
 $body|ConvertTo-Json -Depth 8|Set-Content "$out/model-deployment-request.json"
 az rest --method put --url "https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.CognitiveServices/accounts/$account/deployments/bmg-gpt5-mini?api-version=2024-10-01" --body "@$out/model-deployment-request.json" -o none
 if($LASTEXITCODE){throw 'Model deployment failed'}
}
$scope="/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.CognitiveServices/accounts/$account"
az role assignment create --assignee-object-id $worker --assignee-principal-type ServicePrincipal --role '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' --scope $scope --subscription $sub -o none
if($LASTEXITCODE){throw 'OpenAI worker role failed'}
$cosmosScope="/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.DocumentDB/databaseAccounts/$cosmos"
$role=@{Id='6a70bb22-c5d9-4345-a5c9-18c719276c26';RoleName='BMG POC create and read results';Type='CustomRole';AssignableScopes=@($cosmosScope);Permissions=@(@{DataActions=@('Microsoft.DocumentDB/databaseAccounts/readMetadata','Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/create','Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/read')})}
$role|ConvertTo-Json -Depth 6|Set-Content "$out/cosmos-role-definition.json"
az cosmosdb sql role definition create -g $rg -a $cosmos --body "@$out/cosmos-role-definition.json" --subscription $sub -o none
if($LASTEXITCODE){throw 'Cosmos role definition failed'}
az cosmosdb sql role assignment create -g $rg -a $cosmos --role-definition-id '6a70bb22-c5d9-4345-a5c9-18c719276c26' --principal-id $worker --scope '/dbs/bmg-poc/colls/submissions' --subscription $sub -o none
if($LASTEXITCODE){throw 'Cosmos worker role assignment failed'}
az cognitiveservices account deployment show -g $rg -n $account --deployment-name bmg-gpt5-mini --subscription $sub -o json|Set-Content "$out/model-deployment.json"
$doc=Get-Content "$RuntimeRoot/azure/stage-e-config.json" -Raw|ConvertFrom-Json
@{documents=$doc;openAiEndpoint="https://$account.openai.azure.com/";deployment='bmg-gpt5-mini';cosmosEndpoint="https://$cosmos.documents.azure.com/";database='bmg-poc';container='submissions';inputTokenBudget=1000000;outputTokenBudget=300000;maxCompletionTokens=12000;maxInputBytes=120000;cosmosRequestBudget=500}|ConvertTo-Json -Depth 12|Set-Content "$RuntimeRoot/azure/stage-f-config.json"
Write-Output 'Stage F model, scoped identities and configuration prepared.'


