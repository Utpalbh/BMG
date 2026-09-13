[CmdletBinding()]
param(
 [Parameter(Mandatory)][ValidateSet('Preflight','Foundation','Inventory','Identity','Train','Model','Run')][string]$Action,
 [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_-]{1,40}$')][string]$Session,
 [string]$SubscriptionId='6f841b52-7a6d-4287-b0e3-4591621bb363',
 [string]$TenantId='e06201f9-0ec7-4863-80fc-85f43be49c1e',
 [string]$RuntimeRoot="$env:USERPROFILE/Documents/BmgPocRecreated/$Session",
 [string]$PythonExe='python'
)
$ErrorActionPreference='Stop'
$project=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$azRoot=Join-Path $RuntimeRoot 'azure';$evidence=Join-Path $RuntimeRoot 'evidence'
New-Item -ItemType Directory -Force $azRoot,$evidence|Out-Null
$env:BMG_SUBSCRIPTION_ID=$SubscriptionId;$env:BMG_TENANT_ID=$TenantId
$env:BMG_INVENTORY_PATH=Join-Path $azRoot 'deployment-inventory.json';$env:BMG_EVIDENCE_ROOT=$evidence
$configPath=Join-Path $azRoot 'recreate-session.json'
$saved=@{session=$Session;subscriptionId=$SubscriptionId;tenantId=$TenantId;resourceGroup='rg-bmg-poc';runtimeRoot=[IO.Path]::GetFullPath($RuntimeRoot)}
if(Test-Path $configPath){$prior=Get-Content $configPath -Raw|ConvertFrom-Json; if($prior.session -ne $Session -or $prior.subscriptionId -ne $SubscriptionId -or $prior.tenantId -ne $TenantId){throw 'Session configuration mismatch'}}else{$saved|ConvertTo-Json|Set-Content $configPath}
function AzCheck { if($LASTEXITCODE -ne 0){throw 'Azure CLI operation failed; inspect retained evidence before retry'} }
$account=az account show --subscription $SubscriptionId -o json|ConvertFrom-Json;AzCheck
if($account.tenantId -ne $TenantId){throw 'Wrong Azure tenant'}
az account set --subscription $SubscriptionId;AzCheck
if($Action -eq 'Preflight'){
 & "$env:USERPROFILE/Documents/BmgPocTools/dotnet/dotnet.exe" --version
 if($LASTEXITCODE){throw 'Install the pinned .NET SDK first'}
 & $PythonExe --version
 if($LASTEXITCODE){throw 'Python is required'}
 if(@(Get-ChildItem "$env:USERPROFILE/Documents/BmgPocTools/azcopy" -Recurse -Filter azcopy.exe).Count -ne 1){throw 'Install exactly one pinned AzCopy executable'}
 az bicep build --file (Join-Path $project 'infra/main.bicep') --outfile (Join-Path $azRoot 'main.json');AzCheck
 Write-Output 'Local prerequisites and login checked. No Azure resources created.';return
}
if($Action -eq 'Foundation'){
 $exists=az group exists -n rg-bmg-poc --subscription $SubscriptionId -o tsv;AzCheck
 if($exists -eq 'true'){
  $g=az group show -n rg-bmg-poc --subscription $SubscriptionId -o json|ConvertFrom-Json;AzCheck
  if($g.tags.managedBy -ne 'BMG-StageC-Bicep' -or $g.tags.project -ne 'BMG-POC'){throw 'Existing group is not the inventoried POC'}
  if(!(Test-Path (Join-Path $azRoot 'foundation-submitted.json'))){throw 'POC group already exists: do not add another session to it. Resume its original session or finish approved teardown first.'}
 }
 & "$PSScriptRoot/New-PocVpnCertificates.ps1" -RuntimeRoot $RuntimeRoot
 $cert=Get-Content (Join-Path $azRoot 'vpn-certificates.json') -Raw|ConvertFrom-Json
 $operator=az ad signed-in-user show --query id -o tsv;AzCheck
 $paramsPath=Join-Path $azRoot 'foundation.parameters.json'
 if(!(Test-Path $paramsPath)){
  $now=[DateTime]::UtcNow
  @{'$schema'='https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#';contentVersion='1.0.0.0';parameters=@{location=@{value='eastus2'};resourceGroupName=@{value='rg-bmg-poc'};sessionStartedAt=@{value=$now.ToString('o')};expiresAt=@{value=$now.AddHours(3).ToString('o')};vpnRootPublicCertificate=@{value=$cert.rootPublicCertificateData};operatorObjectId=@{value=$operator};nameSalt=@{value=$Session}}}|ConvertTo-Json -Depth 10|Set-Content $paramsPath
 }
 az deployment sub validate --name "bmg-$Session" --location eastus2 --subscription $SubscriptionId --template-file "$project/infra/main.bicep" --parameters "@$paramsPath" -o none;AzCheck
 az deployment sub what-if --name "bmg-$Session" --location eastus2 --subscription $SubscriptionId --template-file "$project/infra/main.bicep" --parameters "@$paramsPath" --no-pretty-print -o json|Set-Content (Join-Path $azRoot 'what-if.json');AzCheck
 $preview=Get-Content (Join-Path $azRoot 'what-if.json') -Raw|ConvertFrom-Json
 if(@($preview.changes|Where-Object changeType -eq Delete).Count){throw 'Unexpected deletions in preview'}
 if(@($preview.changes|Where-Object {$_.changeType -eq 'Modify' -and $_.resourceId -notlike "/subscriptions/$SubscriptionId/resourceGroups/rg-bmg-poc*"}).Count){throw 'Preview modifies resources outside POC group'}
 @{submittedUtc=[DateTime]::UtcNow.ToString('o');session=$Session}|ConvertTo-Json|Set-Content (Join-Path $azRoot 'foundation-submitted.json')
 az deployment sub create --name "bmg-$Session" --location eastus2 --subscription $SubscriptionId --template-file "$project/infra/main.bicep" --parameters "@$paramsPath" --no-wait -o none;AzCheck
 Write-Output "Submitted. Check: az deployment sub show -n bmg-$Session --query properties.provisioningState";return
}
if($Action -eq 'Inventory'){
 $state=az deployment sub show -n "bmg-$Session" --query properties.provisioningState -o tsv;AzCheck
 if($state -ne 'Succeeded'){throw "Foundation is $state; wait before continuing"}
 $i=az deployment group show -g rg-bmg-poc -n bmg-services --query properties.outputs.inventory.value -o json|ConvertFrom-Json;AzCheck
 $i|ConvertTo-Json -Depth 12|Set-Content $env:BMG_INVENTORY_PATH
 az network vnet-gateway vpn-client generate -g rg-bmg-poc -n vgw-bmg-poc --authentication-method EAPTLS -o tsv|Set-Content (Join-Path $azRoot 'vpn-download-url.local.txt');AzCheck
 Write-Output 'Inventory saved. Download the generated VPN ZIP, import its AzureVPN XML in Azure VPN Client, select the new session certificate, then connect. The generated download URL is temporary and must not be committed.';return
}
if(!(Test-Path $env:BMG_INVENTORY_PATH)){throw 'Run Inventory first'}
$inventory=Get-Content $env:BMG_INVENTORY_PATH -Raw|ConvertFrom-Json
foreach($endpoint in @($inventory.keyVault.endpoint,$inventory.documentIntelligence.endpoint,$inventory.openAI.endpoint,$inventory.cosmos.endpoint,$inventory.storage.endpoint)){
 $ips=[Net.Dns]::GetHostAddresses(([Uri]$endpoint).Host)
 if(!$ips -or @($ips|Where-Object {!$_.ToString().StartsWith('10.84.1.')}).Count){throw 'Connect the POC VPN and verify private DNS before continuing'}
}
if($Action -eq 'Identity'){
 & "$PSScriptRoot/Initialize-StageDIdentity.ps1" -RuntimeRoot $RuntimeRoot
 $upload=Get-Content (Join-Path $azRoot 'stage-d-config.json') -Raw|ConvertFrom-Json
 @{upload=$upload;documentIntelligenceEndpoint=$inventory.documentIntelligence.endpoint;classifierId='bmg-stage-e-v1';classificationThreshold=0.8;maximumDocumentPages=20;classificationPageBudget=120;layoutPageBudget=120}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $azRoot 'stage-e-config.json');return
}
if($Action -eq 'Train'){
 $identity=Get-Content (Join-Path $azRoot 'stage-d-identity.json') -Raw|ConvertFrom-Json
 $operator=az ad signed-in-user show --query id -o tsv;AzCheck
 $settings=Join-Path $azRoot 'training-settings.json'
 @{subscriptionId=$SubscriptionId;tenantId=$TenantId;storageId=$inventory.storage.id;documentIntelligenceId=$inventory.documentIntelligence.id;documentIntelligenceEndpoint=$inventory.documentIntelligence.endpoint;blobEndpoint=$inventory.storage.endpoint;operatorObjectId=$operator;documentIntelligencePrincipalId=$inventory.documentIntelligence.managedIdentityPrincipalId;workerPrincipalId=$identity.worker.servicePrincipalObjectId;outputDirectory=(Join-Path $evidence 'stage-e')}|ConvertTo-Json|Set-Content $settings
 $env:BMG_TRAIN_SETTINGS=$settings
 & $PythonExe "$project/prototype/scripts/train_stage_e.py"
 if($LASTEXITCODE){throw 'Training failed; retain operations and inspect evidence'};return
}
if($Action -eq 'Model'){& "$PSScriptRoot/Initialize-StageF.ps1" -RuntimeRoot $RuntimeRoot;return}
if($Action -eq 'Run'){
 & "$project/prototype/scripts/Build-Local.ps1"
 & "$project/prototype/scripts/Start-AzureFullWorker.ps1" -RuntimeRoot (Join-Path $RuntimeRoot 'full-flow') -Configuration (Join-Path $azRoot 'stage-f-config.json')
}
