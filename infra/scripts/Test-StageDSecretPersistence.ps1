param()
$ErrorActionPreference='Stop'
$project=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$record=Get-Content -Raw -LiteralPath (Join-Path $project 'outputs\stage-d\identity-inventory.json') | ConvertFrom-Json
$report=Get-Content -Raw -LiteralPath (Join-Path $project 'outputs\stage-d\azure-upload-results.json') | ConvertFrom-Json
$roots=@($report.runtimeRoot,"$env:USERPROFILE\Documents\BmgPocRuntime\stage-d",(Join-Path $project 'outputs\stage-d'))
# Setup-time audit uses the operator's existing read permission; the running worker never uses Azure CLI authentication.
$secret=az keyvault secret show --id $record.secretVersionId --query value -o tsv
if ($LASTEXITCODE -ne 0 -or !$secret) { throw 'Cannot acquire the in-memory audit value.' }
$findings=@();$count=0
try {
    foreach ($root in $roots) {
        foreach ($file in (Get-ChildItem -LiteralPath $root -File -Recurse)) {
            if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Audit root contains a reparse point.' }
            if ($file.Length -gt 200MB) { throw 'Audit file exceeds bounded scan size.' }
            $bytes=[System.IO.File]::ReadAllBytes($file.FullName)
            $utf8=[System.Text.Encoding]::UTF8.GetString($bytes)
            $utf16=[System.Text.Encoding]::Unicode.GetString($bytes)
            if ($utf8.Contains($secret) -or $utf16.Contains($secret) -or $utf8.Contains([uri]::EscapeDataString($secret))) { $findings += $file.FullName }
            $count++
        }
    }
} finally { $secret=$null;$utf8=$null;$utf16=$null;$bytes=$null }
@{timestamp=[DateTime]::UtcNow.ToString('o');filesScanned=$count;roots=$roots;secretValueMatches=$findings.Count;files=$findings;scope='Checks plaintext UTF-8, UTF-16 and URL-encoded uploader secret in the named local runtime/evidence files, including AzCopy job plans; does not inspect OS memory, pagefile or encrypted caches.'} |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $project 'outputs\stage-d\secret-persistence-audit.json')
Write-Output "Secret persistence audit: $count files scanned, $($findings.Count) matches. Secret value was not printed."
if ($findings.Count) { exit 2 }
