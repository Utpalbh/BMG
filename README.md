# BMG mortgage-intake Azure POC

Working proof of diagram steps **2–10**: stage PDFs locally → Key Vault → AzCopy/Blob → Document Intelligence classifier and OCR → GPT-5 mini → evidence validation → Cosmos persistence/read-back → local metadata JSON.

**Start here:** [Recreate the POC](docs/RECREATE.md), [completion report](outputs/POC-Completion.md), [operating and learning guide](outputs/stage-f/Prototype-Runbook.md).

This repository includes the original project documents/proposals, original and generated synthetic submissions, training data, completed training OCR sidecars, source code, tests, source Bicep and compiled ARM templates, configurations without secrets, and archived runtime evidence. The owner explicitly authorized this full public backup. Private keys, credentials, login caches and installed build tools are excluded.

## Contents

| Path | Purpose |
|---|---|
| `infra/main.bicep`, `infra/main.json` | Foundation: resource group, network/VPN/DNS, private endpoints, storage, Key Vault, Document Intelligence, OpenAI account and Cosmos |
| `infra/runtime.bicep`, `infra/runtime.json` | Model deployment and worker OpenAI/Cosmos permissions |
| `infra/scripts/Recreate-POC.ps1` | Fresh-session recreation entry point |
| `prototype/src` | .NET worker and real Azure adapters |
| `prototype/tests` | Local and live test harnesses; historical live harness IDs are not fresh-run orchestration |
| `BMG_MVP_Synthetic_Test_Data` | Original synthetic submission PDFs, manifests and expected answers |
| `work/stage-e/dataset`, `work/stage-e/training-layout` | Frozen classifier corpus and reusable completed OCR sidecars |
| `work/stage-f/demo-ready` | Supported six-document full-flow demonstration packet |
| `outputs` | Historical results, limits, costs, configuration and test evidence |
| `archive/runtime` | Synthetic submissions, snapshots, OCR/LLM results and SQLite backups exported from outside the project |
| `docs/RECREATE.md` | Setup, credentials, retraining, VPN, costs and recovery guidance |

The full-flow test returned all eight expected fields, and the live folder watcher and Cosmos/LLM recovery tests passed. **The classifier is not client-ready:** unfamiliar layouts often require review. Some negative fixtures stopped at classification, so they do not prove downstream extraction behavior. See the completion report for exact evidence and limits.

Recreation generates new identities, certificates and secrets. Historical operation IDs, identity IDs and SQLite checkpoints are audit evidence, not a new deployment's state. Do not copy the archive into a live runtime. Public network access is disabled; the laptop must use the VPN. Provisioned network services cost money even when no files are processed.

The original POC resource group and all its active resources were deleted on 13 September 2026 after the GitHub backup was independently verified. See [teardown status](outputs/stage-f/teardown-status.json) for the verification timestamp, identity cleanup and retention notes.

