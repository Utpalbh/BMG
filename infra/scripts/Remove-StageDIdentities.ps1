[CmdletBinding(SupportsShouldProcess,ConfirmImpact='High')]
param([switch]$Delete,[string]$RuntimeRoot="$env:USERPROFILE\Documents\BmgPocRuntime")
$ErrorActionPreference='Stop'
$record=Get-Content -Raw -LiteralPath (Join-Path $RuntimeRoot 'azure\stage-d-identity.json') | ConvertFrom-Json
if ($record.tenantId -ne 'e06201f9-0ec7-4863-80fc-85f43be49c1e' -or $record.subscriptionId -ne '6f841b52-7a6d-4287-b0e3-4591621bb363') { throw 'Identity inventory scope mismatch.' }
$account=az account show --subscription $record.subscriptionId -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $account.tenantId -ne $record.tenantId) { throw 'Azure tenant mismatch.' }
foreach ($kind in @('worker','uploader')) {
    $identity=$record.$kind
    $found=az ad app list --filter "appId eq '$($identity.clientId)'" -o json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot verify application inventory.' }
    if (@($found).Count -eq 0) { Write-Output "$kind application is already absent."; continue }
    if (@($found).Count -ne 1 -or $found[0].id -ne $identity.applicationObjectId -or $found[0].displayName -ne "bmg-poc-$kind-wjsvyjg25vqiy") { throw 'Application identity does not match the POC record.' }
    Write-Output "Verified $kind application: $($identity.clientId)"
    if ($Delete -and $PSCmdlet.ShouldProcess($identity.clientId,'Delete the inventoried POC application and its credentials')) {
        az ad app delete --id $identity.applicationObjectId
        if ($LASTEXITCODE -ne 0) { throw 'Application deletion failed.' }
    }
}
$certPath="Cert:\CurrentUser\My\$($record.workerCertificateThumbprint)"
if (Test-Path -LiteralPath $certPath) {
    if ((Get-Item -LiteralPath $certPath).Subject -ne 'CN=BMG-POC-Worker') { throw 'Certificate subject mismatch.' }
    if ($Delete -and $PSCmdlet.ShouldProcess($certPath,'Remove the POC worker certificate and private key')) { Remove-Item -LiteralPath $certPath }
}
if (!$Delete) { Write-Output 'Preview only. Stop the worker and export evidence before using -Delete at final teardown.' }
Write-Output 'The POC resource-group teardown removes scoped role assignments and the vault. Separately verify that the two recorded service principals are absent after application deletion propagates.'
