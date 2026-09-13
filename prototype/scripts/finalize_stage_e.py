"""Save the verified Stage E checkpoint before the separately authorized power action."""
import json,sqlite3,datetime,subprocess
from pathlib import Path
P=Path(__file__).resolve().parents[2]; O=P/'outputs/stage-e'; N=P/'outputs/overnight'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.write_text(json.dumps(v,indent=2),encoding='utf-8')
def az(*args):
 r=subprocess.run(['az.cmd',*args,'-o','json'],capture_output=True,text=True,check=True);return json.loads(r.stdout)
recovery=read(O/'demo-recovery-results.json');watcher=read(O/'watcher-results.json')
assert recovery['passed'] and watcher['passed'] and watcher['workerStopped']
storage=az('storage','account','show','-g','rg-bmg-poc','-n','stbmgpocwjsvyjg25vqiy')
assert storage['publicNetworkAccess']=='Disabled' and storage['networkRuleSet']['defaultAction']=='Deny'
assert storage['networkRuleSet']['bypass']=='None' and not storage['networkRuleSet'].get('resourceAccessRules')
roles=az('role','assignment','list','--assignee','116acd80-fcea-4810-b3d8-5cac78c256f5','--all')
assert roles==[]
resources=az('resource','list','-g','rg-bmg-poc')
stoppable=[r for r in resources if r['type'].lower() in ('microsoft.compute/virtualmachines','microsoft.compute/virtualmachinescalesets','microsoft.web/sites','microsoft.containerinstance/containergroups','microsoft.containerservice/managedclusters','microsoft.app/containerapps','microsoft.app/jobs')]
assert not stoppable
deployments=az('cognitiveservices','account','deployment','list','-g','rg-bmg-poc','-n','oai-bmg-wjsvyjg25vqiy')
assert not deployments
workers=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('dotnet.exe','Bmg.Intake.Worker.exe') -and $_.CommandLine -like '*Bmg.Intake.Worker*' }).Count"],capture_output=True,text=True,check=True)
assert workers.stdout.strip()=='0',workers.stdout
with sqlite3.connect(Path.home()/'Documents/BmgPocRuntime/stage-e/state/intake.db') as db:
 db.row_factory=sqlite3.Row
 jobs=[dict(x) for x in db.execute('select submission_id,status,error_code from jobs')]
 assert all(j['status'] in ('LayoutRead','ManualException') for j in jobs)
 assert all(j['error_code']=='ClassificationRequiresReview' for j in jobs if j['status']=='ManualException')
 ai=[dict(x) for x in db.execute('select kind,status,count(*) requests,sum(pages) pages from ai_requests group by kind,status')]
 assert all(x['status']=='Succeeded' for x in ai)
 with sqlite3.connect(O/'stage-e-state-backup.db') as backup:db.backup(backup)
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
summary=dict(stage='E',status='Complete',verifiedUtc=now,processingStopped=True,privateStorageVerified=True,trainingRolesRemoved=True,networkRetained=True,stoppableComputeResources=stoppable,openAiDeployments=deployments,regressionTestsPassed=21,safetyTestsPassed=5,identityChecksPassed=7,heldOut=read(O/'held-out-evaluation.json'),recovery=recovery,watcher=watcher,jobs=jobs,aiRequestTotals=ai,trainingLayoutPages=77,nextStage='F — not started')
save(O/'verification-summary.json',summary)
save(O/'final-private-storage-verification.json',dict(verifiedUtc=now,publicNetworkAccess=storage['publicNetworkAccess'],networkRuleSet=storage['networkRuleSet'],trainingRoles=roles))
save(N/'resource-inventory-final.json',resources)
save(N/'ready-to-shut-down.json',dict(stageEComplete=True,privateStorageVerified=True,trainingRolesRemoved=True,networkRetained=True,verifiedUtc=now,processingStopped=True))
review=read(N/'overnight-review.json');review.update(checkedUtc=now,processingStopped=True,networkRetained=True,stageEComplete=True);save(N/'overnight-review.json',review)
runbook=O/'Stage-E-Runbook.md';text=runbook.read_text(encoding='utf-8')
text=text.replace('Status: classifier training succeeded on 12 September at approximately 00:17 IST. Private-only storage and training-permission cleanup were verified. Held-out evaluation and live recovery validation are in progress; update this status at the final checkpoint.','Status: COMPLETE. Classifier training, held-out evaluation, live crash recovery and drop-folder watcher checks passed. Processing is stopped. Stages F onward remain unstarted.')
original=read(O/'original-packet-result.json') if (O/'original-packet-result.json').exists() else None
detail='The original supplied packet received Survey as all six top labels (only one correct), with confidence 0.122–0.785; all six were held for review. This shows poor generalization beyond the generated templates. Recovery was therefore tested with a previously evaluated supported synthetic packet; this is integration evidence, not additional independent accuracy evidence.' if original else 'The original supplied six-document packet completed classification and OCR, including crash recovery.'
text+='\n## Final verified results\n\n28/28 held-out documents had the correct top label. At the frozen 0.80 threshold, 19/24 supported documents passed automatically (79.2% coverage), five went to review, and 4/4 Other documents went to review; zero false accepts in this small synthetic set. OCR found 38/38 checked anchors. This is not a production accuracy or field-extraction guarantee.\n\n'+detail+' Crash recovery reused the recorded AI results with zero additional AI requests. A packet dropped after the watcher started automatically reached LayoutRead; the watcher was then stopped. The 21 regression, five safety and seven identity checks passed. Final Azure checks confirmed private-only storage, no temporary DI training roles, no OpenAI deployments and no compute resources to stop. SQLite was backed up after processing stopped. See verification-summary.json for request/page totals and all terminal job states.\n'
runbook.write_text(text,encoding='utf-8')
bill=read(N/'latest-bill-summary.json');expiry=read(O/'credential-rotation.json')['credentialExpiresAt']
handover=f'''# BMG handover — Stage E complete

Stage E is complete: staging → Key Vault credential → verified Azure upload → classifier → OCR. Stages F onward have not started. Processing is stopped, all jobs have terminal outcomes, and the checkpoint database is backed up in outputs/stage-e/stage-e-state-backup.db.

28/28 held-out top labels were correct; 19/24 supported documents passed the fixed confidence threshold, five required review, and all four Other documents required review. OCR found 38/38 checked anchors. {detail} Crash recovery added no AI requests. The live watcher test passed. See outputs/stage-e/Stage-E-Runbook.md and verification-summary.json for evidence and limitations.

## Cost and shutdown

Azure Cost Management reported INR {bill['poc']['reportedTotal']:.2f} for this POC and INR {bill['subscriptionMonthToDate']['reportedTotal']:.2f} subscription month-to-date at 14:19 IST on 12 September. Reporting can lag; this is not a final invoice or cap. Full breakdown: latest-bill-summary.json.

The user explicitly chose to keep the network. VPN gateway, DNS resolver, private endpoints, public IP, DNS zones and stored data remain provisioned and continue incurring charges even with the laptop off. The earlier network estimate was approximately INR 49.21/hour, not a current billed rate. There are no POC compute resources that can be stopped/deallocated and no OpenAI deployments. Local processing has stopped; no further application requests are being generated by this worker. Shutdown is separately executed after saving this handover; consult power-action.json for the actual request result, which cannot prove physical power-off.

## Resume

1. Start the laptop and reconnect vnet-bmg-poc. Verify private DNS resolves services into 10.84.1.x through resolver 10.84.2.4.
2. Read the Stage E runbook. Decide with the user when to start Stage F; do not repeat completed paid tests.
3. Uploader credential expiry is {expiry} UTC. Rotate it in the same Key Vault secret if expired; never log its value. The previous expired credential and temporary rotation permission were removed. The helper is prototype/scripts/Rotate-StageEUploader.ps1.
4. Runtime and cached operations remain under C:\\Users\\shrut\\Documents\\BmgPocRuntime. Preserve SQLite and snapshot results to avoid duplicate billable requests. Do not automatically requeue classification-review items or lower the confidence threshold.
'''
(N/'Handover.md').write_text(handover,encoding='utf-8')
print(json.dumps(dict(stageEComplete=True,jobs=len(jobs),ai=ai,processingStopped=True)))

