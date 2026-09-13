$ErrorActionPreference='Stop'
$sub='6f841b52-7a6d-4287-b0e3-4591621bb363'
$path="$env:USERPROFILE/Documents/BmgPocRuntime/azure/stage-d-identity.json"
$record=Get-Content -Raw $path | ConvertFrom-Json -AsHashtable
if ($record.uploader.applicationObjectId -ne 'ba7c449f-d05c-45a8-acdd-d3c631ec575d') { throw 'Unexpected uploader identity' }
$vault='/subscriptions/'+$sub+'/resourceGroups/rg-bmg-poc/providers/Microsoft.KeyVault/vaults/kv-bmg-wjsvyjg25vqiy'
$roleId=[guid]::NewGuid().ToString()
$rolePath="$vault/secrets/bmg-uploader-client-secret/providers/Microsoft.Authorization/roleAssignments/$roleId"
$oldKey=$record.uploader.passwordKeyId
$graphToken=az account get-access-token --subscription $sub --resource https://graph.microsoft.com --query accessToken -o tsv
if ($LASTEXITCODE) { throw 'Graph token unavailable' }
$headers=@{Authorization="Bearer $graphToken"}
$appUri="https://graph.microsoft.com/v1.0/applications/$($record.uploader.applicationObjectId)"
$app=Invoke-RestMethod -Uri $appUri -Headers $headers
if ($app.appId -ne $record.uploader.clientId) { throw 'Uploader identity mismatch' }
az role assignment create --name $roleId --assignee-object-id '72ecc7b4-9bca-425f-9816-2562b5ab1ba7' --assignee-principal-type User --role 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7' --scope "$vault/secrets/bmg-uploader-client-secret" --subscription $sub -o none
if ($LASTEXITCODE) { throw 'Temporary role failed' }
$stored=$false
try {
 $expiry=[DateTime]::UtcNow.AddHours(12)
 $password=Invoke-RestMethod -Method Post -Uri "$appUri/addPassword" -Headers $headers -ContentType 'application/json' -Body (@{passwordCredential=@{displayName='BMG Stage E bounded upload';endDateTime=$expiry.ToString('o')}}|ConvertTo-Json)
 $vaultToken=az account get-access-token --subscription $sub --resource https://vault.azure.net --query accessToken -o tsv
 if ($LASTEXITCODE) { throw 'Vault token unavailable' }
 $body=@{value=$password.secretText;attributes=@{enabled=$true;exp=([DateTimeOffset]$expiry).ToUnixTimeSeconds()};tags=@{project='BMG-POC';purpose='AzCopy uploader';clientId=$record.uploader.clientId}}|ConvertTo-Json -Depth 5 -Compress
 for($i=0;$i -lt 12;$i++) {
  try { $response=Invoke-RestMethod -Method Put -Uri 'https://kv-bmg-wjsvyjg25vqiy.vault.azure.net/secrets/bmg-uploader-client-secret?api-version=7.4' -Headers @{Authorization="Bearer $vaultToken"} -ContentType 'application/json' -Body $body; $stored=$true;break }
  catch { if ([int]$_.Exception.Response.StatusCode -ne 403 -or $i -eq 11) { throw 'Credential storage failed; value suppressed' }; Start-Sleep -Seconds 10 }
 }
 $record.uploader.passwordKeyId=$password.keyId
 $record.uploader.credentialExpiresAt=$expiry.ToString('o')
 $record.secretVersionId=$response.id
 $record.secretStored=$true
 $record|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $path
 Invoke-RestMethod -Method Post -Uri "$appUri/removePassword" -Headers $headers -ContentType 'application/json' -Body (@{keyId=$oldKey}|ConvertTo-Json)|Out-Null
} finally {
 if (!$stored -and $password.keyId) { Invoke-RestMethod -Method Post -Uri "$appUri/removePassword" -Headers $headers -ContentType 'application/json' -Body (@{keyId=$password.keyId}|ConvertTo-Json)|Out-Null }
 $password=$null;$body=$null;$response=$null;$vaultToken=$null
 az role assignment delete --ids $rolePath --subscription $sub -o none
 if ($LASTEXITCODE) { throw 'Temporary role cleanup failed' }
}
@{rotatedAt=[DateTime]::UtcNow.ToString('o');credentialExpiresAt=$expiry.ToString('o');oldCredentialRemoved=$true;temporaryRoleRemoved=$true;secretStoredOnlyInKeyVault=$true}|ConvertTo-Json|Set-Content "$PSScriptRoot/../../outputs/stage-e/credential-rotation.json"
Write-Output 'Uploader credential rotated; previous credential and temporary permission removed.'
