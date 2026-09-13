"""Real Azure end-to-end acceptance, with gold data used only after processing."""
import argparse,json,hashlib,sqlite3,subprocess,time
from pathlib import Path
P=Path(__file__).resolve().parents[2];H=Path.home();R=H/'Documents/BmgPocRuntime/stage-f';O=P/'outputs/stage-f';D=P/'work/stage-f/dataset'
DOTNET=H/'Documents/BmgPocTools/dotnet/dotnet.exe';DLL=P/'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll';CONFIG=H/'Documents/BmgPocRuntime/azure/stage-f-config.json'
data=json.loads((D/'manifest.json').read_text())
e_data=json.loads((P/'work/stage-e/dataset/manifest.json').read_text())
def identity(case):return 'stage-f-'+case+('-002' if case=='happy' else '-001')
def sql(q):
 with sqlite3.connect(R/'state/intake.db') as db:db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute(q)]
def stage(case):
 ident=identity(case);dest=R/'staging'/ident
 if dest.exists():return ident
 dest.mkdir(parents=True);docs=[]
 for r in [r for r in data['records'] if r['case']==case or (case=='watch' and r['case']=='happy' and r['label']=='ClosingInstructions')]:
  source=D/r['path']
  if (case=='happy' and r['label']!='ClosingInstructions') or (case=='conflict' and r['label']=='Note'):
   r=next(x for x in e_data['records'] if x['split']=='test' and x['label']==r['label'] and x['index']==(2 if case=='conflict' else 0));source=P/'work/stage-e/dataset'/r['path']
  payload=source.read_bytes();assert hashlib.sha256(payload).hexdigest()==r['sha256']
  n=len(docs)+1;name=f'document-{n:03}.pdf';(dest/name).write_bytes(payload);docs.append(dict(documentId=f'doc-{n:03}',fileName=name,sha256=r['sha256']))
 (dest/'submission.json').write_text(json.dumps(dict(schemaVersion='poc-1',submissionId=ident,revision=1,source='LocalStagingPoC',submissionType='Examination',documents=docs)))
 (dest/'_READY').write_text('');return ident
def command(*extra):return [str(DOTNET),str(DLL),'--azure-full','--root',str(R),'--azure-config',str(CONFIG),*extra]
def run(*extra):
 with (O/'full-worker.log').open('a',encoding='utf-8') as log:
  p=subprocess.run(command('--once',*extra),stdout=log,stderr=log,timeout=1500)
 print('Worker exit',p.returncode,flush=True);return p.returncode
def job(case):return sql("select * from jobs where submission_id='"+identity(case)+"'")[0]
def result(case):return json.loads((Path(job(case)['snapshot'])/'result.json').read_text())
def save(name,value):(O/name).write_text(json.dumps(value,indent=2))
parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['identity','happy','negative','watch']);a=parser.parse_args()
if a.mode=='identity':raise SystemExit(run('--verify-identity'))
if a.mode=='happy':
 stage('happy');assert run('--crash-after-effect','MetadataExtracted')==75,job('happy')
 before=sql("select request_key,status from ai_requests where kind='llm'")
 assert run('--crash-after-effect','Persisted')==75,job('happy')
 assert run() in (0,2),job('happy')
 assert job('happy')['status']=='Returned' and result('happy')['metadata']==data['expectedHappy'],result('happy')
 assert before==sql("select request_key,status from ai_requests where kind='llm'")
 requests=sql('select request_key,status from ai_requests order by request_key');assert run() in (0,2)
 assert requests==sql('select request_key,status from ai_requests order by request_key')
 save('happy-recovery-results.json',dict(passed=True,fieldsCorrect=8,fieldsChecked=8,llmCrashRecovery=True,cosmosCrashRecovery=True,replayAddedRequests=0,job=job('happy'),result=result('happy')))
 print('PASS happy packet, eight fields, LLM/Cosmos crash recovery and no-op replay',flush=True)
if a.mode=='negative':
 stage('missing');stage('conflict');assert run()==2
 for case,error in [('missing','lenderCode:Required'),('conflict','loanNumber:Conflict')]:
  assert job(case)['status']=='ManualException' and error in result(case)['validationErrors'],job(case)
  assert not (Path(job(case)['snapshot'])/'cosmos-write-receipt.json').exists()
 save('negative-results.json',dict(passed=True,missing=result('missing'),conflict=result('conflict'),invalidMetadataPersisted=False))
 print('PASS missing-field and cross-document conflict routing',flush=True)
if a.mode=='watch':
 with (O/'full-watcher.log').open('w') as log:
  process=subprocess.Popen(command('--poll-ms','1000'),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
  try:
   time.sleep(3);assert process.poll() is None;stage('watch')
   for _ in range(240):
    rows=sql("select * from jobs where submission_id='stage-f-watch-001'")
    if rows and rows[0]['status']=='Returned':break
    if rows and rows[0]['status'] in ('ManualException','RetryExhausted'):raise AssertionError(rows[0])
    assert process.poll() is None;time.sleep(2)
   else:raise AssertionError('Watcher timed out')
   assert result('watch')['metadata']==data['expectedHappy'],result('watch')
  finally:
   if process.poll() is None:process.terminate()
   process.wait(timeout=30)
 save('watcher-results.json',dict(passed=True,stagedAfterWatcherStarted=True,workerStopped=True,result=result('watch')))
 print('PASS full-flow watcher with supported document',flush=True)


