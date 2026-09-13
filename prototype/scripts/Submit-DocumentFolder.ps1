param(
 [Parameter(Mandatory)][string]$SourceFolder,
 [string]$SubmissionId=('bmg-'+(Get-Date -Format yyyyMMdd-HHmmss)+'-'+[guid]::NewGuid().ToString('N').Substring(0,6)),
 [ValidateRange(1,2147483647)][int]$Revision=1,
 [string]$RuntimeRoot="$env:USERPROFILE/Documents/BmgPocRuntime/stage-f"
)
$ErrorActionPreference='Stop'
if($SubmissionId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$'){throw 'Invalid submission ID'}
$source=Get-Item -LiteralPath $SourceFolder
if(!$source.PSIsContainer -or ($source.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Use a regular source folder'}
$files=@(Get-ChildItem -LiteralPath $source.FullName -File -Filter '*.pdf'|Sort-Object Name)
if($files.Count -lt 1 -or $files.Count -gt 30){throw 'Expected 1 to 30 PDFs'}
$landing=Join-Path $RuntimeRoot "staging/$SubmissionId-r$Revision"
if(Test-Path -LiteralPath $landing){throw 'Submission folder already exists; choose a new ID or revision'}
New-Item -ItemType Directory -Path $landing -Force|Out-Null
$documents=@();$n=0
foreach($file in $files){
 if($file.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked source file rejected'}
 $n++;$name='document-{0:000}.pdf' -f $n
 $before=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
 $dest=Join-Path $landing $name
 Copy-Item -LiteralPath $file.FullName -Destination $dest
 $after=(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
 if($before -ne $after){throw 'Source changed during copy; packet was not marked ready'}
 $documents+=@{documentId=('doc-{0:000}' -f $n);fileName=$name;sha256=$after}
}
@{schemaVersion='poc-1';submissionId=$SubmissionId;revision=$Revision;source='LocalStagingPoC';submissionType='Examination';documents=$documents}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $landing 'submission.json') -Encoding utf8
[IO.File]::WriteAllText((Join-Path $landing '_READY'),'')
Write-Output "Ready: $SubmissionId revision $Revision ($n PDFs). The running worker handles the remaining steps automatically."
