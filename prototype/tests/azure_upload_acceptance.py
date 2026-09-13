"""Live Stage D process tests. Uploads synthetic PDFs; no AI calls, no source deletion."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, sqlite3, subprocess, time, uuid

p = argparse.ArgumentParser()
p.add_argument('--dotnet', required=True)
p.add_argument('--config', required=True)
p.add_argument('--runtime-parent', required=True)
p.add_argument('--report', required=True)
a = p.parse_args()
project = Path(__file__).resolve().parents[2]
dll = project/'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll'
suite = Path(a.runtime_parent).resolve()/('azure-upload-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
suite.mkdir(parents=True)
results=[]

def write(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2),encoding='utf-8')

def stage(root, sample=1, ready=True):
    ident='stage-d-'+uuid.uuid4().hex[:16]
    source=project/f'BMG_MVP_Synthetic_Test_Data/synthetic-data/submission-{sample:03}'
    original=json.loads((source/'submission.json').read_text())
    folder=root/'staging'/f'{ident}-r1'; folder.mkdir(parents=True)
    m=dict(schemaVersion='poc-1',submissionId=ident,revision=1,source='LocalStagingPoC',submissionType='Examination',documents=[])
    for i,d in enumerate(original['documents'],1):
        name=f'document-{i:03}.pdf'; content=(source/d['fileName']).read_bytes()
        (folder/name).write_bytes(content)
        m['documents'].append(dict(documentId=f'doc-{i:03}',fileName=name,sha256=hashlib.sha256(content).hexdigest()))
    write(folder/'submission.json',m)
    if ready: (folder/'_READY').write_text('')
    return folder

def command(root,*extra):
    return [a.dotnet,str(dll),'--azure-upload','--azure-config',a.config,'--root',str(root),*extra]

def run(root,*extra,expected=(0,)):
    proc=subprocess.run(command(root,'--once',*extra),capture_output=True,text=True,timeout=360)
    with (suite/'process-logs.txt').open('a',encoding='utf-8') as f:
        f.write(f'{root.name} EXIT={proc.returncode}\n{proc.stdout}\n{proc.stderr}\n')
    assert proc.returncode in expected, f'Exit {proc.returncode}: {proc.stdout[-2000:]} {proc.stderr}'
    return proc

def rows(root,query):
    with sqlite3.connect(root/'state/intake.db',timeout=10) as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute(query)]

def uploaded(root):
    jobs=rows(root,'select * from jobs')
    assert len(jobs)==1 and jobs[0]['stage']==2 and jobs[0]['status']=='Uploaded',jobs
    snapshot=Path(jobs[0]['snapshot'])
    receipt=json.loads((snapshot/'azure-upload.json').read_text())
    assert receipt['executionMode']=='AzureUpload' and len(receipt['files'])==7
    assert not receipt['aiPerformed'] and not receipt['cosmosWritten']
    for r in receipt['files']:
        name=r['blob'].rsplit('/',1)[1]
        assert r['sha256']==hashlib.sha256((snapshot/name).read_bytes()).hexdigest()
    assert not list((root/'results').glob('*')) and not list((root/'completed').glob('*'))
    assert not list((root/'fixtures').glob('*'))
    assert {r['stage'] for r in rows(root,'select stage from events')}=={'Ready','CredentialReady','Uploaded'}
    return receipt

def check(name,test):
    root=suite/name;root.mkdir();start=time.monotonic()
    try:
        test(root); results.append(dict(name=name,passed=True,seconds=round(time.monotonic()-start,2)))
        print('PASS',name,flush=True)
    except Exception as error:
        results.append(dict(name=name,passed=False,error=str(error),seconds=round(time.monotonic()-start,2)))
        print('FAIL',name,str(error),flush=True)

def actual(root):
    stage(root);run(root); receipt=uploaded(root)
    assert not any(f['reused'] for f in receipt['files'])
    old=(Path(rows(root,'select snapshot from jobs')[0]['snapshot'])/'azure-upload.json').read_bytes()
    events=rows(root,'select * from events');run(root)
    assert rows(root,'select * from events')==events
    assert old==(Path(rows(root,'select snapshot from jobs')[0]['snapshot'])/'azure-upload.json').read_bytes()
check('real_upload_readback_and_duplicate_suppression',actual)

def crash(root):
    folder=stage(root,2);run(root,'--crash-after-effect','Uploaded',expected=(75,))
    jobs=rows(root,'select * from jobs');assert jobs[0]['stage']==1
    before=json.loads((Path(jobs[0]['snapshot'])/'azure-upload.json').read_text())
    saved=root/'removed-from-staging';saved.mkdir()
    target=saved/folder.name
    assert target.resolve().is_relative_to(root.resolve()) and folder.resolve().is_relative_to(root.resolve())
    shutil.move(str(folder),str(target))
    run(root);after=uploaded(root)
    assert all(f['reused'] for f in after['files'])
    assert [(f['blob'],f['etag']) for f in before['files']]==[(f['blob'],f['etag']) for f in after['files']]
check('crash_after_real_upload_resumes_without_rewriting_blobs',crash)

def ready(root):
    stage(root,ready=False);run(root)
    assert not rows(root,'select * from jobs')
check('readiness_marker_blocks_cloud_processing',ready)

def damaged(root):
    folder=stage(root);(folder/'document-001.pdf').write_bytes(b'%PDF-corrupted-file')
    run(root,expected=(2,));assert not rows(root,'select * from jobs')
    assert rows(root,'select code from intake_errors')[0]['code']=='HashMismatch'
check('bad_hash_rejected_before_credentials_or_upload',damaged)

def mode(root):
    run(root)
    result=subprocess.run([a.dotnet,str(dll),'--simulate','--root',str(root),'--once'],capture_output=True,text=True,timeout=20)
    assert result.returncode==1 and 'bound to another' in result.stderr
check('azure_runtime_rejects_simulated_execution',mode)

def watch(root):
    logpath=root/'watcher.jsonl'
    with logpath.open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(command(root,'--poll-ms','60000'),stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+20
            while not (root/'state/worker.lock').exists():
                assert proc.poll() is None and time.monotonic()<deadline
                time.sleep(.2)
            time.sleep(1);stage(root,3)
            deadline=time.monotonic()+300
            while True:
                current=rows(root,'select * from jobs')
                if current and current[0]['status']=='Uploaded':break
                assert proc.poll() is None and time.monotonic()<deadline,current
                if current: assert current[0]['status'] not in ('ManualException','RetryExhausted'),current
                time.sleep(.5)
            uploaded(root)
        finally:
            proc.terminate();proc.wait(timeout=20)
check('folder_drop_drives_real_unattended_upload',watch)

report=dict(executionMode='AzureUpload',runtimeRoot=str(suite),passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results),tests=results)
write(Path(a.report),report)
print(json.dumps(report,indent=2),flush=True)
raise SystemExit(0 if not report['failed'] else 1)
