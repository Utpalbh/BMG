[CmdletBinding()]
param([string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime")
$ErrorActionPreference = 'Stop'
$pocDir = Join-Path $RuntimeRoot 'azure'
New-Item -ItemType Directory -Force -Path $pocDir | Out-Null
$inventoryPath = Join-Path $pocDir 'vpn-certificates.json'
if (Test-Path -LiteralPath $inventoryPath) {
    $saved = Get-Content -Raw -LiteralPath $inventoryPath | ConvertFrom-Json
    foreach ($thumb in @($saved.rootThumbprint, $saved.clientThumbprint)) {
        $cert = Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumb"
        if (!$cert.HasPrivateKey -or $cert.NotAfter -lt (Get-Date).AddHours(12)) { throw 'Recorded VPN certificate is unusable.' }
    }
    Write-Output 'Existing POC VPN certificates verified.'
    return
}
$expiry = (Get-Date).AddDays(7)
$root = New-SelfSignedCertificate -Type Custom -KeySpec Signature -Subject 'CN=BMG-POC-VPN-Root' -KeyExportPolicy NonExportable -HashAlgorithm sha256 -KeyLength 2048 -CertStoreLocation 'Cert:\CurrentUser\My' -KeyUsageProperty Sign -KeyUsage CertSign -NotAfter $expiry
$client = New-SelfSignedCertificate -Type Custom -DnsName 'BMG-POC-VPN-Client' -KeySpec Signature -Subject 'CN=BMG-POC-VPN-Client' -KeyExportPolicy NonExportable -HashAlgorithm sha256 -KeyLength 2048 -CertStoreLocation 'Cert:\CurrentUser\My' -Signer $root -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.2') -NotAfter $expiry
# Only the public root certificate is sent to Azure. Private keys stay non-exportable in CurrentUser\My.
[ordered]@{
    rootThumbprint = $root.Thumbprint
    clientThumbprint = $client.Thumbprint
    rootSubject = $root.Subject
    clientSubject = $client.Subject
    expiresAt = $expiry.ToUniversalTime().ToString('o')
    rootPublicCertificateData = [Convert]::ToBase64String($root.RawData)
    privateKeysExported = $false
} | ConvertTo-Json | Set-Content -LiteralPath $inventoryPath -Encoding utf8
Write-Output 'Created separate seven-day POC VPN root and client certificates; private keys were not exported.'
