"""Stage B process-level acceptance tests; uses real sample PDFs and explicitly simulated AI.
Run with the bundled Python, passing --dotnet, --runtime-parent and optionally --report.
Tests preserve their uniquely named runtime roots and never delete user files.
"""
from pathlib import Path
import argparse, copy, hashlib, json, os, shutil, sqlite3, subprocess, time, uuid

parser = argparse.ArgumentParser()
parser.add_argument('--dotnet', required=True)
parser.add_argument('--runtime-parent', required=True)
parser.add_argument('--report', required=True)
args = parser.parse_args()
project = Path(__file__).resolve().parents[2]
dll = project / 'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll'
suite = Path(args.runtime_parent).resolve() / ('acceptance-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
suite.mkdir(parents=True)
results = []

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding='utf-8')

def stage(root, sample=1, ident='test', rev=1, ready=True, folder_name=None):
    source = project / f'BMG_MVP_Synthetic_Test_Data/synthetic-data/submission-{sample:03}'
    original = json.loads((source / 'submission.json').read_text())
    expected = json.loads((source / 'expected-invoice-metadata.json').read_text())['invoiceMetadata']
    folder = root / 'staging' / (folder_name or f'{ident}-r{rev}')
    folder.mkdir(parents=True)
    manifest = dict(schemaVersion='poc-1', submissionId=ident, revision=rev, source='LocalStagingPoC', submissionType='Examination', documents=[])
    classes = {}
    for i, item in enumerate(original['documents']):
        docid = f'doc-{i+1:03}'
        shutil.copyfile(source / item['fileName'], folder / item['fileName'])
        manifest['documents'].append(dict(documentId=docid, fileName=item['fileName'], sha256=item['sha256']))
        classes[docid] = item['documentType']
    write(folder / 'submission.json', manifest)
    write(root / 'fixtures' / f'{ident}-r{rev}.json', dict(executionMode='Simulated', metadata={k:v for k,v in expected.items() if k!='_note'}, documentTypes=classes))
    if ready: (folder / '_READY').write_text('')
    return folder

def run(root, *extra, expected=(0,)):
    r = subprocess.run([args.dotnet, str(dll), '--simulate', '--root', str(root), '--once', '--retry-base-ms', '50', *extra], capture_output=True, text=True, timeout=30)
    with (suite / 'process-logs.txt').open('a', encoding='utf-8') as log:
        log.write(f'ROOT={root.name} EXIT={r.returncode}\n{r.stdout}\n{r.stderr}\n')
    assert r.returncode in expected, f'Unexpected exit {r.returncode}: {r.stderr}\n{r.stdout[-2000:]}'
    return r

def sql(root, query, parameters=()):
    with sqlite3.connect(root / 'state/intake.db', timeout=10) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query, parameters)]

def jobs(root): return sql(root, 'select * from jobs')
def count(root, table): return sql(root, f'select count(*) as n from {table}')[0]['n']
def completed(root, n=1):
    assert len(jobs(root)) == n and all(j['status']=='Returned' for j in jobs(root)), jobs(root)
    assert len(list((root / 'simulated-cosmos').glob('*.json'))) == n
    assert len(list((root / 'completed').glob('*.json'))) == n
    for path in (root / 'results').glob('*.json'):
        value=json.loads(path.read_text()); assert value['executionMode']=='Simulated' and value['status']=='Validated'

def check(name, test):
    start=time.monotonic(); root=suite/name; root.mkdir()
    try:
        test(root)
        results.append(dict(name=name, passed=True, seconds=round(time.monotonic()-start, 3)))
        print('PASS', name, flush=True)
    except Exception as error:
        results.append(dict(name=name, passed=False, error=str(error), seconds=round(time.monotonic()-start,3)))
        print('FAIL', name, error, flush=True)

def happy(root):
    for sample in range(1,6): stage(root,sample,f'happy-{sample}')
    run(root); completed(root,5)
    assert len(list((root/'simulated-blob').rglob('*.pdf')))==30
    for path in (root/'staging').glob('*/submission.json'):
        m=json.loads(path.read_text())
        for d in m['documents']: assert hashlib.sha256((path.parent/d['fileName']).read_bytes()).hexdigest()==d['sha256']
    for sample in range(1,6):
        expected=json.loads((project/f'BMG_MVP_Synthetic_Test_Data/synthetic-data/submission-{sample:03}/expected-invoice-metadata.json').read_text())['invoiceMetadata']
        value=json.loads(next((root/'results').glob(f'happy-{sample}-*.json')).read_text())
        assert value['metadata']=={k:v for k,v in expected.items() if k!='_note'}
check('five_happy_submissions',happy)

def no_marker(root):
    folder=stage(root,ready=False); run(root); assert count(root,'jobs')==0
    (folder/'_READY').write_text(''); run(root); completed(root)
check('completion_marker_gate',no_marker)

def partial(root):
    folder=stage(root); file=folder/'note.pdf'; original=file.read_bytes(); file.write_bytes(original[:100])
    run(root,expected=(2,)); assert count(root,'jobs')==0
    assert sql(root,'select code from intake_errors')[0]['code']=='HashMismatch'
    file.write_bytes(original); run(root); completed(root); assert count(root,'intake_errors')==0
check('partial_copy_repair',partial)

def duplicate(root):
    stage(root);run(root); before=count(root,'events'); times={p.name:p.stat().st_mtime_ns for p in (root/'simulated-cosmos').glob('*')}
    stage(root,folder_name='repeated-trigger');run(root);run(root);completed(root)
    assert count(root,'events')==before
    assert times=={p.name:p.stat().st_mtime_ns for p in (root/'simulated-cosmos').glob('*')}
check('duplicate_replay',duplicate)

def conflict(root):
    folder=stage(root);run(root)
    file=folder/'note.pdf'; file.write_bytes(file.read_bytes()+b'\nchanged submission\n')
    path=folder/'submission.json';m=json.loads(path.read_text());m['documents'][0]['sha256']=hashlib.sha256(file.read_bytes()).hexdigest();write(path,m)
    run(root,expected=(2,));completed(root);assert sql(root,'select code from intake_errors')[0]['code']=='RevisionContentConflict'
check('same_revision_conflict',conflict)

def revision(root):
    stage(root);run(root);stage(root,sample=2,rev=2);run(root);completed(root,2)
check('explicit_new_revision',revision)

def crash(root,stage_name):
    folder=stage(root);run(root,'--crash-after-effect',stage_name,expected=(75,))
    assert jobs(root)[0]['status']!='Returned'
    before={str(p.relative_to(root)):p.stat().st_mtime_ns for p in (root/'simulated-blob').rglob('*.pdf')}
    repo={p.name:p.stat().st_mtime_ns for p in (root/'simulated-cosmos').glob('*.json')}
    moved=root/'original-input-retained'
    assert folder.resolve().is_relative_to(root.resolve()) and moved.resolve().is_relative_to(root.resolve())
    folder.rename(moved)  # Verified test-root-local rename; recovery must use the snapshot.
    run(root);completed(root)
    assert before=={str(p.relative_to(root)):p.stat().st_mtime_ns for p in (root/'simulated-blob').rglob('*.pdf')}
    if repo: assert repo=={p.name:p.stat().st_mtime_ns for p in (root/'simulated-cosmos').glob('*.json')}
    assert len(list((root/'simulated-blob').rglob('*.pdf')))==6
for stage_name in ['Uploaded','Persisted','Returned']:
    check('crash_after_'+stage_name,lambda root,s=stage_name:crash(root,s))

def transient(root):
    stage(root);run(root,'--fail-once-stage','Uploaded',expected=(2,));assert jobs(root)[0]['status']=='RetryPending'
    time.sleep(.2);run(root,'--fail-once-stage','Uploaded');completed(root)
    assert len(sql(root,"select * from events where outcome like 'RetryPending:%'"))==1
check('transient_retry_after_restart',transient)

def bounded(root):
    stage(root)
    for _ in range(4): run(root,'--always-fail-stage','Uploaded',expected=(2,));time.sleep(.6)
    assert jobs(root)[0]['status']=='RetryExhausted' and jobs(root)[0]['attempts']==4
    before=count(root,'events');run(root,expected=(2,));assert count(root,'events')==before
    assert not list((root/'completed').glob('*'))
check('bounded_durable_retries',bounded)

def missing(root):
    stage(root);path=root/'fixtures/test-r1.json';f=json.loads(path.read_text());f['metadata']['loanNumber']=None;write(path,f)
    run(root,expected=(2,));assert jobs(root)[0]['status']=='ManualException'
    assert not list((root/'simulated-cosmos').glob('*'))
    value=json.loads(next((root/'results').glob('*.json')).read_text());assert 'loanNumber:Required' in value['validationErrors']
check('missing_required_metadata',missing)

def invalid_date(root):
    stage(root);path=root/'fixtures/test-r1.json';f=json.loads(path.read_text());f['metadata']['closingDate']='2026-02-30';write(path,f)
    run(root,expected=(2,));assert jobs(root)[0]['status']=='ManualException'
check('invalid_calendar_date',invalid_date)

def unexpected(root):
    folder=stage(root);m=json.loads((folder/'submission.json').read_text());m['documents'][0]['documentType']='Note';write(folder/'submission.json',m)
    run(root,expected=(2,));assert count(root,'jobs')==0 and sql(root,'select code from intake_errors')[0]['code']=='InvalidManifestJson'
check('answer_labels_rejected',unexpected)

def traversal(root):
    folder=stage(root);m=json.loads((folder/'submission.json').read_text());m['documents'][0]['fileName']='../note.pdf';write(folder/'submission.json',m)
    run(root,expected=(2,));assert count(root,'jobs')==0
check('path_traversal_rejected',traversal)

def unknown(root):
    stage(root);path=root/'fixtures/test-r1.json';f=json.loads(path.read_text());f['documentTypes']['doc-001']='Unknown';write(path,f)
    run(root,expected=(2,));assert jobs(root)[0]['error_code']=='UnknownDocumentClass'
check('unknown_class_exception',unknown)

def bom(root):
    folder=stage(root);path=folder/'submission.json';path.write_bytes(b'\xef\xbb\xbf'+path.read_bytes())
    run(root);completed(root)
check('windows_powershell_utf8_bom',bom)

def snapshot_tamper(root):
    stage(root);run(root,'--crash-after-effect','Uploaded',expected=(75,))
    snapshot=Path(jobs(root)[0]['snapshot']);file=snapshot/'note.pdf';file.write_bytes(file.read_bytes()+b'\ntampered snapshot')
    run(root,expected=(2,));assert jobs(root)[0]['error_code']=='SnapshotIntegrityFailure'
    assert not list((root/'simulated-cosmos').glob('*.json'))
check('snapshot_integrity_on_restart',snapshot_tamper)

def duplicate_json(root):
    folder=stage(root);path=folder/'submission.json';text=path.read_text();path.write_text(text.replace('"revision": 1','"revision": 1, "revision": 2'))
    run(root,expected=(2,));assert sql(root,'select code from intake_errors')[0]['code']=='DuplicateJsonProperty'
check('duplicate_json_property_rejected',duplicate_json)

def no_fixture(root):
    stage(root);path=root/'fixtures/test-r1.json';target=root/'fixture-not-available.json'
    assert path.resolve().is_relative_to(root.resolve()) and target.resolve().is_relative_to(root.resolve())
    path.rename(target)
    run(root,expected=(2,));assert jobs(root)[0]['error_code']=='SimulationFixtureMissing'
check('simulation_requires_explicit_fixture',no_fixture)

def watcher(root):
    log=(root/'continuous.log').open('w',encoding='utf-8')
    process=subprocess.Popen([args.dotnet,str(dll),'--simulate','--root',str(root),'--poll-ms','60000'],stdout=log,stderr=log)
    try:
        end=time.monotonic()+10
        while time.monotonic()<end and not (root/'logs/worker.jsonl').exists(): time.sleep(.05)
        assert process.poll() is None
        run(root,expected=(3,))
        status=subprocess.run([args.dotnet,str(dll),'--simulate','--root',str(root),'--status'],capture_output=True,text=True,timeout=10)
        assert status.returncode==0
        stage(root);end=time.monotonic()+10
        while time.monotonic()<end:
            if jobs(root) and jobs(root)[0]['status']=='Returned': break
            time.sleep(.1)
        completed(root)
    finally:
        if process.poll() is None: process.terminate();process.wait(timeout=10)
        log.close()
check('watcher_and_single_worker_lock',watcher)

report=dict(stage='B',executionMode='Simulated',azureCallsMade=False,runtimeRoot=str(suite),
            tests=results,passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results))
write(Path(args.report),report)
print(json.dumps(report,indent=2),flush=True)
raise SystemExit(1 if report['failed'] else 0)
