"""Live evaluation through the production staging entry point; never supplies gold labels to the worker."""
import argparse, hashlib, json, shutil, sqlite3, subprocess, time
from pathlib import Path
P=Path(__file__).resolve().parents[2]
HOME=Path.home(); R=HOME/'Documents/BmgPocRuntime/stage-e'
CONFIG=HOME/'Documents/BmgPocRuntime/azure/stage-e-config.json'
DLL=P/'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll'
DOTNET=HOME/'Documents/BmgPocTools/dotnet/dotnet.exe'
DATA=P/'work/stage-e/dataset'; OUT=P/'outputs/stage-e'; OUT.mkdir(parents=True,exist_ok=True)
manifest=json.loads((DATA/'manifest.json').read_text())
test=[r for r in manifest['records'] if r['split']=='test']
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2),encoding='utf-8')
def stage(ident,records):
    dest=R/'staging'/ident
    if dest.exists(): return
    dest.mkdir(parents=True)
    docs=[]
    for i,r in enumerate(records):
        data=(DATA/r['path']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['sha256']
        name=f'document-{i+1:03}.pdf';(dest/name).write_bytes(data)
        docs.append(dict(documentId=f'doc-{i+1:03}',fileName=name,sha256=r['sha256']))
    write(dest/'submission.json',dict(schemaVersion='poc-1',submissionId=ident,revision=1,source='LocalStagingPoC',submissionType='Examination',documents=docs))
    (dest/'_READY').write_text('')
def run(*extra):
    result=subprocess.run([str(DOTNET),str(DLL),'--azure-documents','--root',str(R),'--azure-config',str(CONFIG),'--once',*extra],text=True,capture_output=True,timeout=3600)
    with (OUT/'live-worker-process.log').open('a',encoding='utf-8') as log:log.write(result.stdout+'\n'+result.stderr)
    print(result.stdout[-5000:],flush=True)
    return result.returncode
def sql(query):
    with sqlite3.connect(R/'state/intake.db') as db:
        db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute(query)]
def evaluate():
    jobs={j['submission_id']:j for j in sql('select * from jobs')}; results=[]
    for i,r in enumerate(test):
        j=jobs[f'stage-e-eval-{i+1:03}'];snap=Path(j['snapshot']); receipt=json.loads((snap/'classification.json').read_text())[0]
        layout=snap/'ai/doc-001-layout.json'; anchors=None
        if layout.exists():
            content=json.loads(layout.read_text())['content'];anchors=[a.lower() in content.lower() for a in r['anchors']]
        results.append(dict(expected=r['label'],predicted=receipt['documentType'],confidence=receipt['confidence'],accepted=receipt['accepted'],status=j['status'],scanned=r['scanned'],pages=r['pages'],ocrAnchors=anchors,submissionId=j['submission_id']))
    classes=manifest['classes']; confusion={a:{b:sum(r['expected']==a and r['predicted']==b for r in results) for b in classes} for a in classes}
    known=[r for r in results if r['expected']!='Other']; other=[r for r in results if r['expected']=='Other']
    summary=dict(threshold=0.8,testDocuments=len(results),correct=sum(r['expected']==r['predicted'] for r in results),knownAccepted=sum(r['accepted'] for r in known),knownDocuments=len(known),falseAccepted=sum(r['accepted'] and r['expected']!=r['predicted'] for r in results),otherRoutedToReview=sum(r['status']=='ManualException' for r in other),otherDocuments=len(other),ocrAnchorsFound=sum(sum(r['ocrAnchors'] or []) for r in results),ocrAnchorsChecked=sum(len(r['ocrAnchors'] or []) for r in results),confusionMatrix=confusion,results=results,pageReservations=sql('select kind,status,count(*) as requests,sum(pages) as pages from ai_requests group by kind,status'),limitations=manifest['limitations'])
    write(OUT/'held-out-evaluation.json',summary);print(json.dumps({k:v for k,v in summary.items() if k not in ('results','confusionMatrix','limitations')},indent=2),flush=True)
    return summary
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['stage','run','report','all']);action=parser.parse_args().action
    if action in ('stage','all'):
        for i,r in enumerate(test):stage(f'stage-e-eval-{i+1:03}',[r])
        print('Staged 28 held-out documents with neutral filenames and no gold labels.',flush=True)
    if action in ('run','all'):
        code=run();print(f'Worker exit {code}; Other documents should produce review status.',flush=True)
        assert code in (0,2)
    if action in ('report','all'):evaluate()
