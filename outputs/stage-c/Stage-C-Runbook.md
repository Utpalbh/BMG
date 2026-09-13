# Stage C — private Azure foundation

Stage C is complete. On 11 September 2026, the laptop connected as `172.28.84.2`; all five services resolved to private addresses and returned HTTP 200 to authenticated read requests. System DNS and the private resolver returned matching addresses. Earlier authenticated requests outside the VPN returned HTTP 403 for all five services. Infrastructure, private connectivity and the public-access boundary are verified; application integration remains the next stage.

## Session and scope

- Subscription: `6f841b52-7a6d-4287-b0e3-4591621bb363`, Pay-As-You-Go.
- Tenant: `e06201f9-0ec7-4863-80fc-85f43be49c1e`.
- Region: East US 2. Dedicated resource group: `rg-bmg-poc`.
- Recorded session start: 11 September 2026, **12:59 PM IST**.
- Ten-hour reference expiry: **10:59 PM IST**, 11 September 2026.
- Expiry tags are informational. There is **no automatic deletion**. Networking continues billing until deleted.
- Stage A estimated gateway, resolver, five private endpoints and public IP at approximately **INR 49.21 per hour**, before DNS zone billing, usage, tax and contingency. This is the earlier retail estimate, not a live invoice or hard cap.

No LLM deployment, classifier training, document analysis, uploader credential, or worker application identity is created in Stage C. The Stage B worker remains in explicit simulation mode. Its local orchestration is not yet connected to these Azure services.

## Deployed topology

| Component | Configuration |
|---|---|
| VNet | `vnet-bmg-poc`, `10.84.0.0/16` |
| Gateway subnet | `10.84.0.0/27`, no NSG |
| Private endpoint subnet | `10.84.1.0/24` |
| DNS inbound subnet | `10.84.2.0/28`, delegated exclusively to DNS Resolver |
| DNS resolver | `dnspr-bmg-poc`, inbound address `10.84.2.4` |
| VPN | `vgw-bmg-poc`, VpnGw1AZ Generation1, active-standby, OpenVPN, certificate authentication |
| VPN client pool | `172.28.84.0/24` |
| Gateway ingress | One Standard Static zone-redundant public IPv4 address |
| Blob | `stbmgpocwjsvyjg25vqiy`, StorageV2 Standard LRS; private `training`, `submissions`, `analysis` containers |
| Key Vault | `kv-bmg-wjsvyjg25vqiy`, RBAC, soft delete and seven-day purge protection |
| Document Intelligence | `di-bmg-wjsvyjg25vqiy`, FormRecognizer S0, managed identity |
| Azure OpenAI | `oai-bmg-wjsvyjg25vqiy`, OpenAI S0 account, managed identity; no model deployment yet |
| Cosmos DB | `cosmos-bmg-wjsvyjg25vqiy`, NoSQL serverless, `bmg-poc/submissions`, partition key `/submissionId` |

Each service has a private endpoint and the matching private DNS zone linked to the VNet. All five data services have public network access disabled. Storage shared keys and AI/Cosmos local key authentication are disabled. Storage requires HTTPS/TLS 1.2 and infrastructure encryption; Cosmos requires TLS 1.2. Use service hostnames and normal TLS certificate validation, not raw private IP URLs.

The gateway's public IP is the encrypted VPN tunnel entrance. It does not make the data services publicly accessible. P2S demonstrates this laptop's connection; it does not prove the future client's Site-to-Site VPN, DNS forwarding, firewall, or application integration.

## Connect the laptop

Azure VPN Client **4.0.5.0** is installed. The generated profile is named `vnet-bmg-poc` and specifies DNS server `10.84.2.4`. The documented command-line import returned exit 0 but the client log rejected `-i bmg-poc-vpn.xml -f` as unknown arguments. Treat CLI exit status alone as insufficient proof of profile import; use the manual import below for this installation.

1. Open **Azure VPN Client** from Start.
2. Click **+**, then **Import**, and select:

`C:\Users\shrut\Documents\BmgPocRuntime\azure\vpn-profile\AzureVPN\azurevpnconfig.xml`

3. Select client certificate `BMG-POC-VPN-Client` if prompted, then **Save**.
4. Select `vnet-bmg-poc`, click **Connect**, and wait for Connected.

There are separate server-validation and client-authentication certificate settings. Keep the imported server certificate `DigiCert Global Root G2` under Server Validation. Select the BMG child certificate under Client Authentication. The client log identified a server-selector interaction while diagnosing the initial missing BMG dropdown entry; do not substitute the BMG certificate for the gateway's server-validation root. Local checks confirmed a single BMG client certificate, the matching issuer, Client Authentication EKU, valid dates, and a working private-key signature without exporting it. These checks do not replace a successful VPN handshake.

The root and client VPN certificates are separate from future application credentials. Their private keys are non-exportable in `Cert:\CurrentUser\My`, with seven-day validity. Only the root's public certificate is uploaded to Azure. Thumbprints and expiry are in the local runtime `azure\vpn-certificates.json`. The VPN profile contains connection configuration and must remain outside the OneDrive project; do not publish its complete contents.

## Verification and evidence

From PowerShell in the BMG project directory:

```powershell
.\infra\scripts\Get-StageCStatus.ps1
.\infra\scripts\Export-StageCInventory.ps1
.\infra\scripts\Test-PrivateConnectivity.ps1 -Mode Connected
```

The connected test must show all five normal hostnames resolving to `10.84.1.x`, agreement with DNS Resolver, and HTTP 200 using an Entra token. It performs read operations, not document analysis or model inference. It captures status and sanitized error responses, never access tokens. Cosmos uses HTTPS REST here, matching the planned Gateway-mode networking requirements.

Disconnect the VPN and run the corresponding negative test:

```powershell
.\infra\scripts\Test-PrivateConnectivity.ps1 -Mode Disconnected
```

All five authenticated public tests returned HTTP 403. Key Vault, DI, OpenAI and Cosmos explicitly reported connection/firewall restrictions; Blob reported AuthorizationFailure. Subsequent private requests using the same operator identity returned HTTP 200 for all five, completing the access-boundary comparison. DNS records alone do not prove authorization or a working data path.

| Service | Private address | Authenticated private request | Authenticated public request |
|---|---|---|---|
| Blob | `10.84.1.7` | HTTP 200 | HTTP 403 |
| Key Vault | `10.84.1.9` | HTTP 200 | HTTP 403 |
| Document Intelligence | `10.84.1.8` | HTTP 200 | HTTP 403 |
| Azure OpenAI | `10.84.1.6` | HTTP 200 | HTTP 403 |
| Cosmos | `10.84.1.4` | HTTP 200 | HTTP 403 |

The VPN is left connected for the next approved stage. The worker is not automatically switched out of simulation mode.

Files in this directory:

- `deployment-inventory.json`: actual service names, IDs and normal endpoints; no secrets.
- `resource-inventory.json`: live RG inventory, including Azure-created private endpoint NICs.
- `foundation-validation.json`: live public-access settings and five approved PE connections.
- `connectivity-disconnected.json`: authenticated public-access rejection evidence.
- `connectivity-connected.json`: all five private-access tests passed; `allPassed` is true.
- `verification-summary.json`: completed Stage C checkpoint, client VPN address and verification timestamp.
- `security-scan.json`: Checkov scan and exceptions.
- `deployment-preview.json`: initial Azure what-if preview.
- `cloud-session.json`: session start and intended expiry.

The operator has Blob Data Reader, Key Vault Secrets User, Cognitive Services User, Cognitive Services OpenAI User, and Cosmos native data Reader on the respective POC accounts. These are explicit data permissions; ARM Owner alone is not sufficient for all data-plane calls. AI user roles also allow inference. Dedicated certificate-authenticated worker and uploader identities with narrower scopes remain later-stage work.

## Infrastructure validation

`az bicep build --file infra/main.bicep` exited **0**. Checkov **3.3.17** reported **21 passed, 0 failed, 4 skipped, 0 parsing errors**. Azure ARM validation succeeded; the initial what-if showed **42 Create** entries and no Modify/Delete entries. Eight nested group deployments and the parent subscription deployment subsequently succeeded.

The four resource-local scan exceptions are explicit:

| Check | Reason |
|---|---|
| CKV_AZURE_36 | Trusted-service bypass is deliberately disabled for private-only runtime. Enabling it to satisfy this check would widen access. |
| CKV_AZURE_43 | Scanner cannot evaluate Bicep `uniqueString`; ARM validated the actual 21-character lowercase alphanumeric storage name. |
| CKV_AZURE_206 | Approved synthetic POC uses LRS; local originals/snapshots remain available. Production resilience needs a separate decision. |
| CKV_AZURE_182 | Approved POC uses one managed resolver inbound endpoint. A second was not required for the single-laptop proof. |

Cosmos key-based metadata writes were explicitly disabled, and OpenAI received a managed identity during hardening. Static scanning is useful evidence, not a guarantee of complete security. Core controls are also checked against live Azure state.

The skill's specialized MCP research tools were unavailable, so official Microsoft documentation and CLI/ARM validation were used. The infrastructure is in `infra/`; source documents and supplied PDFs were not edited. Pre-existing subscription resources were retained.

## Teardown

Export later-stage results, training data/procedure, prompts, usage and test evidence before deletion. Stop the worker and disconnect VPN. Preview the exact deletion scope with:

```powershell
.\infra\scripts\Remove-StageCResources.ps1
```

When the POC is finished, execute with `-Delete` and confirm. The script verifies the fixed subscription, resource group, ownership tags and local session record, exports the resource inventory, and requests RG deletion. Poll `az group exists` until false; command acceptance does not prove deletion is finished. The seven-day purge-protected vault cannot be immediately purged or its name reused.

Azure also automatically created `NetworkWatcher_eastus2` inside the **pre-existing** `NetworkWatcherRG`. Record it as a supporting resource and remove that exact watcher at final teardown only after checking it is not serving another East US 2 workload. Do not delete `NetworkWatcherRG`, its earlier watchers, or any pre-existing subscription resource. The watcher itself has no configured flow logs or packet capture in this POC.

Delete only the `vnet-bmg-poc` client profile and POC-owned certificate thumbprints after the session. Directory applications/credentials created in later stages need separate cleanup; RG deletion does not remove them. Do not indiscriminately remove certificates or uninstall tools the user may retain.

## Concepts to retain

Private Endpoint is an inbound private service interface; it does not give Document Intelligence outbound access to Blob for training. A later training stage may need a narrowly scoped temporary storage exception, followed by restoration of private-only runtime controls. Identity and network permission are separate checks, both of which must pass.

No LLM is trained in this stage. The approved later plan trains a document classifier and uses a pretrained LLM for constrained extraction and evidence validation. A private endpoint does not ensure model accuracy or force GlobalStandard processing to stay in East US 2.

## Official references

- [VPN SKU and generation support](https://learn.microsoft.com/en-us/azure/vpn-gateway/vpn-gateway-about-vpngateways)
- [Azure VPN Client certificate setup](https://learn.microsoft.com/en-us/azure/vpn-gateway/point-to-site-vpn-client-certificate-windows-azure-vpn-client)
- [VPN Client CLI import and DNS settings](https://learn.microsoft.com/en-us/azure/vpn-gateway/azure-vpn-client-optional-configurations)
- [Private Endpoint DNS pairings](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns)
- [DNS Resolver endpoints](https://learn.microsoft.com/en-us/azure/dns/private-resolver-endpoints-rulesets)
- [Key Vault RBAC](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide)
- [Document Intelligence secured storage access](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/authentication/managed-identities-secured-access?view=doc-intel-4.0.0)
- [Cosmos serverless constraints](https://learn.microsoft.com/en-us/azure/cosmos-db/serverless)
