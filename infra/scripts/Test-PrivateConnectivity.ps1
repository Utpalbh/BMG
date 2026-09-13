[CmdletBinding()]
param(
    [ValidateSet('Connected','Disconnected')][string]$Mode,
    [string]$InventoryPath = (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'outputs\stage-c\deployment-inventory.json')
)
$ErrorActionPreference = 'Stop'
if (!$Mode) { throw 'Specify -Mode Connected or -Mode Disconnected to label the evidence.' }
$sub = '6f841b52-7a6d-4287-b0e3-4591621bb363'
$inventory = Get-Content -Raw -LiteralPath $InventoryPath | ConvertFrom-Json
$targets = @(
    @{name='Blob';endpoint=$inventory.storage.endpoint;path='?comp=list';audience='https://storage.azure.com/';headers=@{'x-ms-version'='2023-11-03'}},
    @{name='KeyVault';endpoint=$inventory.keyVault.endpoint;path='secrets?api-version=7.4';audience='https://vault.azure.net';headers=@{}},
    @{name='DocumentIntelligence';endpoint=$inventory.documentIntelligence.endpoint;path='documentintelligence/info?api-version=2024-11-30';audience='https://cognitiveservices.azure.com/';headers=@{}},
    @{name='OpenAI';endpoint=$inventory.openAI.endpoint;path='openai/models?api-version=2024-10-21';audience='https://cognitiveservices.azure.com/';headers=@{}},
    @{name='Cosmos';endpoint=$inventory.cosmos.endpoint;path='dbs';audience='https://cosmos.azure.com/';headers=@{'x-ms-version'='2018-12-31'}}
)
$tokens = @{}
$results = @()
foreach ($target in $targets) {
    $hostName = ([uri]$target.endpoint).DnsSafeHost
    $addresses = @()
    $dnsError = $null
    try { $addresses = @(Resolve-DnsName -Name $hostName -Type A -DnsOnly -ErrorAction Stop | Where-Object IPAddress | Select-Object -ExpandProperty IPAddress) } catch { $dnsError = $_.Exception.Message }
    $resolverAddresses = @()
    if ($Mode -eq 'Connected') {
        try { $resolverAddresses = @(Resolve-DnsName -Name $hostName -Server '10.84.2.4' -Type A -DnsOnly -QuickTimeout -ErrorAction Stop | Where-Object IPAddress | Select-Object -ExpandProperty IPAddress) } catch { $dnsError = $_.Exception.Message }
    }
    if (!$tokens.ContainsKey($target.audience)) {
        # Capture in process memory only. Never print tokens or enable an HTTP debug trace.
        $token = az account get-access-token --subscription $sub --resource $target.audience --query accessToken -o tsv
        if ($LASTEXITCODE -ne 0 -or !$token) { throw "Could not acquire operator token for $($target.name)." }
        $tokens[$target.audience] = $token
    }
    $headers = $target.headers.Clone()
    if ($target.name -eq 'Cosmos') {
        $headers['Authorization'] = [uri]::EscapeDataString("type=aad&ver=1.0&sig=$($tokens[$target.audience])")
        $headers['x-ms-date'] = [DateTime]::UtcNow.ToString('r')
    } else { $headers['Authorization'] = 'Bearer ' + $tokens[$target.audience] }
    $status = $null
    $errorCode = $null
    try {
        $response = Invoke-WebRequest -Uri ($target.endpoint.TrimEnd('/') + '/' + $target.path) -Headers $headers -TimeoutSec 20 -UseBasicParsing
        $status = [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        # Error bodies can distinguish firewall denial from authorization denial. No request headers are saved.
        $errorCode = $_.ErrorDetails.Message
        if ($errorCode -and $errorCode.Length -gt 2000) { $errorCode = $errorCode.Substring(0,2000) }
    }
    $privateDns = $addresses.Count -gt 0 -and @($addresses | Where-Object {$_ -notlike '10.84.1.*'}).Count -eq 0
    $passed = if ($Mode -eq 'Connected') { $privateDns -and $resolverAddresses.Count -gt 0 -and $status -eq 200 } else { $status -eq 403 }
    $results += [ordered]@{service=$target.name;host=$hostName;systemDnsAddresses=$addresses;resolverDnsAddresses=$resolverAddresses;dnsError=$dnsError;httpStatus=$status;errorBody=$errorCode;passed=$passed}
    Write-Output "$($target.name): HTTP $status; DNS $($addresses -join ','); passed=$passed"
}
$tokens.Clear()
$resultPath = Join-Path (Split-Path $InventoryPath -Parent) ("connectivity-" + $Mode.ToLowerInvariant() + '.json')
@{mode=$Mode;timestamp=[DateTime]::UtcNow.ToString('o');results=$results;allPassed=(@($results | Where-Object {!$_.passed}).Count -eq 0)} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $resultPath -Encoding utf8
if (@($results | Where-Object {!$_.passed}).Count -gt 0) { exit 2 }
