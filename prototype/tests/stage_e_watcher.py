"""Prove a new ready packet is processed by the running real classifier/OCR watcher."""
import json,sqlite3,subprocess,time
from pathlib import Path
from stage_e_acceptance import R,CONFIG,DLL,DOTNET,OUT,stage,test
ident='stage-e-watch-001'
with (OUT/'watcher-process.log').open('w') as log:
    process=subprocess.Popen([str(DOTNET),str(DLL),'--azure-documents','--root',str(R),'--azure-config',str(CONFIG),'--poll-ms','1000'],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        time.sleep(3);assert process.poll() is None
        stage(ident,[next(r for r in test if r['label']=='Note' and r['index']==2)])
        for _ in range(180):
            with sqlite3.connect(R/'state/intake.db') as db:
                db.row_factory=sqlite3.Row;row=db.execute('select * from jobs where submission_id=?',(ident,)).fetchone()
            if row and row['status']=='LayoutRead':break
            if row and row['status'] in ('ManualException','RetryExhausted'):raise AssertionError(dict(row))
            if process.poll() is not None:raise AssertionError('Watcher exited unexpectedly')
            time.sleep(2)
        else:raise AssertionError('Watcher timeout')
        report=dict(passed=True,stagedAfterWorkerStarted=True,submissionId=ident,finalStatus=row['status'],snapshot=row['snapshot'],llmPerformed=False,cosmosWritten=False)
    finally:
        # This owned process is stopped only after a durable terminal checkpoint or bounded test failure.
        if process.poll() is None:process.terminate()
        process.wait(timeout=30)
        log.flush()
report['workerStopped']=True
(OUT/'watcher-results.json').write_text(json.dumps(report,indent=2))
print('PASS real watcher: new packet automatically reached LayoutRead; worker stopped.',flush=True)
