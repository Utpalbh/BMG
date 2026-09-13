"""Local checks for real-mode preflight and durable AI reservation guards. No billable calls."""
import hashlib, json, sqlite3, subprocess, time, uuid
from pathlib import Path
from pypdf import PdfReader, PdfWriter
P=Path(__file__).resolve().parents[2]; H=Path.home()
BASE=H/'Documents/BmgPocRuntime/test-runs'/('stage-e-safety-'+uuid.uuid4().hex[:8]); BASE.mkdir(parents=True)
CONFIG=H/'Documents/BmgPocRuntime/azure/stage-e-config.json'
DLL=P/'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll'; DOTNET=H/'Documents/BmgPocTools/dotnet/dotnet.exe'
DATA=P/'work/stage-e/dataset'; M=json.loads((DATA/'manifest.json').read_text()); SAMPLE=DATA/M['records'][0]['path']
results=[]
def run(root):
    p=subprocess.run([str(DOTNET),str(DLL),'--azure-documents','--root',str(root),'--azure-config',str(CONFIG),'--once'],capture_output=True,text=True,timeout=60)
    return p
def query(root,sql):
    with sqlite3.connect(root/'state/intake.db') as db:
        db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute(sql)]
def stage(root,data):
    dest=root/'staging/test';dest.mkdir(parents=True)
    (dest/'document.pdf').write_bytes(data)
    (dest/'submission.json').write_text(json.dumps(dict(schemaVersion='poc-1',submissionId='test',revision=1,source='LocalStagingPoC',submissionType='Examination',documents=[dict(documentId='doc-001',fileName='document.pdf',sha256=hashlib.sha256(data).hexdigest())])))
    (dest/'_READY').write_text('')
def check(name,fn):
    root=BASE/name
    try:fn(root);results.append(dict(name=name,passed=True));print('PASS '+name,flush=True)
    except Exception as e:results.append(dict(name=name,passed=False,error=str(e)));print('FAIL '+name+': '+str(e),flush=True)
def invalid(root,kind):
    if kind=='malformed':data=b'%PDF-1.7\nThis is not a PDF structure.'
    else:
        writer=PdfWriter()
        if kind=='encrypted':writer.append(PdfReader(SAMPLE));writer.encrypt('poc-test-password')
        else:
            for i in range(21):writer.add_blank_page(width=612,height=792)
        import io
        stream=io.BytesIO();writer.write(stream);data=stream.getvalue()
    stage(root,data);p=run(root);assert p.returncode==2,(p.returncode,p.stdout,p.stderr)
    jobs=query(root,'select * from jobs');assert jobs[0]['status']=='ManualException'
    assert jobs[0]['error_code']==('PdfPageLimitExceeded' if kind=='over_page_limit' else 'PdfMalformedOrEncrypted'),jobs
    assert query(root,'select count(*) n from ai_requests')[0]['n']==0
    assert not list((root/'snapshots').rglob('azure-credential.json'))
for kind in ('malformed','encrypted','over_page_limit'):check(kind,lambda root,k=kind:invalid(root,k))

def uncertain(root,budget=False):
    # Seed only this isolated test DB directly before classification, so billing guards
    # can be tested without performing a credential retrieval or a paid API request.
    stage(root,SAMPLE.read_bytes())
    root.mkdir(exist_ok=True)
    # --status initializes directory layout without creating a database. Seed a database using an empty run.
    marker=root/'staging/test/_READY';marker.rename(marker.with_name('_NOT_READY'))
    assert run(root).returncode==0
    dest=root/'staging/test';m=json.loads((dest/'submission.json').read_text())
    # Match the worker's property ordering, two-space indentation and Windows CRLF.
    snap=root/'snapshots/safety';snap.mkdir(parents=True)
    (snap/'document.pdf').write_bytes(SAMPLE.read_bytes())
    m['documents'][0]['sha256']=hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    canonical=json.dumps(m,indent=2,ensure_ascii=True).replace('\n','\r\n').encode()
    (snap/'submission.json').write_bytes(canonical)
    digest=hashlib.sha256(canonical).hexdigest();jobid='safety'
    key=hashlib.sha256(f'{jobid}|doc-001|{m["documents"][0]["sha256"]}|classify|bmg-stage-e-v1|2024-11-30'.encode()).hexdigest()
    with sqlite3.connect(root/'state/intake.db') as db:
        db.execute('insert into jobs(id,submission_id,revision,digest,snapshot,stage,status) values(?,?,?,?,?,2,?)',(jobid,'test',1,digest,str(snap),'Pending'))
        db.execute('insert into ai_requests(request_key,kind,pages,status) values(?,?,?,?)',('prior-budget' if budget else key,'classify',120 if budget else 2,'Submitting'))
    p=run(root);jobs=query(root,'select * from jobs')
    assert p.returncode==2,(p.stdout,p.stderr)
    assert jobs[0]['error_code']==('AiPageBudgetExceeded' if budget else 'AiSubmissionOutcomeUnknown'),jobs
    assert len(query(root,'select * from ai_requests'))==1
check('uncertain_submission_does_not_resubmit',uncertain)
check('durable_page_budget_blocks_new_request',lambda root:uncertain(root,True))
report=dict(runtimeRoot=str(BASE),tests=results,passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results),billableCalls=0)
(P/'outputs/stage-e/safety-results.json').write_text(json.dumps(report,indent=2))
assert report['failed']==0,report
