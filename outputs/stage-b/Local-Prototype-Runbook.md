# BMG intake prototype

Stage B is a working local intake and recovery prototype. It uses real PDF files and a real SQLite database. All Azure services and AI results are explicitly simulated. No invoice or EDM integration exists, and no network calls are made by the worker.

## Run the demonstration

Open PowerShell in `C:\Users\shrut\OneDrive\Desktop\Work\Moder\BMG\prototype` and run:

```powershell
.\scripts\Start-LocalWorker.ps1
```

Leave that terminal open. In a second PowerShell terminal in the same folder, run:

```powershell
.\scripts\Submit-Synthetic.ps1 -Sample 1
```

The helper copies six supplied synthetic PDFs, creates a sanitized manifest, and writes `_READY` last. It prepares a separate simulation fixture outside staging. No per-submission confirmation is needed. You can use samples 1 through 5; omitting a submission ID generates a fresh ID automatically.

Find the result in `C:\Users\shrut\Documents\BmgPocRuntime\results`. Every result contains `executionMode: Simulated`; source evidence is explicitly marked as fixture data, not OCR evidence. Stop the worker with Ctrl+C. The demonstration executed during development used ID `stageb-demo-001` and is already completed. Use a new ID to produce another result.

Status can be read while the worker is running:

```powershell
.\scripts\Start-LocalWorker.ps1 -StatusOnly
```

For a single reconciliation pass instead of continuous watching:

```powershell
.\scripts\Start-LocalWorker.ps1 -Once
```

Directly copying the original sample folder into staging is intentionally rejected because it contains expected-answer JSON and document-type labels. Use the helper, or prepare a manifest matching the Stage A submission schema, supply a fixture for simulation, and write the marker last. Arbitrary PDFs without a simulation fixture are not analyzed; the job reports `SimulationFixtureMissing`.

## What runs where

| Directory | Contents |
|---|---|
| `prototype/src` | C# worker, interfaces and adapters |
| `prototype/config` | Configurable placeholder metadata policy |
| `prototype/scripts` | Build, start, status and submission helpers |
| `prototype/tests` | Process-level acceptance harness |
| `C:\Users\shrut\Documents\BmgPocTools` | Isolated SDK, AzCopy and NuGet caches |
| `C:\Users\shrut\Documents\BmgPocRuntime\staging` | Submission folders and final readiness markers |
| `...\snapshots` | Verified input snapshots and checkpoint artifacts |
| `...\state\intake.db` | Durable job state, retry counts, events and intake errors |
| `...\fixtures` | Explicit simulation-only answers, kept out of staging |
| `...\simulated-blob` | Local copy standing in for uploaded originals |
| `...\simulated-cosmos` | Local idempotent result repository |
| `...\results` | Returned metadata or a structured metadata exception |
| `...\completed` | One completion receipt per accepted submission revision |
| `...\exceptions` | Current intake/job errors; transient receipts clear after recovery |
| `...\logs` | Structured logs with IDs and stages, without metadata values |
| `...\test-runs` | Retained isolated acceptance-test runs |

`...` in the table means the runtime root above. The tools and runtime deliberately live outside OneDrive. The scripts use the current user's profile for their default paths. The application is console-hosted; a Windows Service, autostart and a GUI are not installed.

## Recovery behavior

1. A readiness marker is mandatory. The worker also checks the manifest, file signatures, hashes, allowed filenames, unique document IDs and byte limits.
2. Accepted bytes are written to a snapshot before the job is inserted into SQLite. Original staged documents remain unchanged.
3. A watcher wakes the worker quickly; a ten-second scan recovers missed notifications and retries due work. Only one worker can own a runtime root.
4. SQLite uses WAL mode and FULL synchronization. Each stage checkpoint and its event are committed together.
5. Upload and repository adapters tolerate replay after a crash between the external effect and the database checkpoint. Verified existing outputs are reused; conflicting outputs raise an exception.
6. The result must be read back from the simulated repository and atomically written locally before `Returned` is committed.
7. Transient I/O failures use exponential backoff and jitter, with at most four attempts for the failing stage. Counts and due times survive process restarts.

The key is a canonical manifest hash covering the submission ID, revision, declared files and content hashes. Replaying the same ID/revision/content does not create another job. Changed content under the same revision is rejected. After correcting a terminal job problem, stage a new explicit revision; Stage B does not offer an unrestricted reset/retry command that would erase its audit trail. Stopping after a transient error and restarting normally resumes the existing job.

Files without `_READY` simply wait. An incomplete or mismatched ready package is reported in `intakeIssues` and `exceptions`; it can be repaired before acceptance. Unexpected files, duplicate JSON properties and path traversal are rejected. Repairing intake clears that intake error. Do not edit captured snapshots or delete SQLite records to retry.

Exit codes: 0 means no outstanding job/intake issues; 2 means pending retries or outstanding exceptions; 3 means runtime I/O or process-lock failure; 1 means configuration/startup failure. Test-only crash injection exits 75. A status-only command exits 0 when its query succeeds and includes the actual issues in its JSON.

## Build and tests

Installed versions: .NET SDK 10.0.401, Microsoft.Data.Sqlite 10.0.12, and AzCopy 10.32.7. AzCopy's Authenticode signature was verified as valid and signed by Microsoft. It is installed for the later real-upload stage but is not invoked by the simulation. System PATH was not changed. The SDK's initial startup also created its standard untrusted HTTPS development certificate; this console application does not use it.

Rebuild using the exact package lock:

```powershell
.\scripts\Build-Local.ps1
```

The SDK is pinned by `global.json`; dependency versions and content hashes are in `packages.lock.json`. Both should be updated intentionally together with compatibility checks when upgrading.

Run the acceptance harness from the BMG project directory, using Python 3.12 or newer:

```powershell
& 'C:\Users\shrut\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  '.\prototype\tests\acceptance.py' `
  --dotnet 'C:\Users\shrut\Documents\BmgPocTools\dotnet\dotnet.exe' `
  --runtime-parent 'C:\Users\shrut\Documents\BmgPocRuntime\test-runs' `
  --report '.\outputs\stage-b\acceptance-results.json'
```

The harness uses Python's standard library and launches actual worker processes. It creates unique test roots and keeps all evidence. It exercises happy packages, readiness, partial copies, duplicate triggers, revision conflicts, three crash boundaries, retries, missing/invalid metadata, unknown classes, unsafe manifests, Windows PowerShell BOM encoding, snapshot corruption, a missing simulation fixture, and live folder watching plus single-worker ownership. It never deletes source PDFs or user runtime directories.

## Boundaries for the next stages

The interfaces `IPipelineAdapter` and `IResultRepository` are the seams for real services. Stage B validates orchestration and local durability only. The simulated adapter reads trusted fixtures and does not perform OCR, train a classifier, assess document evidence, or detect semantic cross-document conflicts. Its confidence values are fabricated test values and must never be presented as measured AI confidence.

PDF signature and content-integrity checks do not constitute full PDF parsing, malware detection, encrypted-document support or page-count validation. Those input controls belong with real document processing. The local data store uses the user's filesystem protections and Windows disk protection, if enabled; SQLite is not separately encrypted by this prototype. Production retention, authentication, permissions, service hosting and client integration remain later work.

Stage C will deploy the private Azure foundation only after the Stage B checkpoint is accepted. Azure identity, VPN, private DNS, actual upload, AI, and Cosmos integrations are not yet proven. The cloud spending window has not started.
