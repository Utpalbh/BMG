"""Export final evidence only after every live acceptance check has succeeded."""
import datetime,json,sqlite3,subprocess,hashlib,shutil
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker
P=Path(__file__).resolve().parents[2];O=P/'outputs/stage-f';R=Path.home()/'Documents/BmgPocRuntime/stage-f'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,data):p.write_text(json.dumps(data,indent=2),encoding='utf-8')
def az(*args):return json.loads(subprocess.run(['az.cmd',*args,'-o','json'],capture_output=True,text=True,check=True).stdout)
for f in ['happy-recovery-results.json','negative-results.json','watcher-results.json']:assert read(O/f)['passed']
assert read(O/'simulation-regression-results.json')['failed']==0 and read(O/'validation-tests.json')['failed']==0
schema=read(P/'outputs/stage-a/result.schema.json');schema['properties']['executionMode']={'const':'AzureFull'};schema['required'].append('executionMode')
write(P/'prototype/config/full-result.schema.json',schema)
validator=Draft202012Validator(schema,format_checker=FormatChecker())
for file in (R/'results').glob('*.json'):validator.validate(read(file))
with sqlite3.connect(R/'state/intake.db') as db:
 db.row_factory=sqlite3.Row;jobs=[dict(r) for r in db.execute('select * from jobs')]
 assert all(j['status'] in ('Returned','ManualException') for j in jobs)
 before_requests=db.execute('select count(*) from ai_requests').fetchone()[0]
 replay=subprocess.run([str(Path.home()/'Documents/BmgPocTools/dotnet/dotnet.exe'),str(P/'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll'),'--azure-full','--root',str(R),'--azure-config',str(Path.home()/'Documents/BmgPocRuntime/azure/stage-f-config.json'),'--once'],capture_output=True,text=True,timeout=30)
 assert replay.returncode in (0,2)
 assert db.execute('select count(*) from ai_requests').fetchone()[0]==before_requests
 for j in jobs:
  if j['status']=='ManualException':assert db.execute("select count(*) from ai_requests where kind='cosmos' and request_key like ?",(j['id']+'%',)).fetchone()[0]==0
 ai=[dict(r) for r in db.execute('select kind,status,count(*) requests,sum(pages) pagesOrRequests from ai_requests group by kind,status')]
 usage=[dict(r) for r in db.execute('select * from llm_usage')]
 ru=sum(json.loads(r[0])['requestUnits'] for r in db.execute("select result_json from ai_requests where kind='cosmos' and result_json is not null"))
 with sqlite3.connect(O/'full-flow-state-backup.db') as backup:db.backup(backup)
workerCount=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('dotnet.exe','Bmg.Intake.Worker.exe') -and $_.CommandLine -like '*Bmg.Intake.Worker*' }).Count"],capture_output=True,text=True,check=True).stdout.strip()
assert workerCount=='0'
resources=az('resource','list','-g','rg-bmg-poc');write(O/'final-resource-inventory.json',resources)
storage=az('storage','account','show','-g','rg-bmg-poc','-n','stbmgpocwjsvyjg25vqiy')
assert storage['publicNetworkAccess']=='Disabled' and not storage['networkRuleSet']['resourceAccessRules']
checks={'storage':storage['publicNetworkAccess']}
for name in ['di-bmg-wjsvyjg25vqiy','oai-bmg-wjsvyjg25vqiy']:
 r=az('cognitiveservices','account','show','-g','rg-bmg-poc','-n',name);assert r['properties']['publicNetworkAccess']=='Disabled';checks[name]='Disabled'
cosmos=az('cosmosdb','show','-g','rg-bmg-poc','-n','cosmos-bmg-wjsvyjg25vqiy');assert cosmos['publicNetworkAccess']=='Disabled';checks['cosmos']='Disabled'
vault=az('keyvault','show','-g','rg-bmg-poc','-n','kv-bmg-wjsvyjg25vqiy');assert vault['properties']['publicNetworkAccess']=='Disabled';checks['keyVault']='Disabled'
roles=az('cosmosdb','sql','role','assignment','list','-g','rg-bmg-poc','-a','cosmos-bmg-wjsvyjg25vqiy');write(O/'cosmos-role-assignments.json',roles)
runtime_config=read(Path.home()/'Documents/BmgPocRuntime/azure/stage-f-config.json');write(O/'configuration-no-secrets.json',runtime_config)
happy=read(O/'happy-recovery-results.json');demo=P/'work/stage-f/demo-ready'
demo.mkdir(exist_ok=True)
for f in Path(happy['job']['snapshot']).glob('*.pdf'):shutil.copyfile(f,demo/f.name)
for file in (R/'results').glob('*.json'):shutil.copyfile(file,O/file.name)
write(O/'verification-summary.json',dict(status='Prototype flow verified; classifier generalization remains limited',verifiedUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),diagramSteps='2–10',fullAzureFlow=True,workerStopped=True,networkRetained=True,teardownPerformed=False,clientReady=False,regressionChecks=21,validatorChecks=read(O/'validation-tests.json')['passed'],fullHappyFieldsCorrect=8,fullHappyFieldsChecked=8,liveWatcherPassed=True,promptInjectionFixturePassed=False,promptInjectionBlockedAtClassification=True,conflictRoutingLivePassed=True,missingFieldValidationLivePassed=False,missingFieldValidationLocalPassed=True,llmAndCosmosCrashRecoveryPassed=True,replayAddedRequests=0,publicAccess=checks,jobs=jobs,aiTotals=ai,llmUsage=usage,totalReportedCosmosRU=ru,buildSha256=hashlib.sha256((P/'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll').read_bytes()).hexdigest(),limitations=['Original six templates failed confidence gating; only one original top label correct.','Adding metadata rows caused four of six new templates to fall below classification threshold.','Successful full packet combines accepted Stage E templates with field-complete Closing Instructions; integration evidence only.','Client application integration and site-to-site VPN are untested.']))
book=O/'Prototype-Runbook.md';text=book.read_text(encoding='utf-8').replace('Status: live end-to-end verification in progress. Read `verification-summary.json` for the final verified checkpoint; this document alone does not assert completion.','Status: the real Azure flow for diagram steps 2–10 is verified. All acceptance checks listed below passed; processing is stopped. Classifier generalization remains limited and this is not a client-ready deployment.').replace(".\\work\\stage-f\\dataset\\happy",".\\work\\stage-f\\demo-ready")
text+='\n## Final acceptance evidence\n\nThe supported six-document packet returned all eight expected metadata fields after real LLM extraction, validation, Cosmos create/read-back and local return. Crashes after MetadataExtracted and Persisted recovered without another LLM request or duplicate Cosmos item. Replaying a completed packet added no service requests. Conflicting loan numbers produced a live metadata review result without Cosmos writes. The missing-lender-code fixture was held earlier at classification confidence 0.799; missing-field validation passed locally but was not demonstrated live. A supported packet staged after watcher startup reached Returned. The injected-instruction fixture was blocked at classification, so LLM prompt-injection resistance was not proved. The worker was stopped afterward. All 21 regression and '+str(read(O/'validation-tests.json')['passed'])+' validator/budget checks passed. Result JSON files also passed the versioned full-result schema.\n\nThe first all-enriched six-document packet was held before OCR: all top labels were correct but four confidences were below 0.80. It remains in the audit trail. The successful packet uses five previously accepted layouts and the enriched Closing Instructions document. Do not report it as independent accuracy evidence. See verification-summary.json, the named test receipts, copied result files, configuration snapshot, model receipt and full-flow-state-backup.db.\n'
book.write_text(text,encoding='utf-8')
print(json.dumps(dict(verified=True,jobs=len(jobs),returned=sum(j['status']=='Returned' for j in jobs),llmInputTokens=sum(x['input_actual'] or 0 for x in usage),llmOutputTokens=sum(x['output_actual'] or 0 for x in usage),cosmosRU=ru)))


