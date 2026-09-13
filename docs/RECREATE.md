# Recreate the POC on Windows

Use a **new session name and runtime directory** after teardown. This workflow targets the original personal subscription and `rg-bmg-poc` in East US 2. Optional subscription/tenant parameters exist, but another subscription/region requires a fresh quota, permission, addressing and policy review. Never run a second fresh session against an existing POC group.

The individual service flow was verified live. The new recreation wrapper was syntax-checked and its Bicep compiled; a second paid deployment was deliberately not created just to test restoration. Allow for model availability, service API changes and VPN provisioning time. GPT-5 mini version 2025-08-07 has a finite service lifetime; refresh the model catalog/quota before a future deployment.

## 1. Clone and prepare tools

```powershell
git -c core.longpaths=true clone https://github.com/Utpalbh/BMG.git
cd BMG
git config core.longpaths true
```

Use PowerShell 7, Azure CLI, Python 3.12+, Azure VPN Client, .NET SDK **10.0.401** and AzCopy **10.32.7**. On the original laptop the isolated tools remain in `Documents\BmgPocTools`; they are not deleted with Azure resources.

On another laptop, install the pinned .NET SDK into `C:\Users\<you>\Documents\BmgPocTools\dotnet` using Microsoft's [dotnet-install script](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-install-script), for example `dotnet-install.ps1 -Version 10.0.401 -InstallDir "$env:USERPROFILE\Documents\BmgPocTools\dotnet"`. Download AzCopy from [Microsoft's installation documentation](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azcopy-v10), verify its Microsoft signature/release checksum, and place exactly one `azcopy.exe` beneath `Documents\BmgPocTools\azcopy`. The identity initializer records its SHA-256 in the worker configuration. NuGet versions and integrity hashes are pinned in `packages.lock.json`.

Frozen PDFs and completed OCR sidecars are included, so regeneration is unnecessary. If regenerating fixtures or running schema checks, install `python -m pip install -r requirements-recreate.txt`; PDF preview generation additionally needs Poppler `pdftoppm`. Historical fixture generators use this laptop's bundled Poppler path, which must be configured on a different machine. This does not affect running the included submissions or retraining from included sidecars.

## 2. Authenticate and preflight

```powershell
az login --tenant e06201f9-0ec7-4863-80fc-85f43be49c1e
$session = 'poc-20261001' # choose a NEW stable name for this recreation
.\infra\scripts\Recreate-POC.ps1 -Action Preflight -Session $session -PythonExe python
```

All fresh credentials, session parameters, deployment operations and evidence go outside the repository under `Documents\BmgPocRecreated\<session>`. The helper scopes Azure commands to the selected subscription and checks the tenant. Setup needs rights to deploy resources/roles and create owned Entra applications. Subscription Owner alone does not guarantee every Entra directory permission.

## 3. Provision the foundation

```powershell
.\infra\scripts\Recreate-POC.ps1 -Action Foundation -Session $session
az deployment sub show -n "bmg-$session" --query properties.provisioningState
```

Foundation first validates and previews the Bicep, rejects deletions or modifications outside the POC group, then submits an incremental deployment. It is asynchronous; **wait for Succeeded**. VPN provisioning can take tens of minutes. Reuse the same session to inspect/resume a partial deployment; do not start new sessions to work around an unknown outcome.

The session name salts globally unique service names. This avoids attempting to reuse a Key Vault/Cognitive Services name still reserved after soft deletion. Key Vault purge protection prevents immediate purging; this workflow does not purge it. Default empty `nameSalt` in the source template preserves historical naming for reference.

## 4. Export and connect the new VPN profile

```powershell
.\infra\scripts\Recreate-POC.ps1 -Action Inventory -Session $session
```

The helper records the **new service names/managed identity IDs** and saves a temporary VPN ZIP download URL under the runtime's `azure` folder. Download it, extract the AzureVPN XML and import it into Azure VPN Client. Select the new `BMG-POC-VPN-Client` certificate and connect. Older certificates may have the same subject; compare the thumbprint in the new runtime's `vpn-certificates.json`. Never export a private key into GitHub.

Verify private DNS through resolver `10.84.2.4`: the normal Blob, Key Vault, DI, OpenAI and Cosmos names must resolve to `10.84.1.x`. For example use `[System.Net.Dns]::GetHostAddresses('<new-openai-name>.openai.azure.com')`. The original Stage C runbook records VPN import/certificate lessons. If the generated profile lacks the resolver setting, configure `10.84.2.4` in its DNS settings before import. Do not enable public data access as a workaround.

## 5. Create fresh runtime identities

```powershell
.\infra\scripts\Recreate-POC.ps1 -Action Identity -Session $session
```

This creates a certificate-backed worker app, a separate uploader app, scoped permissions and a 12-hour uploader credential held only in Key Vault. New runtime configuration is generated from the new inventory. The worker certificate and VPN certificate serve different purposes. The original `Rotate-StageEUploader.ps1` is bound to historical IDs: **do not use it for a recreated deployment**. For sessions longer than the uploader's 12-hour lifetime, rotate the newly inventoried uploader app credential into its newly inventoried vault using the same in-memory pattern; do not delete runtime state or rerun a stale identity initializer to simulate rotation.

## 6. Rebuild the classifier

```powershell
.\infra\scripts\Recreate-POC.ps1 -Action Train -Session $session -PythonExe python
```

The trained Azure classifier is not a portable model-weight file. Its **70 training PDFs, labels, manifest, API version, cached Layout sidecars and build recipe** are retained. The helper binds training to the new DI identity/resource and uses a fresh operation directory, avoiding the old deleted service's operation IDs. Completed compatible OCR sidecars can be reused to avoid re-billing their preprocessing. Never reuse an incomplete/unknown old operation after recreation.

Training temporarily grants scoped setup access and a storage resource-instance exception for DI, then restores private-only access and removes temporary roles. Check the fresh `evidence/stage-e/training-result.json` and `training-cleanup.json`. Do not continue after failed cleanup. Training is real and billable; this is not an LLM fine-tune.

## 7. Deploy the model and configure Cosmos access

```powershell
.\infra\scripts\Recreate-POC.ps1 -Action Model -Session $session
```

This checks the GPT-5 mini catalog/quota, creates the on-demand deployment, and uses the **fresh worker principal**, not the archived ID. The companion `infra/runtime.bicep`/`runtime.json` documents these model and role resources as IaC. Choose the script or template approach consistently; do not independently create duplicate role assignments through both. OpenAI defaults remain 30 GlobalStandard capacity, low reasoning effort in application calls, and a bounded token budget. GlobalStandard is not a guarantee of processing only within East US 2.

## 8. Run and submit the included demonstration

```powershell
.\infra\scripts\Recreate-POC.ps1 -Action Run -Session $session
```

In another PowerShell window:

```powershell
$session = 'poc-20261001' # same name
.\prototype\scripts\Submit-DocumentFolder.ps1 `
  -SourceFolder '.\work\stage-f\demo-ready' `
  -RuntimeRoot "$env:USERPROFILE\Documents\BmgPocRecreated\$session\full-flow"
```

Read `full-flow\results` and `full-flow\completed`. The supported six-document packet should produce the eight placeholder fields documented in the original result. Each service response and confidence can vary; review failures instead of lowering thresholds silently. A readiness manifest plus `_READY` is required; the helper creates both. The archive and gold answers are never runtime inference inputs.

## Stop and tear down

Stop the console worker with Ctrl+C and export new results before deleting the **inventoried** POC resource group. Networking continues to bill while provisioned. Entra app registrations/service principals and local certificates are outside the resource group and need separate scoped cleanup. The old teardown helpers deliberately pin the original session; for a recreation, use its fresh inventory and validate exact IDs/ownership before deletion. No backup or recreation helper deletes Azure resources automatically.

The proof's limitations remain: classifier generalization, missing-field/adversarial cases blocked before the LLM, no client app integration, no Windows Service/GUI, and no client Site-to-Site test. See the saved runbooks before proposing client deployment.
