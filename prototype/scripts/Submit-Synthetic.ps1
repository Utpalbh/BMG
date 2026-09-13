param(
    [ValidateRange(1,5)][int]$Sample = 1,
    [string]$SubmissionId,
    [ValidateRange(1,2147483647)][int]$Revision = 1,
    [string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime"
)
$ErrorActionPreference = 'Stop'
$bmgProject = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$bmgSource = Join-Path $bmgProject ('BMG_MVP_Synthetic_Test_Data\synthetic-data\submission-{0:000}' -f $Sample)
$bmgOriginal = Get-Content (Join-Path $bmgSource 'submission.json') -Raw | ConvertFrom-Json
$bmgExpected = Get-Content (Join-Path $bmgSource 'expected-invoice-metadata.json') -Raw | ConvertFrom-Json
if (!$SubmissionId) { $SubmissionId = 'demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6) }
if ($SubmissionId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$') { throw 'Invalid submission ID.' }
$bmgLanding = Join-Path $RuntimeRoot "staging\$SubmissionId-r$Revision"
$bmgFixturePath = Join-Path $RuntimeRoot "fixtures\$SubmissionId-r$Revision.json"
if ((Test-Path -LiteralPath $bmgLanding) -or (Test-Path -LiteralPath $bmgFixturePath)) { throw 'This submission/revision already exists. Use another ID or explicit new revision.' }
New-Item -ItemType Directory -Force -Path $bmgLanding,(Split-Path $bmgFixturePath -Parent) | Out-Null
$bmgDocuments = @(); $bmgClasses = [ordered]@{}; $bmgIndex = 0
foreach ($bmgDocument in $bmgOriginal.documents) {
    $bmgIndex++; $bmgId = 'doc-{0:000}' -f $bmgIndex
    $bmgFile = Join-Path $bmgSource $bmgDocument.fileName
    $bmgHash = (Get-FileHash -LiteralPath $bmgFile -Algorithm SHA256).Hash.ToLowerInvariant()
    Copy-Item -LiteralPath $bmgFile -Destination (Join-Path $bmgLanding $bmgDocument.fileName)
    $bmgDocuments += [ordered]@{ documentId=$bmgId; fileName=$bmgDocument.fileName; sha256=$bmgHash }
    $bmgClasses[$bmgId] = $bmgDocument.documentType
}
$bmgMetadata = [ordered]@{}
foreach ($bmgProperty in $bmgExpected.invoiceMetadata.PSObject.Properties) {
    if ($bmgProperty.Name -ne '_note') { $bmgMetadata[$bmgProperty.Name] = $bmgProperty.Value }
}
# Fixture-only answer data stays outside staging and is consumed solely by the simulated adapter.
[ordered]@{ executionMode='Simulated'; metadata=$bmgMetadata; documentTypes=$bmgClasses } |
    ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $bmgFixturePath -Encoding utf8
[ordered]@{ schemaVersion='poc-1'; submissionId=$SubmissionId; revision=$Revision; source='LocalStagingPoC'; submissionType='Examination'; documents=$bmgDocuments } |
    ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $bmgLanding 'submission.json') -Encoding utf8
# Marker written LAST. Do not copy expected-answer JSON or classifier labels into staging.
[System.IO.File]::WriteAllText((Join-Path $bmgLanding '_READY'), '')
Write-Output "Staged $SubmissionId revision $Revision with six PDFs. Mode: SIMULATED."
Write-Output "Results: $(Join-Path $RuntimeRoot 'results')"
