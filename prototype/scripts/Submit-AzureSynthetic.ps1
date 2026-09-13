param(
    [ValidateRange(1,5)][int]$Sample = 1,
    [string]$SubmissionId = ('azure-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6)),
    [ValidateRange(1,2147483647)][int]$Revision = 1,
    [string]$RuntimeRoot = "$env:USERPROFILE\Documents\BmgPocRuntime\stage-d"
)
$ErrorActionPreference = 'Stop'
if ($SubmissionId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$') { throw 'Invalid submission ID.' }
$project = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$source = Join-Path $project ('BMG_MVP_Synthetic_Test_Data\synthetic-data\submission-{0:000}' -f $Sample)
$original = Get-Content -Raw -LiteralPath (Join-Path $source 'submission.json') | ConvertFrom-Json
$landing = Join-Path $RuntimeRoot "staging\$SubmissionId-r$Revision"
if (Test-Path -LiteralPath $landing) { throw 'Submission/revision exists; choose a new ID or revision.' }
New-Item -ItemType Directory -Force -Path $landing | Out-Null
$documents = @(); $index=0
foreach ($document in $original.documents) {
    $index++
    $file = Join-Path $source $document.fileName
    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    # Neutral filenames prevent source labels from becoming an accidental classifier signal.
    $name='document-{0:000}.pdf' -f $index
    Copy-Item -LiteralPath $file -Destination (Join-Path $landing $name)
    $documents += @{documentId=('doc-{0:000}' -f $index);fileName=$name;sha256=$hash}
}
@{schemaVersion='poc-1';submissionId=$SubmissionId;revision=$Revision;source='LocalStagingPoC';submissionType='Examination';documents=$documents} |
    ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $landing 'submission.json') -Encoding utf8
[System.IO.File]::WriteAllText((Join-Path $landing '_READY'),'')
Write-Output "Staged $SubmissionId revision ${Revision}: six PDFs, no fixture or expected-answer data. Azure worker stops at Uploaded."
