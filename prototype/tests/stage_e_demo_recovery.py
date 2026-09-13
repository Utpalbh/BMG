"""Extra integration packet plus real crash-before-checkpoint recovery; preserves every artifact."""
import argparse,hashlib,json,sqlite3,subprocess,time
from pathlib import Path
P=Path(__file__).resolve().parents[2];H=Path.home();R=H/'Documents/BmgPocRuntime/stage-e';O=P/'outputs/stage-e'
DOTNET=H/'Documents/BmgPocTools/dotnet/dotnet.exe';DLL=P/'prototype/src/Bmg.Intake.Worker/bin/Release/net10.0/Bmg.Intake.Worker.dll';CONFIG=H/'Documents/BmgPocRuntime/azure/stage-e-config.json'
def sql(query):
    with sqlite3.connect(R/'state/intake.db') as db:db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute(query)]
def run(*args):
    p=subprocess.run([str(DOTNET),str(DLL),'--azure-documents','--root',str(R),'--azure-config',str(CONFIG),'--once',*args],capture_output=True,text=True,timeout=1800)
    with (O/'demo-recovery-process.log').open('a') as f:f.write(p.stdout+'\n'+p.stderr)
    print(p.stdout[-2500:],flush=True);return p
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--generated',action='store_true');args=parser.parse_args()
    ident='stage-e-supported-demo-001' if args.generated else 'stage-e-demo-001'
    source=P/'BMG_MVP_Synthetic_Test_Data/synthetic-data/submission-001'; dest=R/'staging'/ident
    if not dest.exists():
        dest.mkdir(parents=True);docs=[]
        if args.generated:
            data_root=P/'work/stage-e/dataset';dataset=json.loads((data_root/'manifest.json').read_text())
            records=[r for r in dataset['records'] if r['split']=='test'];evaluation=json.loads((O/'held-out-evaluation.json').read_text())['results']
            candidates=[n for n in range(4) if all(e['accepted'] for r,e in zip(records,evaluation) if r['label']!='Other' and r['index']==n)]
            assert candidates,'No complete supported packet exists at the frozen threshold'
            files=[data_root/r['path'] for r in records if r['label']!='Other' and r['index']==candidates[0]]
        else:files=[source/d['fileName'] for d in json.loads((source/'submission.json').read_text())['documents']]
        for i,file in enumerate(files):
            data=file.read_bytes();name=f'document-{i+1:03}.pdf';(dest/name).write_bytes(data)
            docs.append(dict(documentId=f'doc-{i+1:03}',fileName=name,sha256=hashlib.sha256(data).hexdigest()))
        (dest/'submission.json').write_text(json.dumps(dict(schemaVersion='poc-1',submissionId=ident,revision=1,source='LocalStagingPoC',submissionType='Examination',documents=docs)))
        (dest/'_READY').write_text('')
    p=run('--crash-after-effect','LayoutRead')
    job=sql("select * from jobs where submission_id='"+ident+"'")[0]
    if p.returncode!=75:
        (O/'original-packet-result.json').write_text(json.dumps(dict(job=job,classifications=json.loads((Path(job['snapshot'])/'classification.json').read_text())),indent=2))
        raise SystemExit('Original packet did not reach LayoutRead; inspect classifications and report this result honestly.')
    before=sql('select request_key,kind,pages,status,operation from ai_requests order by request_key')
    assert job['stage']==3 and (Path(job['snapshot'])/'layout-summary.json').exists()
    p=run();after=sql('select request_key,kind,pages,status,operation from ai_requests order by request_key')
    job=sql("select * from jobs where submission_id='"+ident+"'")[0]
    assert p.returncode in (0,2) and job['status']=='LayoutRead' and before==after
    summary=dict(passed=True,submissionId=ident,packetKind='Previously evaluated supported synthetic packet' if args.generated else 'Original supplied synthetic packet',crashExitCode=75,checkpointBeforeCrash='Classified',finalStatus=job['status'],replayAddedAiRequests=0,requestRecordsUnchanged=True,snapshot=job['snapshot'],classification=json.loads((Path(job['snapshot'])/'classification.json').read_text()),layout=json.loads((Path(job['snapshot'])/'layout-summary.json').read_text()))
    (O/'demo-recovery-results.json').write_text(json.dumps(summary,indent=2));print('PASS live OCR crash recovery: zero additional AI requests.',flush=True)
