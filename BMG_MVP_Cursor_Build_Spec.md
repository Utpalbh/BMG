# BM&G Mortgage Examination Intake Automation MVP
## End-to-End Architecture, Functional Specification, and Azure PoC Build Guide

**Version:** 1.0  
**Date:** 26 August 2026  
**Status:** Working architecture / PoC specification  
**Prepared from:** Moder modernization proposal, discovery transcripts, and the latest MVP decision supplied in the project.

> **Purpose:** This document is intentionally implementation-oriented. It can be given to an architect, developer, or AI coding tool such as Cursor to build a proof of concept. Confirmed workshop decisions are separated from design recommendations and open items.

---

## 1. Executive summary

BM&G's current examination intake is fragmented across JetDocs, LoanTrack, EDM, MS Access, ClosingExpress, and SecureDocs. The existing process requires a coordination desk to manually create a LoanTrack transaction/invoice number, manually upload documents to EDM, manually add the invoice number to the MS Access queue, and distribute work. The broader modernization proposal targets replacement of these legacy handoffs and later AI-assisted examination, but the **agreed MVP is deliberately much smaller**.

### Agreed MVP in one sentence

When a lender submission arrives through JetDocs, automatically take the files from the temporary on-premises landing location, send them privately to an Azure AI service for document classification and extraction of the small metadata set required for invoice creation, create the LoanTrack invoice/transaction, and then upload the original documents to EDM using the resulting invoice number as the reference.

### MVP stop point

The MVP ends after successful EDM upload. The current MS Access queue, work distribution, ClosingExpress examination process, approximately 140 examination fields, review checklist, and SecureDocs release process remain unchanged.

### Recommended PoC technology direction

- **On-premises orchestration:** .NET 8 Worker Service running near the JetDocs temporary folder and existing LoanTrack/EDM systems.
- **Azure AI:** Azure AI Document Intelligence v4.0 using a custom classifier and custom extraction models for the required metadata. Azure OpenAI is not required for the first PoC unless business metadata proves too semantic or variable for Document Intelligence alone.
- **Private connectivity:** Site-to-Site IPsec/IKE VPN from BM&G on-premises to an Azure VNet; Document Intelligence exposed only through a Private Endpoint; public network access disabled.
- **DNS:** On-premises DNS conditionally forwards Azure private-service queries to Azure DNS Private Resolver so the normal Document Intelligence FQDN resolves to the private endpoint IP.
- **PoC adapters:** LoanTrack invoice creation and EDM upload are implemented behind interfaces. Until their real APIs/database contracts are confirmed, the PoC uses simulated adapters so the end-to-end workflow can be demonstrated.

---

## 2. Source basis, decision status, and terminology

| Status | Meaning in this document |
|---|---|
| **CONFIRMED - MVP DECISION** | Explicit decision supplied from the latest workshop/project discussion. |
| **CONFIRMED - CURRENT STATE** | Supported by the Moder proposal and/or discovery transcript. |
| **DESIGN RECOMMENDATION** | Architecture choice proposed here to make the MVP buildable and secure. |
| **TBD / BUSINESS CONFIRMATION** | Not yet supplied; implementation must remain configurable until confirmed. |

### Source facts carried forward

1. Lenders currently upload through JetDocs. The original proposal says an email is generated and no automation is triggered.
2. Coordination desk staff manually create a LoanTrack transaction and obtain an invoice number.
3. EDM document association depends on the transaction/invoice reference.
4. The MS Access queue is not integrated with LoanTrack; staff manually enter the invoice number into Access.
5. Different processing centers support either coordinator assignment or processor self-pickup.
6. Legal Assistants currently use ClosingExpress for examination, manually key about 140 fields, and later release through SecureDocs.
7. The proposed future document classes include Note, Deed of Trust, Title Commitment, Survey, Closing Instructions, and Rider.
8. The proposal identified Azure Document Intelligence as the OCR/document-analysis technology, but the new MVP decision narrows extraction to invoice-creation metadata rather than the full approximately 140 examination fields.

### Important architecture change from the original proposal

The original proposal stated that all platform services would be on premises and that mortgage data would not leave the firm's network boundary. The **new MVP decision supersedes that statement for this slice**: source documents are sent to an Azure AI service for processing. The intended security control is private hybrid connectivity (S2S VPN + Private Endpoint), not an on-prem-only AI runtime. Security/legal stakeholders should explicitly approve this revised data-processing boundary.

---

## 3. MVP objective and business outcome

### 3.1 Business problem addressed

Today the Coordination Desk acts as the integration layer between disconnected systems. For the intake portion alone, a person receives the lender submission, creates the transaction in LoanTrack, obtains the invoice number, uploads/associates documents in EDM, then manually adds the invoice to the MS Access queue.

The MVP removes the first major manual chain:

**JetDocs submission -> metadata understanding -> invoice creation -> EDM upload**

### 3.2 Business outcome

The MVP should demonstrate that BM&G can automatically turn a lender document submission into a correctly referenced EDM package without a coordinator reading documents or re-keying the metadata required only to create the invoice.

### 3.3 What the MVP intentionally does not solve

- Replacement of JetDocs.
- Replacement of LoanTrack.
- Replacement of EDM.
- Replacement of MS Access queue.
- Dynamic queue routing or SLA management.
- ClosingExpress replacement or wrapper.
- SecureDocs replacement.
- Full examination automation.
- The approximately 140 examination fields.
- Business-rule validation / stare-and-compare.
- Legal Assistant QC workbench.
- Full Document Preparation / LendingPad workflow.
- Client portal modernization.

---

## 4. End-to-end MVP process

### 4.1 Happy path

1. **Lender uploads documents in JetDocs.**
2. JetDocs/current integration places the documents in an **on-premises temporary submission folder** and/or emits a trigger.
3. The **MVP Intake Worker** receives the trigger and establishes a submission/correlation ID.
4. The worker waits until the submission is stable/complete enough to process (no partially copied files).
5. The worker computes file hashes and checks idempotency to prevent duplicate processing.
6. Documents are sent over HTTPS through the **Site-to-Site VPN** to **Azure AI Document Intelligence through its Private Endpoint**.
7. Document Intelligence classifies each document into the configured mortgage document class.
8. For each supported class, the corresponding extraction model returns configured metadata fields and confidence values.
9. The worker normalizes the extraction results into a **canonical InvoiceMetadata object** according to configurable source-priority rules.
10. Required fields and confidence thresholds are validated.
11. The worker invokes the **Invoice Adapter** to create the LoanTrack transaction/invoice and obtains the invoice number.
12. Only after the invoice number is returned successfully, the worker invokes the **EDM Adapter** to upload/associate every original document with that invoice number.
13. Processing is marked **Completed** and the source submission is archived/moved according to the agreed retention rule.
14. From this point onward, **the existing process remains unchanged**: the coordination desk/current process handles MS Access queue placement and downstream examination/release.

### 4.2 Do not create an invoice when

- The submission cannot be correlated as one logical transaction.
- A required document class is missing, if business declares that class mandatory for invoice metadata.
- A required metadata value is missing.
- Required metadata has confidence below the business-approved threshold.
- Conflicting values across documents cannot be resolved using approved source-priority rules.
- The same submission has already produced an invoice.

Such cases enter a **manual exception** state; the MVP should log enough information for support/coordinator review without changing downstream workflows.

---

## 5. Functional requirements

### FR-01 Intake trigger
The system shall begin processing when a JetDocs-related trigger indicates a new lender submission is available in the temporary landing location.

**PoC implementation:** use a file-system/folder watcher. Treat one subfolder as one submission. A `submission.json` manifest is used by the synthetic PoC to emulate the JetDocs trigger/correlation data.

**Production TBD:** actual JetDocs web service, event, email notification, database signal, or polling contract must be confirmed.

### FR-02 Submission grouping
The system shall process a submission as an atomic logical unit containing one or more documents. The trigger must provide, or the landing structure must imply, a stable submission identifier.

### FR-03 Stable-file detection
The worker shall not upload a document while it is still being copied. Use one of: atomic folder rename, completion marker, manifest, or repeated size/last-write checks.

### FR-04 Duplicate prevention
The system shall generate and persist an idempotency key using the source submission ID plus document hashes. A repeated trigger shall not create a second invoice.

### FR-05 Classification
The system shall classify each supported document into a configured document class. Initial candidate classes from the proposal are:

- Note
- DeedOfTrust
- TitleCommitment
- Survey
- ClosingInstructions
- Rider
- Unknown

The final list is business-configurable.

### FR-06 Metadata extraction
The system shall extract only the metadata required for **invoice creation in the MVP**. The final field list and source-document mapping are **TBD by business**.

### FR-07 Confidence
Every extracted field shall retain the source document, extracted value, confidence, and model identifier/version when available.

### FR-08 Canonical metadata aggregation
The system shall map document-level extraction outputs into a canonical `InvoiceMetadata` object using configuration rather than hard-coded source precedence.

### FR-09 Metadata validation
Required fields and minimum confidence shall be configurable. If validation fails, invoice creation shall not be attempted.

### FR-10 Invoice creation
The system shall create the LoanTrack transaction/invoice and capture the returned invoice number.

**Production interface:** TBD. Do not assume direct LoanTrack database writes until schema/integration ownership is approved.

### FR-11 EDM upload
After invoice creation succeeds, the system shall upload/associate the **original lender files** to EDM using the returned invoice number/reference.

### FR-12 Partial EDM protection
The system shall track each document upload separately so an interrupted multi-file upload can resume without duplicate documents.

### FR-13 Status and audit
Each submission shall have a correlation ID and durable processing status, timestamps, attempts, error codes, document hashes, classification results, metadata, invoice number, and EDM upload status.

### FR-14 Manual exception
Non-retryable failures shall be moved to a failed/manual-review state and shall not silently disappear.

### FR-15 Downstream preservation
The MVP shall not automatically create the MS Access queue entry or change ClosingExpress/SecureDocs behavior.

---

## 6. Metadata contract - deliberately configurable until business confirms

The business is expected to confirm **what metadata is required and from which document(s)**. Therefore, do not lock the PoC to a fixed production schema.

### 6.1 Placeholder canonical metadata used by the synthetic PoC

```json
{
  "lenderCode": "LND001",
  "loanNumber": "BMG-POC-000001",
  "borrowerName": "Jordan Parker and Casey Parker",
  "propertyAddress": "101 Prototype Lane, Sampletown, TX 75001",
  "closingDate": "2026-09-22",
  "loanType": "Conventional",
  "purpose": "Purchase",
  "submissionType": "Examination"
}
```

**This is not the confirmed BM&G production schema.** It exists so the PoC can be built before the workshop delivers the final metadata mapping.

### 6.2 Recommended configurable mapping format

```json
{
  "fields": {
    "lenderCode": {
      "required": true,
      "minConfidence": 0.90,
      "sourcePriority": ["ClosingInstructions", "Note"]
    },
    "loanNumber": {
      "required": true,
      "minConfidence": 0.90,
      "sourcePriority": ["ClosingInstructions", "Note", "DeedOfTrust", "Rider"]
    },
    "borrowerName": {
      "required": true,
      "minConfidence": 0.85,
      "sourcePriority": ["Note", "DeedOfTrust", "ClosingInstructions"]
    }
  }
}
```

When business provides the real mapping, Cursor/developers should update configuration and model field definitions rather than rewrite orchestration logic.

---

## 7. Architecture overview

### 7.1 Architecture principle

Keep the orchestration and system-of-record integrations **on premises**, and use Azure only for the AI document-processing capability required by the MVP. This minimizes change to BM&G's legacy environment and keeps the MVP boundary narrow.

### 7.2 Core components

| Component | Location | Responsibility |
|---|---|---|
| JetDocs / temp landing | On-prem | Existing lender submission and temporary file landing. |
| MVP Intake Worker | On-prem | Trigger handling, grouping, hashing, AI orchestration, validation, invoice/EDM calls, retries. |
| Processing State Store | On-prem | Durable idempotency, state, attempts, audit. PoC may use SQLite; production should use approved SQL Server. |
| Invoice Adapter | On-prem | Encapsulates LoanTrack invoice creation contract. |
| EDM Adapter | On-prem | Encapsulates EDM upload/association contract. |
| Azure VPN Gateway | Azure | S2S IPsec/IKE connectivity from BM&G network to Azure VNet. |
| Azure DNS Private Resolver | Azure | Allows on-prem DNS to resolve Azure Private Endpoint names. |
| Private DNS Zone | Azure | `privatelink.cognitiveservices.azure.com` for the Document Intelligence endpoint. |
| Document Intelligence Private Endpoint | Azure VNet | Private IP used by on-prem application to reach the AI service. |
| Azure AI Document Intelligence | Azure | Document classification and metadata extraction. Public network access disabled. |
| Azure Blob Storage (training only) | Azure | Synthetic/labeled dataset for custom model training. Use private endpoint if network-restricted. |

---

## 8. Hybrid network and Private Endpoint design

### 8.1 Connectivity requirement

A Private Endpoint gives Document Intelligence a private IP in the Azure VNet, but it does not connect the on-premises network to that VNet. The cross-premises path is therefore:

**On-prem app -> on-prem VPN device -> IPsec/IKE Site-to-Site VPN -> Azure VPN Gateway -> VNet -> Document Intelligence Private Endpoint**

### 8.2 Illustrative network plan

| Network | Example range | Notes |
|---|---:|---|
| BM&G on-prem | `10.20.0.0/16` | Illustrative only; replace with real non-overlapping ranges. |
| Azure VNet | `10.40.0.0/16` | Must not overlap on-prem. |
| GatewaySubnet | `10.40.0.0/27` | Reserved for Azure VPN Gateway. |
| Private Endpoint subnet | `10.40.1.0/24` | Document Intelligence PE; optional Storage PE. |
| DNS Resolver inbound subnet | `10.40.2.0/28` | Dedicated/delegated subnet for Azure DNS Private Resolver inbound endpoint. |

### 8.3 DNS is mandatory

The application should continue to call the normal custom-subdomain endpoint, for example:

`https://<bmg-resource>.cognitiveservices.azure.com/`

It should **not** call the `privatelink...` hostname directly. DNS must resolve the service name to the private endpoint IP for the on-prem client.

Recommended pattern:

1. Create Azure Private DNS zone `privatelink.cognitiveservices.azure.com` and link it to the VNet.
2. Associate the Document Intelligence Private Endpoint with that zone.
3. Deploy Azure DNS Private Resolver with an inbound endpoint.
4. Configure BM&G enterprise DNS with a conditional forwarder for the appropriate Azure service DNS zone(s) to the resolver inbound IP over the S2S VPN.
5. Validate from the on-prem worker host using `nslookup` / `Resolve-DnsName`; the returned address must be the private endpoint IP.

### 8.4 Network security requirements

- Disable Document Intelligence public network access after Private Endpoint validation.
- Restrict on-prem firewall egress to required Azure private IPs/ports; runtime uses TCP 443.
- Use route-based S2S VPN; IKEv2 is the preferred baseline unless BM&G network standards dictate otherwise.
- Ensure on-prem and Azure address spaces do not overlap.
- Apply NSG/private endpoint subnet policy consistent with enterprise network standards.
- Log VPN connection state and Azure activity/security events.

### 8.5 PoC versus production VPN

The PoC can use a single S2S tunnel if the goal is functional validation. Production should evaluate zone-redundant VPN Gateway/active-active design according to BM&G availability requirements. ExpressRoute is not required for this MVP unless the enterprise already mandates it.

---

## 9. Azure AI Document Intelligence design

### 9.1 Recommended first implementation

Use **Azure AI Document Intelligence v4.0** with:

1. **Custom classifier** to identify the mortgage document type.
2. **Custom neural extraction model per supported class** to return the configured fields.
3. A small on-prem aggregation layer to map field results to canonical invoice metadata.

Why this is a good MVP fit:

- It is purpose-built for document OCR/layout/classification/extraction.
- It supports Private Endpoint networking.
- It returns structured results and confidence.
- It avoids introducing an LLM dependency before the required metadata is known.
- The broader proposal already identifies Azure Document Intelligence for document processing.

### 9.2 Training-data minimums relevant to the PoC

Microsoft currently documents that a custom classifier needs at least **two classes and five document samples per class**. Custom extraction can start with **five examples of a document type**. The accompanying synthetic dataset therefore supplies **five submissions x six candidate document classes = 30 PDFs**, giving five samples per class.

### 9.3 Training storage

Custom model training uses customer-provided Azure Blob Storage. For the private-network PoC:

- create a dedicated storage account/container for synthetic/training data;
- enable the Document Intelligence resource managed identity as required for training access;
- preferably use a Blob Private Endpoint and private DNS;
- do not place real BM&G mortgage documents in the synthetic PoC dataset unless data governance has approved it.

### 9.4 Runtime upload behavior

The on-prem worker can submit the document content directly to the Analyze API/SDK; a runtime Blob hop is not required merely to analyze a file. Azure Blob is included primarily for custom model training.

### 9.5 Data-retention security note

Microsoft documentation states that Document Intelligence temporarily stores submitted input and analysis results in encrypted Azure Storage in the same region for asynchronous processing and retains them for up to 24 hours, with a Delete Analyze Result API available for earlier deletion. This must be explicitly reviewed because it changes the original proposal's “no mortgage data leaves the network” assumption.

**Recommended production control:** after successfully retrieving required results, call the delete-analyze-result operation where supported/appropriate and capture the deletion result in audit logs.

### 9.6 Authentication

For PoC, use either:

- API key stored outside source control, or
- Microsoft Entra service principal/token credential.

For production, prefer Microsoft Entra ID service-to-service authentication with a dedicated application/service principal and least-privilege `Cognitive Services User` role, subject to BM&G identity standards. Do not embed API keys in code or `appsettings.json` committed to source control.

---

## 10. Detailed component design

### 10.1 `Intake.Worker`

**Technology:** .NET 8 Worker Service.

Responsibilities:

- watch/receive new submission triggers;
- normalize trigger into `SubmissionEnvelope`;
- stable-file detection;
- SHA-256 hashing;
- idempotency check;
- invoke classifier and extractor;
- aggregate/validate metadata;
- invoke Invoice Adapter;
- invoke EDM Adapter;
- persist state and audit;
- retry transient failures;
- archive completed submissions / quarantine failed submissions.

### 10.2 `ITriggerSource`

Production-neutral abstraction so the PoC can use a folder watcher without locking the design to a JetDocs mechanism not yet confirmed.

```csharp
public interface ITriggerSource
{
    IAsyncEnumerable<SubmissionEnvelope> ReadAsync(CancellationToken ct);
}
```

PoC implementation: `FileSystemTriggerSource`.

Future implementation: `JetDocsTriggerSource` after discovery confirms actual integration surface.

### 10.3 `IDocumentAiClient`

```csharp
public interface IDocumentAiClient
{
    Task<ClassifiedDocument> ClassifyAsync(DocumentInput input, CancellationToken ct);
    Task<DocumentExtraction> ExtractAsync(
        DocumentInput input,
        string documentType,
        CancellationToken ct);
}
```

Implementation: `AzureDocumentIntelligenceClient`.

### 10.4 `IMetadataAggregator`

Takes all extraction results and configuration, resolves source priority, and returns:

- canonical field value;
- selected source document;
- confidence;
- conflicts;
- validation errors.

### 10.5 `IInvoiceService`

```csharp
public interface IInvoiceService
{
    Task<InvoiceResult> CreateInvoiceAsync(
        InvoiceMetadata metadata,
        string idempotencyKey,
        CancellationToken ct);
}
```

PoC: `SimulatedInvoiceService` generates values such as `INV-POC-000001` and stores them durably.

Production: `LoanTrackInvoiceService`, contract TBD after LoanTrack interface/schema discovery.

### 10.6 `IEdmService`

```csharp
public interface IEdmService
{
    Task<EdmUploadResult> UploadAsync(
        string invoiceNumber,
        DocumentInput document,
        CancellationToken ct);
}
```

PoC: copy documents into `edm-simulated/<invoiceNumber>/` and write a JSON receipt.

Production: actual EDM API/interface TBD.

---

## 11. Processing state and idempotency

### 11.1 Submission state machine

`Received -> Staged -> AIProcessing -> MetadataValidated -> InvoiceCreated -> EDMUploaded -> Completed`

Failure paths enter `RetryPending` for transient issues or `ManualException` for non-retryable/business-validation failures.

### 11.2 Minimum durable tables

#### `SubmissionProcessing`

| Field | Purpose |
|---|---|
| `SubmissionId` | Source business/correlation identifier. |
| `IdempotencyKey` | Unique hash/key used to prevent duplicate invoices. |
| `Status` | Current processing state. |
| `ReceivedUtc` / `UpdatedUtc` | Audit timing. |
| `InvoiceNumber` | Returned LoanTrack invoice number. |
| `AttemptCount` | Retry/support visibility. |
| `LastErrorCode` / `LastErrorMessage` | Failure diagnostics; redact sensitive content where required. |
| `AiModelVersion` | Model/version traceability. |

#### `SubmissionDocument`

| Field | Purpose |
|---|---|
| `DocumentId` | Internal UUID. |
| `SubmissionId` | Parent. |
| `OriginalFileName` | Source file. |
| `Sha256` | Duplicate/integrity check. |
| `DocumentType` | AI classification result. |
| `ClassificationConfidence` | Confidence. |
| `EdmStatus` | Per-document upload state. |
| `EdmDocumentId` | Returned EDM identifier when available. |

#### `ExtractedField`

Store normalized field name, value, confidence, source document/page if provided, model ID/version, and selected/not-selected flag.

### 11.3 Idempotency rule

Recommended PoC key:

`SHA256(submissionId + sorted(documentSha256s))`

Before invoice creation, acquire an application/database lock for the idempotency key. The unique database constraint is the final guard against duplicate invoices.

---

## 12. Failure handling and resilience

### 12.1 Transient retry policy

Use exponential backoff with jitter for:

- VPN/network timeouts;
- Document Intelligence 408/429/5xx;
- temporary LoanTrack integration failures;
- temporary EDM failures.

Suggested PoC baseline: 4 attempts with delays approximately 2s, 5s, 15s, 30s; use server retry hints when supplied.

### 12.2 Non-retryable examples

- unsupported/password-protected file;
- unknown document class after configured threshold;
- missing business-required invoice metadata;
- conflicting metadata with no approved resolution;
- invalid LoanTrack business validation;
- unauthorized/authentication failures requiring configuration correction.

### 12.3 Recovery after invoice creation

The most important partial-failure case is:

**Invoice created, EDM upload fails.**

The workflow must never create another invoice simply because EDM retry occurs. Persist the invoice number before attempting EDM, then resume the EDM step against the same invoice.

### 12.4 Recovery after partial EDM upload

Store per-document upload receipts. On retry, upload only documents not confirmed in EDM, or use EDM's idempotency/document-existence API if available.

---

## 13. Security, privacy, and compliance

The uploaded packages contain mortgage PII, financial information, and legal instruments. Security controls are therefore part of MVP architecture, not future scope.

### Required controls

- S2S encrypted network path between on-premises and Azure VNet.
- Document Intelligence Private Endpoint.
- Public network access disabled after private-connectivity test.
- TLS for API calls.
- Encryption at rest in on-prem processing store and any Azure training storage.
- Least-privilege service identity.
- Secrets excluded from source control.
- Log redaction: do not log full document text, SSNs, bank data, or entire AI response payloads by default.
- Correlation IDs and field-level metadata provenance for audit.
- Controlled failed-file/quarantine access.
- Explicit retention/deletion policy for on-prem temp/archive files.
- Review Document Intelligence's temporary Azure retention behavior with legal/security.
- For custom training, isolate synthetic/approved training data from runtime production data.

### Threats to test

- public endpoint accidentally remains reachable;
- DNS resolves to public IP from on-prem;
- duplicate trigger creates duplicate invoice;
- malicious/unexpected file type;
- oversized/password-protected PDF;
- credentials leaked in logs/configuration;
- spoofed file written into landing folder;
- partial file copy processed prematurely.

---

## 14. Observability and audit

### Minimum structured log fields

`timestamp, correlationId, submissionId, documentId, stage, attempt, durationMs, outcome, errorCode, invoiceNumber, modelId, modelVersion`

Do not include full PII in logs.

### Metrics

- submissions received/completed/failed;
- average end-to-end processing time;
- AI call duration and failure rate;
- classification confidence distribution;
- metadata validation failures by field;
- invoice creation success/failure;
- EDM upload success/failure;
- duplicate triggers suppressed;
- manual exception count.

### Health checks

- temp-folder read/write health;
- state-store connectivity;
- DNS resolution to Document Intelligence private IP;
- TCP/TLS reachability to AI endpoint;
- VPN connection status (Azure side via monitoring);
- LoanTrack adapter health;
- EDM adapter health.

---

## 15. Azure PoC resource specification

Use Bicep so Cursor can provision repeatably. Names below are examples and must be parameterized.

| Resource | Example name | Notes |
|---|---|---|
| Resource group | `rg-bmg-mvp-ai-poc` | One PoC RG. |
| VNet | `vnet-bmg-mvp-poc` | Non-overlapping address range. |
| Gateway subnet | `GatewaySubnet` | Required fixed subnet name. |
| VPN Gateway public IP | `pip-vpngw-bmg-poc` | Standard/zone-redundant as approved. |
| Azure VPN Gateway | `vng-bmg-mvp-poc` | Route-based S2S. |
| Local Network Gateway | `lng-bmg-onprem-poc` | On-prem public VPN IP + internal prefixes. |
| VPN connection | `conn-bmg-onprem-poc` | IPsec/IKE shared key/cert per network standard. |
| Private endpoint subnet | `snet-private-endpoints` | DI PE, optional Blob PE. |
| Document Intelligence | `di-bmg-mvp-<unique>` | Custom subdomain; public access disabled after PE validation. |
| DI Private Endpoint | `pe-di-bmg-mvp` | Subresource `account`. |
| Private DNS | `privatelink.cognitiveservices.azure.com` | Link to VNet. |
| DNS Private Resolver | `dnspr-bmg-mvp-poc` | Inbound endpoint for on-prem queries. |
| Training Storage | `stbmgmvppoc<unique>` | Synthetic/custom model training only. |
| Blob Private Endpoint | `pe-st-bmg-mvp` | Recommended if storage is private. |

### Infrastructure parameters

Do not hard-code:

- Azure region;
- VNet/subnet CIDRs;
- on-prem address prefixes;
- on-prem VPN public IP;
- VPN pre-shared key;
- tenant/subscription IDs;
- Document Intelligence SKU;
- model IDs;
- storage names.

---

## 16. Recommended repository structure for Cursor

```text
bmg-intake-mvp/
  README.md
  docs/
    architecture.md
    decisions/
      ADR-001-hybrid-private-ai.md
      ADR-002-document-intelligence.md
      ADR-003-adapter-boundaries.md
  infra/
    main.bicep
    parameters/
      poc.bicepparam
    modules/
      network.bicep
      vpn.bicep
      private-dns.bicep
      document-intelligence.bicep
      training-storage.bicep
  src/
    Bmg.Intake.Worker/
    Bmg.Intake.Domain/
    Bmg.Intake.Infrastructure/
    Bmg.Intake.Adapters.Simulated/
  tests/
    Bmg.Intake.UnitTests/
    Bmg.Intake.IntegrationTests/
  config/
    metadata-mapping.poc.json
    document-types.poc.json
  synthetic-data/
    submission-001/
    ...
  scripts/
    train-models.ps1
    test-private-dns.ps1
    drop-synthetic-submission.ps1
```

### Suggested .NET projects

- `Domain`: DTOs, states, validation results, interfaces; no Azure/legacy dependencies.
- `Worker`: orchestration and hosted service.
- `Infrastructure`: EF Core/SQLite/SQL Server, Azure Document Intelligence client, resilience policies, logging.
- `Adapters.Simulated`: PoC Invoice and EDM implementations.
- Later create `Adapters.LoanTrack` and `Adapters.Edm` when actual contracts are known.

---

## 17. Synthetic PoC dataset included with this specification

The companion dataset contains:

- five synthetic examination submissions;
- each submission contains Note, Deed of Trust, Title Commitment, Survey, Closing Instructions, and Rider;
- 30 PDFs total;
- `submission.json` trigger/manifest simulation;
- `expected-invoice-metadata.json` with the placeholder canonical output;
- unique fictitious borrowers, lenders, properties, and loan values;
- no real customer information.

This dataset provides five samples per class, matching the Document Intelligence minimum sample count for a small custom classifier/extraction PoC.

### Expected PoC behavior

Drop `submission-001` into the configured landing root. The worker should process all six PDFs, extract/aggregate the expected placeholder metadata, call the simulated invoice adapter, receive e.g. `INV-POC-000001`, and copy all six documents into the simulated EDM location under that invoice number.

---

## 18. PoC build sequence

### Phase A - local end-to-end skeleton

1. Create .NET solution and domain interfaces.
2. Implement folder watcher, stable-folder rule, SHA-256 hashing, SQLite state store.
3. Implement `SimulatedDocumentAiClient` reading the included ground truth.
4. Implement simulated Invoice and EDM adapters.
5. Demonstrate idempotent end-to-end processing locally.

### Phase B - Azure private network

1. Deploy VNet/subnets.
2. Deploy Azure VPN Gateway and Local Network Gateway.
3. Network team configures matching on-prem VPN device.
4. Establish S2S tunnel and verify routes.
5. Deploy DNS Private Resolver inbound endpoint.
6. Configure on-prem conditional forwarder.

### Phase C - Azure Document Intelligence

1. Deploy Document Intelligence with custom subdomain.
2. Create Private Endpoint/private DNS integration.
3. Validate endpoint resolves to private IP from the on-prem worker host.
4. Disable public network access.
5. Deploy private training storage.
6. Upload synthetic training docs and train classifier/extraction models.
7. Replace `SimulatedDocumentAiClient` with the Azure client.
8. Run all five synthetic submissions.

### Phase D - legacy integration discovery

1. Confirm actual LoanTrack invoice-creation interface and required metadata.
2. Replace placeholder metadata mapping with business-confirmed mapping.
3. Implement `LoanTrackInvoiceService`.
4. Confirm EDM upload/association interface.
5. Implement real `EdmService`.
6. Run controlled non-production tests with approved data.

---

## 19. Test plan and MVP acceptance criteria

### Functional acceptance

- A new submission trigger is detected automatically.
- All files in the submission are classified.
- Configured metadata is extracted with value/confidence/source provenance.
- Required metadata validation gates invoice creation.
- Exactly one invoice is created per unique submission.
- The invoice number is persisted before EDM upload.
- All original files are associated/uploaded to EDM using that invoice number.
- The same trigger replay does not create a second invoice or duplicate EDM documents.
- A partial EDM failure resumes against the existing invoice.
- Low-confidence/missing metadata enters manual exception without invoice creation.

### Network/security acceptance

- S2S VPN reports connected.
- From the on-prem worker host, the Document Intelligence FQDN resolves to the Private Endpoint IP.
- `tracert`/routing and TCP 443 reachability work through the intended path.
- Document Intelligence public network access is disabled.
- Requests from an unapproved public network fail.
- No secrets are committed to source control.
- Logs contain correlation/audit information but not full mortgage document content.

### Synthetic-dataset acceptance

- All five submissions process successfully in the happy path.
- All 30 documents receive the expected class with an agreed PoC threshold.
- Placeholder invoice metadata matches expected outputs within normalization rules.

---

## 20. Open questions that must be answered before production integration

### Highest priority - business metadata (expected in 1-2 days)

1. What exact metadata fields are required to create the LoanTrack invoice?
2. For each field, from which document type(s) can it be sourced?
3. If the same field appears in multiple documents, what is the authoritative source or precedence?
4. Which fields are mandatory versus optional?
5. What confidence threshold requires manual review?
6. Are any calculations/lookup defaults needed rather than extraction?

### JetDocs / intake

7. What exactly creates the trigger: JetDocs web service, email, DB row, file notification, or another integration?
8. Does JetDocs create one folder per submission?
9. How do we know all files for a submission have arrived?
10. Is there a source submission/order ID we can use as the primary idempotency key?
11. Are all files PDFs? What about TIFF/JPG/DOCX/password-protected PDFs?

### LoanTrack

12. What is the supported integration surface for transaction/invoice creation: API, web service, database stored procedure, or UI-only legacy function?
13. Which system generates the invoice number?
14. What validation/default fields does LoanTrack apply?
15. Is there a way to look up an invoice by source submission ID to support recovery/idempotency?

### EDM

16. What is the EDM interface/protocol and authentication mechanism?
17. Is invoice number the only required association key?
18. Does EDM return document IDs/checksums?
19. Is EDM upload itself idempotent or can the same file be uploaded twice?
20. Are there required document-type codes/metadata during upload?

### Security/network

21. What are the actual on-prem CIDRs and VPN device/public IP?
22. Is S2S VPN already available or must a new Azure VPN Gateway be provisioned?
23. Which Azure region is approved for mortgage document processing?
24. Is Document Intelligence's up-to-24-hour temporary service retention acceptable, and should the solution invoke early deletion after result retrieval?
25. What enterprise DNS team/process owns the private-zone conditional forwarder?

---

## 21. Risks and mitigations

| Risk | Impact | MVP mitigation |
|---|---|---|
| Metadata fields are not yet known | Extraction cannot be finalized | Keep canonical mapping/config/model fields externalized; use placeholder synthetic schema. |
| LoanTrack has no supported API | Invoice step blocks automation | Adapter boundary; discover DB/service surface; keep simulated PoC independent. |
| EDM contract unknown | Final integration blocked | Adapter boundary and simulated repository. |
| JetDocs trigger semantics unknown | Duplicate/incomplete submissions | Abstract trigger, stable-folder rule, hashes/idempotency. |
| Low document variability in synthetic training | Unrealistic AI accuracy | Treat synthetic set as connectivity/flow PoC only; later add approved representative real samples. |
| VPN/DNS misconfiguration | Private endpoint appears unavailable | Dedicated DNS tests; resolver + conditional forwarding; check FQDN resolves private IP. |
| Original on-prem-only security assumption | Governance concern | Record architecture decision; security/legal approval; document service retention; private network + deletion control. |
| AI misclassification/extraction | Wrong invoice metadata | Required-field/confidence gate; no invoice on unresolved values; provenance/audit. |
| Duplicate trigger after invoice created | Duplicate invoices | Durable idempotency key + unique constraint + recover/resume from persisted state. |

---

## 22. Architecture decisions (ADRs) to record

### ADR-001 - Hybrid private AI processing
**Decision:** Keep orchestration/legacy adapters on premises; reach Azure AI through S2S VPN + Private Endpoint.  
**Reason:** Minimal MVP change, private network path, no need to move legacy systems into Azure.

### ADR-002 - Document Intelligence first
**Decision:** Use Document Intelligence classifier + custom extraction for the initial metadata PoC; do not introduce an LLM unless field complexity justifies it.  
**Reason:** Smaller attack surface, fewer services, purpose-built document AI, confidence and structured outputs.

### ADR-003 - Adapter legacy boundaries
**Decision:** No direct LoanTrack or EDM implementation in the core orchestration layer.  
**Reason:** Interfaces are not yet confirmed and both are legacy integration risks.

### ADR-004 - Invoice is the commit boundary
**Decision:** Persist the invoice number immediately after successful creation; all retries after this point reuse the same invoice.  
**Reason:** Prevent duplicate financial/business transaction records.

### ADR-005 - Downstream process unchanged
**Decision:** MVP ends after EDM upload.  
**Reason:** Explicit scope decision; queue/examination/release modernization remains future work.

---

## 23. What follows after MVP, but not in this build

The broader modernization roadmap can later extend the event after `EDMUploaded` to automate MS Access replacement/dynamic queue creation, SLA routing, and eventually examination extraction/rules/QC. None of those should be implemented into the current MVP unless scope is formally changed.

A future event could be conceptually:

`DocumentsReadyForExamination(invoiceNumber, edmDocumentIds, lenderId, submissionType)`

For this MVP, do not publish/use this event to change production workflow; it is only a future extensibility point.

---

## 24. Cursor / AI coding tool build contract

Give the AI coding tool this document plus the `synthetic-data` folder and ask it to follow these non-negotiable rules:

1. Build **only** the MVP boundary described here.
2. Use .NET 8 and clean adapter interfaces.
3. Start with simulated Invoice and EDM adapters; do not invent LoanTrack/EDM APIs.
4. Start with a file-system trigger; do not invent JetDocs API behavior.
5. Implement durable idempotency before invoice creation.
6. Make metadata mapping and thresholds configuration-driven.
7. Never create an invoice if required metadata validation fails.
8. Persist invoice number before EDM upload.
9. Implement resumable per-document EDM state.
10. Use Azure AI Document Intelligence through the normal resource FQDN; private DNS must route it to the PE.
11. Do not place Azure credentials/secrets in Git.
12. Add integration tests using the provided synthetic submissions.
13. Add a `--simulate-ai` mode so local end-to-end tests do not require Azure.
14. Add health checks and structured logging with correlation IDs.
15. Generate Bicep for Azure resources but parameterize region, CIDRs, VPN public IP, and all secrets.
16. Do not automate MS Access queue, ClosingExpress, SecureDocs, the 140 fields, or full-doc-prep workflow.

### Definition of done for the Cursor-generated PoC

A developer can clone the repo, run the simulated mode locally, drop a synthetic submission folder, and observe one simulated invoice plus six simulated EDM documents. After Azure/network parameters are supplied and models are trained, the same orchestration can switch to real Document Intelligence without changing domain logic.

---

## 25. References

### Project sources

- Moder, **Mortgage Examination Intelligence Platform - Modernization Proposal**, June 2026. Relevant sections: current workflow/pages 3-4, future platform/pages 5-8, delivery strategy/page 10, proposed stack/pages 13 and 16, security/page 18.
- Discovery transcript supplied in the project, including John Gage's explanation of LoanTrack invoice creation, separate/manual MS Access queue entry, and coordination-desk assignment/pickup behavior.
- Latest MVP decision supplied 26 August 2026: JetDocs temporary landing -> Azure AI classification/extraction of invoice metadata -> invoice creation -> EDM upload; downstream unchanged.

### Microsoft technical references consulted for this specification

- Microsoft Learn, **About Azure VPN Gateway** - Site-to-Site is an IPsec/IKE cross-premises connection between an on-prem VPN device and Azure VNet.
- Microsoft Learn, **Azure DNS Private Resolver Overview** - on-prem conditional forwarders can target a resolver inbound endpoint to resolve Azure Private DNS zones.
- Microsoft Learn, **Azure Private Endpoint private DNS zone values** - Foundry/Cognitive Services private zone includes `privatelink.cognitiveservices.azure.com`.
- Microsoft Learn, **Configure secure access with managed identities and private endpoints - Document Intelligence** - private endpoint and public-network restriction guidance.
- Microsoft Learn, **Document Intelligence custom classification models** - at least two classes and five samples per class.
- Microsoft Learn, **Document Intelligence custom models** - custom extraction can begin with five examples of a document type.
- Microsoft Learn, **Document Intelligence SDK v4.0** - API-key and Microsoft Entra token authentication are supported.
- Microsoft Learn, **Data, privacy, and security for Document Intelligence** - temporary encrypted storage/retention behavior and early delete capability.

---

## Appendix A - Example application configuration

```json
{
  "Intake": {
    "LandingRoot": "C:\\BmgMvp\\landing",
    "CompletedRoot": "C:\\BmgMvp\\completed",
    "FailedRoot": "C:\\BmgMvp\\failed",
    "StableFileSeconds": 10
  },
  "DocumentIntelligence": {
    "Endpoint": "https://<resource>.cognitiveservices.azure.com/",
    "ClassifierModelId": "bmg-doc-classifier-v1",
    "ExtractionModels": {
      "Note": "bmg-note-metadata-v1",
      "DeedOfTrust": "bmg-dot-metadata-v1",
      "TitleCommitment": "bmg-title-metadata-v1",
      "Survey": "bmg-survey-metadata-v1",
      "ClosingInstructions": "bmg-closing-instructions-metadata-v1",
      "Rider": "bmg-rider-metadata-v1"
    }
  },
  "Processing": {
    "ClassificationThreshold": 0.80,
    "RetryCount": 4
  },
  "Adapters": {
    "InvoiceMode": "Simulated",
    "EdmMode": "Simulated"
  }
}
```

Secrets are supplied through environment variables/approved secret storage, not this file.

## Appendix B - Example normalized AI result

```json
{
  "submissionId": "submission-001",
  "document": "closing-instructions.pdf",
  "documentType": "ClosingInstructions",
  "classificationConfidence": 0.987,
  "modelId": "bmg-closing-instructions-metadata-v1",
  "fields": {
    "loanNumber": {
      "value": "BMG-POC-000001",
      "confidence": 0.995,
      "page": 1
    },
    "lenderCode": {
      "value": "LND001",
      "confidence": 0.981,
      "page": 1
    },
    "closingDate": {
      "value": "2026-09-22",
      "confidence": 0.972,
      "page": 1
    }
  }
}
```

## Appendix C - MVP boundary reminder

```text
IN SCOPE
JetDocs/temp landing
  -> trigger
  -> AI classification
  -> MVP metadata extraction
  -> invoice creation
  -> EDM upload
  -> stop

UNCHANGED / OUT OF MVP
MS Access queue
  -> processor assignment/pickup
  -> ClosingExpress examination (~140 fields)
  -> review checklist
  -> SecureDocs release
```
