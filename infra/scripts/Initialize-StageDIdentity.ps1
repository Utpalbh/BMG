[CmdletBinding()]
param([string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$sub = if($env:BMG_SUBSCRIPTION_ID){$env:BMG_SUBSCRIPTION_ID}else{'6f841b52-7a6d-4287-b0e3-4591621bb363'}
$tenant = if($env:BMG_TENANT_ID){$env:BMG_TENANT_ID}else{'e06201f9-0ec7-4863-80fc-85f43be49c1e'}
$inventoryPath=if($env:BMG_INVENTORY_PATH){$env:BMG_INVENTORY_PATH}else{Join-Path $projectRoot 'outputs/stage-c/deployment-inventory.json'}
$inventory=Get-Content -Raw -LiteralPath $inventoryPath|ConvertFrom-Json
$identitySuffix=$inventory.storage.name.Substring('stbmgpoc'.Length)
$directory = Join-Path $RuntimeRoot 'azure'
$recordPath = Join-Path $directory 'stage-d-identity.json'
New-Item -ItemType Directory -Force -Path $directory,(Join-Path $projectRoot 'outputs\stage-d') | Out-Null
$graphToken = az account get-access-token --subscription $sub --resource https://graph.microsoft.com --query accessToken -o tsv
if ($LASTEXITCODE -ne 0 -or !$graphToken) { throw 'Cannot obtain directory setup token.' }
$graphHeaders = @{Authorization="Bearer $graphToken"}
function Graph([string]$Method,[string]$Path,$Body) {
    $arguments=@{Method=$Method;Uri="https://graph.microsoft.com/v1.0/$Path";Headers=$graphHeaders;ContentType='application/json'}
    if ($null -ne $Body) { $arguments.Body=($Body | ConvertTo-Json -Depth 15 -Compress) }
    Invoke-RestMethod @arguments
}
if (Test-Path -LiteralPath $recordPath) { $record=Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json -AsHashtable }
else { $record=@{tenantId=$tenant;subscriptionId=$sub;createdAt=[DateTime]::UtcNow.ToString('o');secretName='bmg-uploader-client-secret';worker=$null;uploader=$null;secretStored=$false} }
function SaveRecord { $record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $recordPath -Encoding utf8 }
if (!$record.workerCertificateThumbprint) {
    $certificate=New-SelfSignedCertificate -Type Custom -Subject 'CN=BMG-POC-Worker' -KeySpec Signature -KeyExportPolicy NonExportable -HashAlgorithm sha256 -KeyLength 2048 -CertStoreLocation 'Cert:\CurrentUser\My' -NotAfter (Get-Date).AddDays(7)
    $record.workerCertificateThumbprint=$certificate.Thumbprint
    SaveRecord
}
$certificate=Get-Item -LiteralPath "Cert:\CurrentUser\My\$($record.workerCertificateThumbprint)"
foreach ($roleName in @('worker','uploader')) {
    $displayName="bmg-poc-$roleName-$identitySuffix"
    if (!$record[$roleName]) {
        $existing = az ad app list --display-name $displayName --query '[].id' -o json | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or @($existing).Count -gt 0) { throw "Uninventoried application named $displayName already exists; inspect ownership before reuse." }
        $body=@{displayName=$displayName;signInAudience='AzureADMyOrg';requiredResourceAccess=@()}
        if ($roleName -eq 'worker') {
            $body.keyCredentials=@(@{type='AsymmetricX509Cert';usage='Verify';key=[Convert]::ToBase64String($certificate.RawData);displayName='BMG-POC-Worker';startDateTime=$certificate.NotBefore.ToUniversalTime().ToString('o');endDateTime=$certificate.NotAfter.ToUniversalTime().ToString('o')})
        }
        $application=Graph 'POST' 'applications' $body
        $record[$roleName]=@{applicationObjectId=$application.id;clientId=$application.appId;displayName=$displayName;servicePrincipalObjectId=$null}
        SaveRecord
    }
    if (!$record[$roleName].servicePrincipalObjectId) {
        $principal=Graph 'POST' 'servicePrincipals' @{appId=$record[$roleName].clientId}
        $record[$roleName].servicePrincipalObjectId=$principal.id
        SaveRecord
    }
}
$secretScope="$($inventory.keyVault.id)/secrets/$($record.secretName)"
$blobScope="$($inventory.storage.id)/blobServices/default/containers/submissions"
az role assignment create --assignee-object-id $record.worker.servicePrincipalObjectId --assignee-principal-type ServicePrincipal --role '4633458b-17de-408a-b874-0445c86b69e6' --scope $secretScope --subscription $sub -o none
if ($LASTEXITCODE -ne 0) { throw 'Worker secret-scoped role assignment failed.' }
az role assignment create --assignee-object-id $record.uploader.servicePrincipalObjectId --assignee-principal-type ServicePrincipal --role 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' --scope $blobScope --subscription $sub -o none
if ($LASTEXITCODE -ne 0) { throw 'Uploader container role assignment failed.' }
if (!$record.secretStored) {
    $operatorId=az ad signed-in-user show --query id -o tsv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot identify setup operator.' }
    $temporaryId=([guid]::NewGuid()).ToString()
    $record.temporarySetupRoleId="$($inventory.keyVault.id)/providers/Microsoft.Authorization/roleAssignments/$temporaryId"
    SaveRecord
    az role assignment create --name $temporaryId --assignee-object-id $operatorId --assignee-principal-type User --role 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7' --scope $inventory.keyVault.id --subscription $sub -o none
    if ($LASTEXITCODE -ne 0) { throw 'Temporary vault setup permission failed.' }
    try {
        # No secret is written to disk, printed, or used as a process argument.
        $expires=[DateTime]::UtcNow.AddHours(12)
        $password=Graph 'POST' "applications/$($record.uploader.applicationObjectId)/addPassword" @{passwordCredential=@{displayName='BMG bounded POC upload';endDateTime=$expires.ToString('o')}}
        $record.uploader.passwordKeyId=$password.keyId
        $record.uploader.credentialExpiresAt=$expires.ToString('o')
        SaveRecord
        $vaultToken=az account get-access-token --subscription $sub --resource https://vault.azure.net --query accessToken -o tsv
        if ($LASTEXITCODE -ne 0) { throw 'Vault setup token acquisition failed.' }
        $secretBody=@{value=$password.secretText;attributes=@{enabled=$true;exp=([DateTimeOffset]$expires).ToUnixTimeSeconds()};tags=@{project='BMG-POC';purpose='AzCopy uploader';clientId=$record.uploader.clientId}} | ConvertTo-Json -Depth 8 -Compress
        $stored=$false
        for ($attempt=0; $attempt -lt 12; $attempt++) {
            try {
                $response=Invoke-RestMethod -Method Put -Uri "$($inventory.keyVault.endpoint.TrimEnd('/'))/secrets/$($record.secretName)?api-version=7.4" -Headers @{Authorization="Bearer $vaultToken"} -ContentType 'application/json' -Body $secretBody
                $record.secretVersionId=$response.id
                $stored=$true; break
            } catch {
                if ([int]$_.Exception.Response.StatusCode -ne 403 -or $attempt -eq 11) { throw 'Vault secret write failed; secret value was not logged.' }
                Start-Sleep -Seconds 10
            }
        }
        if (!$stored) { throw 'Could not store uploader credential.' }
        $record.secretStored=$true
        SaveRecord
    } finally {
        $password=$null; $secretBody=$null; $response=$null; $vaultToken=$null
        az role assignment delete --ids $record.temporarySetupRoleId --subscription $sub -o none
        if ($LASTEXITCODE -eq 0) { $record.temporarySetupRoleRemoved=$true; SaveRecord }
    }
}
$azcopy = @(Get-ChildItem -LiteralPath "$env:USERPROFILE\Documents\BmgPocTools\azcopy" -Recurse -File -Filter azcopy.exe)
if ($azcopy.Count -ne 1) { throw 'Expected exactly one pinned AzCopy executable.' }
$config=@{tenantId=$tenant;workerClientId=$record.worker.clientId;workerCertificateThumbprint=$record.workerCertificateThumbprint;keyVaultUri=$inventory.keyVault.endpoint;uploaderSecretName=$record.secretName;uploaderClientId=$record.uploader.clientId;blobServiceUri=$inventory.storage.endpoint;container='submissions';azCopyPath=$azcopy[0].FullName;azCopySha256=(Get-FileHash -LiteralPath $azcopy[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
$config | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $directory 'stage-d-config.json') -Encoding utf8
$record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $directory 'identity-inventory-public.json') -Encoding utf8
Write-Output 'Stage D identities, scoped roles and expiring Key Vault credential configured. No secret values were written to local files.'

