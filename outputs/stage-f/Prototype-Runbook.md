# BMG full-flow prototype

Status: the real Azure flow for diagram steps 2–10 is verified. The full-flow and targeted checks described below passed; broader test limitations are recorded explicitly. Processing is stopped. Classifier generalization remains limited and this is not a client-ready deployment.

## Scope

The laptop represents the client host. The real Azure path is local staging → readiness detection → Key Vault credential retrieval → AzCopy/Blob upload → custom document classification → prebuilt Layout OCR → GPT-5 mini extraction → application validation → Cosmos create/read-back → local metadata JSON. This covers diagram steps 2–10. No Jetdocs, LoanTrack, invoice, EDM or examination-rule integration is implemented. Windows Service installation and client deployment remain separate work.

`--azure-full` uses an isolated runtime at `C:\Users\shrut\Documents\BmgPocRuntime\stage-f`. Earlier simulation, upload and OCR modes remain available for their historical checkpoints. Runtime configuration is under `C:\Users\shrut\Documents\BmgPocRuntime\azure\stage-f-config.json`. No secret value is stored there.

## Run a demonstration

Connect the saved `vnet-bmg-poc` profile in Azure VPN Client. The normal Azure service hostnames must resolve through the VPN to `10.84.1.x`; the resolver inbound address is `10.84.2.4`. Application DNS uses Windows NRPT. A public result from a diagnostic DNS tool must be investigated using both .NET resolution and an explicit query to the private resolver; do not bypass TLS or change endpoints to raw IPs.

From the project directory, start the worker in PowerShell:

```powershell
.\prototype\scripts\Start-AzureFullWorker.ps1
```

In another PowerShell window, stage a prepared valid fixture:

```powershell
.\prototype\scripts\Submit-DocumentFolder.ps1 -SourceFolder '.\work\stage-f\demo-ready'
```

The helper copies only PDFs to neutral filenames, hashes the copied bytes, writes the sanitized manifest and writes `_READY` last. The worker automatically processes a complete ready packet. A client-side producer would perform that readiness contract; merely copying an arbitrary PDF without a manifest/marker is not a complete submission. The helper can accept a different PDF folder, but the current classifier and field-label policy are deliberately limited and may send it to review.

Results appear under `C:\Users\shrut\Documents\BmgPocRuntime\stage-f\results`; completed receipts appear under `completed`; review/failure receipts appear under `exceptions`. Status: `Start-AzureFullWorker.ps1 -Status`. Stop the worker with Ctrl+C. `-Once` performs a reconciliation pass and exits. Exit 2 means there are outstanding exceptions or retries, which can include deliberately staged negative tests; inspect job status rather than assuming all jobs failed.

Never edit captured snapshots, erase SQLite, or blindly requeue a billed operation. The explicit --revalidate JOB_ID --once option applies only to a metadata-validation failure at checkpoint 5: it archives the prior result, appends an audit event, and reuses cached candidates without another LLM call. Same ID/revision/content is a replay. Changed content must have a new revision. A rejected or unknown LLM POST is held for review; a successful response is cached before the extraction checkpoint. Cosmos uses create-only writes with a stable job ID and partition key, followed by read-back verification; an existing item must match, not be overwritten.

## What the LLM does

Deployment `bmg-gpt5-mini` uses GPT-5 mini `2025-08-07`, GlobalStandard, capacity 30, default Microsoft content filtering and no automatic version upgrade. The saved deployment receipt contains the actual service configuration. Requests use low reasoning effort, strict JSON Schema output, no tools, no temperature override, `store=false`, and at most 12,000 output tokens including reasoning. This is inference using a constrained prompt, not LLM fine-tuning. The custom classifier was trained in Stage E; Layout OCR is prebuilt.

The prompt and candidate schema request explicit assessments for all seven document-derived fields in each document. Missing values are null. Distinct conflicting values must be retained. Submission type comes from the manifest and is never guessed by the LLM. Raw model responses, token usage and source OCR remain in restricted snapshot storage, not routine logs. `store=false` is an API setting, not a blanket claim that all provider monitoring/retention is disabled.

The worker validates document identifiers, source hashes/classification acceptance, page existence, exact OCR quote support after whitespace normalization, exact value presence and explicit field-label/value association. Dates accept ISO or unambiguous English month names; ambiguous numeric dates are reviewed. A recognized leading field label accidentally included in a model value is removed deterministically; the remaining value must still match its quote and field label. Identifiers retain leading zeros and punctuation. Addresses receive whitespace normalization only. Substantive differences are conflicts even when source priority would otherwise favor one document. Required fields and enum values are enforced. Only validated metadata is written to Cosmos.

Field-label validation currently recognizes explicit English labels such as Loan Number, Borrower, Property Address, Lender Code and Closing Date. Unrecognized prose or synonyms may be reviewed even when a human could extract the fact. Quote matching is evidence support, not proof that the source document is authentic or that an LLM found every conflicting statement. Prompt-injection testing is bounded evidence for the tested fixture, not a universal defense guarantee.

## Identity, networking and security concepts

VPN provides a network route; it does not authorize service access. Private DNS maps service names to private endpoints; TLS still validates normal service hostnames. Entra authentication identifies the application, and each service's RBAC authorizes operations. The VPN client certificate and worker application certificate are separate. The worker private key is nonexportable in the current user's certificate store.

The worker can read one Key Vault secret, call the POC Document Intelligence resource, infer using the POC OpenAI resource, and create/read items in the POC Cosmos container. Its Cosmos custom role includes metadata read plus item create/read, without item delete/replace/upsert permissions. The separate uploader identity has submissions-container Blob Data Contributor. Its short-lived secret is read from Key Vault and supplied to AzCopy without writing it to source or command arguments. Azure subscription Owner is used for setup, not runtime inference.

Private service endpoints remain publicly disabled. Training's temporary service-to-storage exception and DI training role were removed in Stage E. Authentication endpoints remain public HTTPS dependencies. GlobalStandard inference may process outside East US 2; private networking does not impose model data residency. The client must assess its own residency/compliance requirements before choosing this deployment type.

The current Point-to-Site VPN proves this laptop's connection only. Client Site-to-Site would require a compatible VPN device, routable non-overlapping address spaces, gateway configuration, routing/firewall rules and bidirectional DNS planning, followed by actual connectivity tests. Do not claim this POC has tested the client's site, apps, network or identity policies.

## Usage and operational limits

Per-runtime caps are 120 classification pages, 120 Layout pages, one million LLM input tokens, 300,000 completion/reasoning tokens and 500 Cosmos requests. LLM input reserves UTF-8 bytes plus overhead conservatively, and reconciles with reported token counts. Unknown responses keep their reservations. Single-process inference calls are spaced by at least three seconds. Cosmos request counts bound retries; response request-unit charges are retained. These are application limits, not Azure billing caps. Training and previous runtimes have separate ledgers and must be included when reconciling total use.

The SQLite store uses durable checkpoints and successful AI-response caches. Local files rely on laptop user permissions and disk protection; SQLite is not independently encrypted. PDFs are checked for hashes, parsing, encryption and page limits, but there is no malware scanner. The prototype is console-hosted, not an installed Windows Service, HA deployment or production monitoring system.

## Known classifier limitation and client readiness

Stage E's 28 generated held-out documents had 28 correct top labels, with 19/24 supported documents automatically accepted at the fixed 0.80 threshold. Five supported documents and all four Other documents went to review. In contrast, the original six supplied templates all received Survey as top label (only one correct), with confidence below threshold, and were held for review. This is poor generalization to those templates. The Stage F fixtures are derived from the supported family to demonstrate integration; successful results do not resolve that limitation.

Before client deployment: collect a representative approved corpus, confirm the actual metadata/business contract, train on distinct template families including the original style, freeze a separate evaluation set, measure field/evidence accuracy and false acceptance, calibrate thresholds, and agree review ownership. Validate identity rotation, service hosting, logging/retention, malware scanning, network availability, data residency, recovery and client integration. LLM fine-tuning should follow evidence of a problem that prompt/schema/data improvements cannot solve; it is not needed merely to extract eight fields.

## Retention and teardown

The user previously instructed us to retain the network. Stop local processing after a test session; this prevents new application calls but does not stop provisioned network charges. No VM or App Service is hosting this worker. The on-demand model deployment is not a provisioned-throughput commitment.

Do not delete the retained network without updated user authorization. Before eventual teardown, preserve source, configuration, training corpus, classifier build recipe, model/prompt versions, results, SQLite backups, test evidence and cost receipts. Existing teardown scripts target the inventoried POC resources. Entra applications, certificate-store entries and VPN profiles require their own scoped cleanup. Verify resource deletion completes and reconcile delayed billing; deletion is not proven by submitting a delete command.

## References

- [Azure structured outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs)
- [Azure reasoning models](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning)
- [Cosmos REST document creation](https://learn.microsoft.com/en-us/rest/api/cosmos-db/create-a-document)
- [Cosmos authorization](https://learn.microsoft.com/en-us/rest/api/cosmos-db/access-control-on-cosmosdb-resources)
- Stage A plan, Stage C networking runbook, Stage D identity runbook and Stage E classifier/OCR runbook in the adjacent output folders.


## Final acceptance evidence

The supported six-document packet returned all eight expected metadata fields after real LLM extraction, validation, Cosmos create/read-back and local return. Crashes after MetadataExtracted and Persisted recovered without another LLM request or duplicate Cosmos item. Replaying a completed packet added no service requests. Conflicting loan numbers produced a live metadata review result without Cosmos writes. The missing-lender-code fixture was held earlier at classification confidence 0.799; missing-field validation passed locally but was not demonstrated live. A supported packet staged after watcher startup reached Returned. The injected-instruction fixture was blocked at classification, so LLM prompt-injection resistance was not proved. The worker was stopped afterward. All 21 regression and 12 validator/budget checks passed. Result JSON files also passed the versioned full-result schema.

The first all-enriched six-document packet was held before OCR: all top labels were correct but four confidences were below 0.80. It remains in the audit trail. The successful packet uses five previously accepted layouts and the enriched Closing Instructions document. Do not report it as independent accuracy evidence. See verification-summary.json, the named test receipts, copied result files, configuration snapshot, model receipt and full-flow-state-backup.db.

Current teardown status: blocked before execution by automatic approval review because the earlier network-retention instruction requires explicit reversal. No Azure resources have been deleted. See ../POC-Completion.md and teardown-status.json. Processing is stopped.

