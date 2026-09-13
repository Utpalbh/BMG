# BMG POC preflight and configuration

Stage A completed on 10 September 2026. The project is ready for Stage B, the local intake foundation. No billable Azure resources or model deployments were created. This is a planning baseline, not proof of a working Azure deployment.

## Scope and decisions

The authoritative boundary is steps 2 through 10 in `Claude outputs/bmg_mvp_detailed_flow.png`: local staging, detection, Key Vault credential retrieval, AzCopy upload, document classification, OCR/layout, LLM extraction, Cosmos persistence, and validated metadata returned locally. The written Word/Markdown specifications describe an older alternative and a larger boundary. No Jetdocs installation, LoanTrack invoice creation, EDM integration, queue automation, or examination rules are included in this POC.

The local .NET worker coordinates every API call; arrows between managed services do not imply automatic triggers. Blob upload precedes analysis. For runtime, the worker can submit verified original bytes to Document Intelligence, avoiding a claim that the managed AI service can automatically reach a storage private endpoint. Results and source hashes tie the analysis back to the uploaded originals. The worker receives OCR/layout, invokes the LLM, validates its output, writes Cosmos, and reads it back before marking step 10 complete.

The laptop represents the client-side host. Azure supplies real storage, AI, database, identity and private networking. The worker and VPN must remain running during the session. A later client deployment will replace the local staging producer and validate the client's actual network. Point-to-Site does not prove Site-to-Site connectivity or the client's application integrations.

## Verified preflight evidence

| Check | Result |
|---|---|
| Subscription | Existing Pay-As-You-Go in the default tenant; Owner role verified through live Azure calls |
| Authentication | Cached profile existed but token had expired; user renewed sign-in and live calls now succeed |
| Providers | Microsoft.Network, Storage, KeyVault, CognitiveServices, DocumentDB and Quota registered |
| Planned resource group | `rg-bmg-poc` was unused at check time |
| Region | East US 2 selected |
| Document Intelligence | FormRecognizer S0 listed in East US 2 with no SKU restrictions |
| GPT-5 mini | Version 2025-08-07, generally available, GlobalStandard capacity reported as 1,000K TPM; subscription limit 1,000K TPM, usage zero |
| GPT-4.1 mini | Version 2025-04-14 available in catalog; GlobalStandard quota entry absent; batch quotas exist. Not a runtime dependency |
| Network quota | 1,000 VNets, 20 standard IPv4 public IPs and 65,536 private endpoints available in East US 2 |
| Laptop network | Active Wi-Fi uses 192.168.1.0/24; observed route table does not overlap the proposed POC address pools |
| Local tools | .NET SDK 8.0.416, Azure CLI and Git present; AzCopy not on PATH; .NET 10 not installed yet |
| Dataset | Five submissions, 30 PDFs, six classes; source hashes checked earlier and matched |
| Contract validation | All five supplied expected metadata objects and converted manifests accepted; six negative schema cases rejected |

Quota is an entitlement, not a reservation or deployment guarantee. Regional capacity and credentials must be refreshed just before deployment. Missing Document Intelligence usage entries were not interpreted as unlimited capacity. Actual creation, certificate login, training access and endpoint reachability remain later-stage tests. Azure subscription Owner also does not, by itself, establish every Microsoft Entra directory permission; dedicated app registration creation will be checked during identity setup.

## Configuration to implement

Use `poc-configuration.json` for the machine-readable baseline. Region is `eastus2`; use one dedicated resource group and ownership tags on every POC resource. Globally unique service names will be generated during infrastructure preparation and recorded in a deployment inventory.

| Component | Planned setting |
|---|---|
| Local worker | .NET 10 LTS, console-first with a later Windows Service hosting option |
| Local durable state | SQLite outside OneDrive, one active submission initially |
| VPN | VpnGw1AZ, Generation1, route-based, active-standby, OpenVPN P2S with certificate authentication |
| VNet | 10.84.0.0/16 |
| GatewaySubnet | 10.84.0.0/27; do not attach an NSG |
| Private endpoints | 10.84.1.0/24; five endpoints for Blob, Key Vault, DI, OpenAI and Cosmos NoSQL |
| DNS resolver inbound subnet | 10.84.2.0/28, dedicated and delegated |
| P2S client pool | 172.28.84.0/24 |
| DNS | Five private zones, one resolver inbound endpoint; no outbound resolver/ruleset required for this one-way resolution design |
| Document Intelligence | S0, API 2024-11-30, custom classifier plus prebuilt-layout |
| LLM | GPT-5 mini 2025-08-07, GlobalStandard, 30 capacity units initially |
| LLM execution | Low reasoning effort, one concurrent call, 20 requests/minute application ceiling; track input and all output/reasoning tokens |
| Storage | Standard LRS; separate training, submissions and analysis containers |
| Cosmos | NoSQL serverless, one region, partition key /submissionId, Gateway connection mode over HTTPS |
| Key Vault | Standard with RBAC; uploader credential fetched by a separately bootstrapped identity |

GlobalStandard allows inference processing outside the resource region. Private networking controls access and transport; it does not change the model's processing-location terms. This is acceptable for the authorized synthetic POC with no regional restriction. The client's later data-residency decision may require a different deployment type.

## Identity and private network design

The initial worker identity uses a certificate whose private key is protected in the local Windows certificate store. This identity can read the specific Key Vault secret and call only the required AI/Cosmos operations. A separate uploader service principal has container-scoped storage permissions; its short-lived credential is retrieved for the AzCopy child process, never committed, printed, or passed as a visible command-line argument. Record and remove the POC-created applications and credentials during teardown. The VPN certificate is separate from application authentication.

Validate the normal service hostnames against the VPN-reachable DNS resolver. Private DNS must return each endpoint's private address. Use HTTPS with normal certificate validation; do not bypass TLS or call raw private IP URLs. Cosmos uses Gateway mode to keep its data path on HTTPS rather than requiring Direct-mode port ranges. Verify authenticated requests both with the VPN connected and disconnected and test public-network rejection separately.

Training needs a distinct access check. Document Intelligence's managed identity and a supported storage firewall resource-instance/trusted-service configuration may be needed for the training source. A private endpoint does not automatically make the service's training fetch private. If that supported exception is needed, use it only for synthetic training, document it, and close it before the final private-runtime demonstration. Do not enable unrestricted public blob access. End-to-end runtime acceptance requires the planned public network restrictions in effect.

## Intake and metadata contract

`submission.schema.json` defines the runtime manifest. It intentionally excludes `documentType` labels and expected-answer fields. A staging helper will convert the existing synthetic manifests without changing source data. `_READY` is written last, after PDFs and the manifest are fully present. The drop of a ready folder is the sole manual business action; the worker does not ask the user to confirm each processing stage.

The worker verifies hashes and file signatures, prevents path traversal and links outside the staging root, enforces unique file/document IDs and size limits, and stores durable checkpoints. A folder watcher plus a periodic reconciliation scan handles missed or repeated notifications. Same ID and content means replay; changed content needs an explicit revision. One local SQLite database and atomic writes support recovery after interruption. Scope the output JSON to the submission ID and revision to prevent stale-result mix-ups.

`metadata-policy.json` keeps the eight placeholder fields and source precedence from the supplied expected-data files. All eight are required for this synthetic contract. The real client field list remains unconfirmed.

| Field | Preferred source |
|---|---|
| lenderCode | Closing Instructions, then Note |
| loanNumber | Closing Instructions, Note, Deed of Trust, Rider |
| borrowerName | Note, Deed of Trust, Closing Instructions |
| propertyAddress | Deed of Trust, Closing Instructions, Note |
| closingDate | Closing Instructions |
| loanType | Closing Instructions, Note |
| purpose | Closing Instructions |
| submissionType | Whitelisted submission manifest field |

Normalize equivalent values, retain the originals, and flag substantive conflicts. Priority does not silently suppress conflicting required values. Ambiguous dates, unsupported values and missing required fields produce ManualException. Do not equate a model's self-reported confidence with a measured probability. Every selected document field needs actual source/page evidence that the application checks. Documents are untrusted data, not instructions for tools or code execution.

`result.schema.json` defines the application result, including metadata, provenance, status and errors. It is not an Azure OpenAI strict-output schema; Stage F will define a compatible candidate-response schema. Schema validity alone does not prove factual correctness. Stage 10 succeeds only after Cosmos read-back matches the submission and an atomic local result-file write completes. Preserve original PDFs and keep sensitive evidence out of ordinary diagnostic logs.

## Training and evaluation

Target 120 training PDFs and 60 separate held-out PDFs across six classes, plus negative cases. The supplied uniform one-page files are a starting training family. Create additional templates, scans, changed pagination, renamed filenames, missing fields, and conflicts. Keep template families and borrower/loan identities separated between training and evaluation where possible; training labels and expected answers are never runtime inference inputs.

Train the classifier. Do not fine-tune the LLM or train six neural extraction models for this diagram. Use Layout and a constrained extraction prompt, then evaluate normalized field accuracy, evidence correctness, class confusion, exception routing, latency, tokens and cost. The 0.80 classifier threshold is provisional and must be assessed on held-out examples. Six document classes in the supplied packages do not establish a client rule that all six are mandatory.

The test fixture evidence used to validate the schemas is explicitly synthetic and is not a claim of extraction success. No AI accuracy or VPN functionality has been demonstrated in Stage A.

## Cost worksheet

The reference budget is flexible; plan around INR 1,500 for the bounded 10-hour session. Prices were retrieved in INR from Microsoft's public Retail Prices API on 10 September 2026. Rates are retail estimates, not the subscription's final invoice. `cost-estimate.json` contains the calculation.

| Item | 10-hour scenario INR |
|---|---:|
| VpnGw1AZ | 200.65 |
| DNS resolver inbound endpoint | 238.87 |
| Five private endpoints | 47.77 |
| One public IPv4 | 4.78 |
| Private DNS zones, two daily billing units reserved | 15.92 |
| 240 Layout pages including training preprocessing allowance | 229.31 |
| 120 classification pages including reruns | 34.40 |
| LLM usage allowance | 150.00 |
| Cosmos one million RU allowance | 23.89 |
| Storage, vault, queries, transfer and logging allowance | 30.00 |
| Subtotal | 975.58 |
| With 20 percent contingency and illustrative 18 percent tax | 1,381.43 |

The same workload with three network hours is approximately INR 894 including those allowances. DNS resolver pricing is monthly but prorated hourly; the calculation uses September's 720 hours. DNS zones are billed daily and reserve two days in case the session spans a billing boundary. The LLM and miscellaneous entries are allowances, not verified unit tariffs; they must be checked against the actual deployment before the cloud session. No free credits are assumed. No paid custom neural extraction training is planned. If additional training charges or model changes become necessary, update the worksheet before proceeding.

Limit the application to one million LLM input tokens and 300,000 total output/reasoning tokens for the session. Persist usage counters, page counts, retry counts and Cosmos request units. Reaching an allowance pauses new work and prompts a usage review; it does not pretend Azure billing has stopped. Networking continues billing until deletion completes. Quotas and budget alerts are not hard spend caps.

## Session and teardown

Prepare source, data, local tests and Bicep before starting cloud resources. Record the deployment start and intended expiry. The cloud session includes provisioning, training, runtime validation, and deletion. Leave time for gateway creation, which can exceed 45 minutes. Capture failed experiments and learned configuration details as well as successes.

Before deleting anything, export results, non-secret configuration, prompts, model identifiers, training manifests and test evidence locally. Trained cloud models may be lost with resource deletion; keep source training data and a reproducible training procedure, not merely their IDs. Stop the local worker, delete only the inventoried POC resource group, wait for deletion, and verify no POC resources remain. Remove only POC-created Entra apps/credentials, VPN profiles and certificates, which do not all live in the resource group. Account for automatically created supporting resources explicitly; do not delete pre-existing subscription assets. Cost reporting can lag deletion, so record teardown time and reconcile final billing when it appears.

## Stage B handoff

The next stage is local only: create the .NET solution, install the agreed SDK and AzCopy if necessary, establish the non-synchronized runtime directory, implement staging readiness and durable state, and add explicitly labeled simulated adapters. Demonstrate detection, partial-copy protection, duplicate suppression, and restart recovery. Stop at that checkpoint before private Azure resource deployment. User approval between build stages is distinct from the eventual unattended processing of individual submissions.

## Reference material

- Project sources: detailed diagram and generating Python script; BMG_MVP_Cursor_Build_Spec.md; Word architecture/POC specification; intake overview deck; modernization proposal and its PDF; dataset manifests and expected metadata.
- [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [DNS billing and hourly proration](https://azure.microsoft.com/en-us/pricing/details/dns/)
- [Document Intelligence pricing](https://azure.microsoft.com/en-us/pricing/details/document-intelligence/)
- [Document Intelligence private and managed-identity access](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/authentication/managed-identities-secured-access?view=doc-intel-4.0.0)
- [Azure OpenAI structured outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs)
- [Azure model deployment types](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/deployment-types)
- [VPN Gateway creation and timing](https://learn.microsoft.com/en-us/azure/vpn-gateway/tutorial-create-gateway-portal)
- [Cosmos DB Private Link and connection modes](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-configure-private-endpoints)
- [.NET support policy](https://dotnet.microsoft.com/en-us/platform/support/policy)
