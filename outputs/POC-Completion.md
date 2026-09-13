# BMG POC completion — 13 September 2026

The working prototype has proved diagram steps 2–10 using real Azure services: local staging, detection, Key Vault credential retrieval, AzCopy upload, classification, OCR, GPT-5 mini extraction, application validation, Cosmos persistence/read-back and local metadata return.

The supported six-document packet returned all eight expected fields correctly. A second document staged after the watcher started also reached Returned automatically. The worker recovered from interruptions at the LLM and Cosmos checkpoint boundaries, using the existing LLM response. A completed replay added no service requests. A live conflicting-loan-number case went to review with no Cosmos write. Twelve validator/budget checks and 21 orchestration regression checks passed.

The final runtime contains two Returned jobs and four ManualException jobs retained as evidence. All processing is stopped. The LLM ledger reports 4,364 input and 5,198 completion/reasoning tokens; Cosmos responses reported 52.01 RU. These are application usage observations, not a full Azure bill.

## Costs and teardown

Azure Cost Management reported INR 2,146.95 for BMG and INR 2,147.04 subscription month-to-date at 11:15 AM IST on 13 September. The report can lag and is not a final invoice. Approximately INR 2,002.33 of the reported POC cost was DNS, VPN and virtual networking. See outputs/stage-f/latest-bill-summary.json.

No Azure resources were deleted. Automatic approval review blocked deletion of rg-bmg-poc because the user had explicitly instructed us to keep its network. Explicit approval to reverse that instruction is pending. Networking remains provisioned and billable; stopping the worker does not pause those charges. The exact guarded deletion target is recorded in outputs/stage-f/teardown-status.json. Do not bypass this approval block by deleting individual network resources or issuing an indirect deletion.

## Deliberate shortcuts and limitations

This is an integration POC, not a client-ready classifier. The original six supplied templates were all labelled Survey at low confidence (one correct label), and held for review. Adding metadata rows also pushed four newer templates below the fixed 0.80 threshold. The successful packet uses five previously accepted layouts plus a field-complete Closing Instructions document. No threshold was lowered and failed tests remain in the evidence.

The missing-field fixture was held at classification confidence 0.799, so missing-field validation was proved locally but not end-to-end for that fixture. The adversarial-instruction fixture was also held at classification, so it did not prove LLM prompt-injection resistance. These tests were not repeated to save time and cost. No classifier retraining, LLM fine-tuning, GUI, Windows Service installation, client app integration or client Site-to-Site VPN testing was added.

The LLM initially returned field labels as part of values. The deterministic validator now removes only recognized leading labels and still checks the remaining value against the page quote and label. An audited revalidation reused the original OCR/LLM artifacts, archived the old result and made no additional LLM call.

## Saved deliverables

- Operating and learning guide: outputs/stage-f/Prototype-Runbook.md
- Final verification and limits: outputs/stage-f/verification-summary.json
- Real returned result: the stage-f-happy-002 result JSON in outputs/stage-f
- Checkpoint backup: outputs/stage-f/full-flow-state-backup.db
- Working source: prototype/src/Bmg.Intake.Worker
- Start command: prototype/scripts/Start-AzureFullWorker.ps1
- Folder submission helper: prototype/scripts/Submit-DocumentFolder.ps1
- Reusable supported demonstration PDFs: work/stage-f/demo-ready
- Earlier infrastructure, network, identity, classifier and cost evidence: outputs/stage-a through outputs/stage-e

Runtime data remains outside OneDrive at C:\Users\shrut\Documents\BmgPocRuntime. Code, synthetic corpora, model deployment settings, training recipe and results remain in this project. After approved teardown, provision the recorded Azure infrastructure again before using the live worker. The classifier requires retraining from the retained corpus if its Azure resource is deleted.
