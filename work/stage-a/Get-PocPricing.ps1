$ErrorActionPreference = 'Stop'
$filters = [ordered]@{
    dns = "contains(productName, 'DNS') and priceType eq 'Consumption'"
    network = "(armRegionName eq 'eastus2' or armRegionName eq 'Global') and (serviceName eq 'VPN Gateway' or serviceName eq 'Virtual Network') and priceType eq 'Consumption'"
    documents = "(armRegionName eq 'eastus2' or armRegionName eq 'Global') and (contains(productName, 'Document Intelligence') or contains(productName, 'Form Recognizer')) and priceType eq 'Consumption'"
    llm = "(armRegionName eq 'eastus2' or armRegionName eq 'Global') and (contains(meterName, '4.1') or contains(meterName, '5-mini')) and priceType eq 'Consumption'"
    cosmos = "(armRegionName eq 'eastus2' or armRegionName eq 'Global') and contains(productName, 'Cosmos') and contains(skuName, 'Serverless') and priceType eq 'Consumption'"
    vault = "armRegionName eq 'eastus2' and serviceName eq 'Key Vault' and priceType eq 'Consumption'"
}
$collected = @()
foreach ($category in $filters.Keys) {
    $url = 'https://prices.azure.com/api/retail/prices?currencyCode=INR&$filter=' + [uri]::EscapeDataString($filters[$category])
    $page = 0
    do {
        $reply = Invoke-RestMethod -Uri $url -TimeoutSec 45
        $collected += @($reply.Items)
        $page++
        Write-Output "$category page $page : $($reply.Items.Count) prices"
        $url = $reply.NextPageLink
        if ($page -ge 8 -and $url) { throw "Pricing pagination limit reached for $category; results would be incomplete." }
    } while ($url)
}
$destination = Join-Path $PSScriptRoot 'retail-prices-INR.json'
[ordered]@{ retrievedUtc = [DateTime]::UtcNow.ToString('o'); source = 'https://prices.azure.com/api/retail/prices'; filters = $filters; items = $collected } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $destination -Encoding utf8
Write-Output "Saved $($collected.Count) price records."
