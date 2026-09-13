"""Operator-only setup: immutable training upload, temporary network exception, resumable build."""
import json, subprocess, urllib.request, urllib.error, time, hashlib, datetime, shutil, sys, concurrent.futures, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/stage-e'; OUT.mkdir(parents=True,exist_ok=True)
DATA=ROOT/'work/stage-e/dataset'
SUB='6f841b52-7a6d-4287-b0e3-4591621bb363'; TENANT='e06201f9-0ec7-4863-80fc-85f43be49c1e'
BASE=f'/subscriptions/{SUB}/resourceGroups/rg-bmg-poc/providers/'
STORAGE=BASE+'Microsoft.Storage/storageAccounts/stbmgpocwjsvyjg25vqiy'
DI=BASE+'Microsoft.CognitiveServices/accounts/di-bmg-wjsvyjg25vqiy'
ENDPOINT='https://di-bmg-wjsvyjg25vqiy.cognitiveservices.azure.com'
BLOB='https://stbmgpocwjsvyjg25vqiy.blob.core.windows.net/training/'
MODEL='bmg-stage-e-v1'; API='2024-11-30'
TOKENS={}
OPERATOR='72ecc7b4-9bca-425f-9816-2562b5ab1ba7'; DI_PRINCIPAL='116acd80-fcea-4810-b3d8-5cac78c256f5'; WORKER='45701353-fc17-4a20-929c-a826685bd0b0'
# Recreated services/identities get new IDs. Historical evidence must never act as fresh run state.
if os.environ.get('BMG_TRAIN_SETTINGS'):
    settings=json.loads(Path(os.environ['BMG_TRAIN_SETTINGS']).read_text(encoding='utf-8-sig'))
    SUB=settings['subscriptionId'];TENANT=settings['tenantId'];STORAGE=settings['storageId'];DI=settings['documentIntelligenceId']
    ENDPOINT=settings['documentIntelligenceEndpoint'].rstrip('/');BLOB=settings['blobEndpoint'].rstrip('/')+'/training/'
    OPERATOR=settings['operatorObjectId'];DI_PRINCIPAL=settings['documentIntelligencePrincipalId'];WORKER=settings['workerPrincipalId']
    OUT=Path(settings['outputDirectory']);OUT.mkdir(parents=True,exist_ok=True)
    if OUT.resolve()==(ROOT/'outputs/stage-e').resolve():raise RuntimeError('Recreation must use a fresh output directory')
def az(*args):
    p=subprocess.run([shutil.which('az') or 'az.cmd',*args,'-o','json','--only-show-errors'],capture_output=True,text=True)
    if p.returncode: raise RuntimeError('Azure CLI failed: '+p.stderr[:1000])
    return json.loads(p.stdout) if p.stdout.strip() else None
def token(resource):
    if resource not in TOKENS or TOKENS[resource][1]<time.time():
        TOKENS[resource]=(az('account','get-access-token','--resource',resource)['accessToken'],time.time()+1800)
    return TOKENS[resource][0]
def request(method,url,resource,data=None,headers=None):
    h={'Authorization':'Bearer '+token(resource),**(headers or {})}
    if isinstance(data,dict): data=json.dumps(data).encode(); h['Content-Type']='application/json'
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h,method=method),timeout=90) as r:
        body=r.read(); return r.status,dict(r.headers),body
def write(name,value):
    p=OUT/name; tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(value,indent=2),encoding='utf-8'); tmp.replace(p)
def arm(method,rid,data=None):
    return json.loads(request(method,'https://management.azure.com'+rid+'?api-version=2023-05-01','https://management.azure.com/',data)[2])
def role(principal,kind,role_id,scope):
    existing=az('role','assignment','list','--scope',scope,'--query',f"[?principalId=='{principal}' && ends_with(roleDefinitionId, '{role_id}')]")
    if existing:return None
    return az('role','assignment','create','--assignee-object-id',principal,'--assignee-principal-type',kind,'--role',role_id,'--scope',scope)['id']
def upload_pdf(r):
    data=(DATA/r['path']).read_bytes(); assert hashlib.sha256(data).hexdigest()==r['sha256']
    url=BLOB+'stage-e-v1/'+r['label']+'/'+Path(r['path']).name
    headers={'x-ms-version':'2023-11-03','x-ms-blob-type':'BlockBlob','Content-Type':'application/pdf','If-None-Match':'*'}
    for attempt in range(20):
        try:request('PUT',url,'https://storage.azure.com/',data,headers);break
        except urllib.error.HTTPError as e:
            if e.code in (409,412):break  # Existing bytes are independently hash-verified below.
            if e.code==403 and attempt<19:time.sleep(10);continue
            raise
    content=request('GET',url,'https://storage.azure.com/',headers={'x-ms-version':'2023-11-03'})[2]
    assert hashlib.sha256(content).hexdigest()==r['sha256']
def main():
    assert az('account','show')['id']==SUB
    manifest=json.loads((DATA/'manifest.json').read_text()); train=[r for r in manifest['records'] if r['split']=='train']
    scope=STORAGE+'/blobServices/default/containers/training'
    prior_roles=OUT/'role-setup-latest.json'
    temporary=json.loads(prior_roles.read_text()).get('temporaryAssignmentIds',[]) if prior_roles.exists() else []
    if any(not rid.lower().startswith(STORAGE.lower()+'/') or '/providers/microsoft.authorization/roleassignments/' not in rid.lower() for rid in temporary):
        raise RuntimeError('Temporary role inventory is outside the POC storage scope')
    # Persist each created assignment immediately so interrupted setup remains auditable.
    for principal,kind,roleid,rscope,temp in [
      (OPERATOR,'User','ba92f5b4-2d11-453d-a403-e96b0029c9fe',scope,True),
      (DI_PRINCIPAL,'ServicePrincipal','ba92f5b4-2d11-453d-a403-e96b0029c9fe',STORAGE,True),
      (WORKER,'ServicePrincipal','a97b65f3-24c7-4388-baec-2e87135dc908',DI,False)]:
        rid=role(principal,kind,roleid,rscope)
        if rid and temp:temporary.append(rid)
        if rid:write('role-setup-latest.json',{'temporaryAssignmentIds':temporary,'latestAssignmentId':rid})
    before=arm('GET',STORAGE)['properties']
    before['networkAcls'].setdefault('resourceAccessRules',[])
    if before['publicNetworkAccess']!='Disabled' or before['networkAcls']['defaultAction']!='Deny':raise RuntimeError('Unexpected storage baseline')
    write('storage-before-training.json',{'publicNetworkAccess':before['publicNetworkAccess'],'networkAcls':before['networkAcls']})
    try:
        token('https://storage.azure.com/')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for i,future in enumerate(concurrent.futures.as_completed([pool.submit(upload_pdf,r) for r in train])):
                future.result()
                if i%10==9:print(f'Training PDFs uploaded and hash-verified: {i+1}/{len(train)}',flush=True)
        write('training-upload.json',{'documents':len(train),'pages':sum(r['pages'] for r in train),'testDocumentsUploaded':0,'manifestSha256':hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest(),'blobPrefix':BLOB+'stage-e-v1/'})
        subprocess.run([sys.executable,str(Path(__file__).with_name('prepare_stage_e_layout.py'))],check=True)
        acl=dict(before['networkAcls']);acl['resourceAccessRules']=[{'resourceId':DI,'tenantId':TENANT}];acl['bypass']='None'
        arm('PATCH',STORAGE,{'properties':{'publicNetworkAccess':'Enabled','networkAcls':acl}})
        write('storage-training-exception.json',{'publicNetworkAccess':'Enabled','networkAcls':acl,'purpose':'Temporary DI system managed identity training fetch only; no IP allowlist or broad trusted-service bypass.'})
        print('Training access configured; allowing 60 seconds for firewall propagation.',flush=True)
        for _ in range(6):time.sleep(10)
        operation_file=OUT/'training-operation.json'
        failed_result=OUT/'training-result.json'
        if failed_result.exists() and json.loads(failed_result.read_text()).get('status')=='failed':
            failed_id=json.loads(failed_result.read_text())['operationId']
            failed_result.rename(OUT/('training-failed-'+failed_id+'.json'))
            operation_file.rename(OUT/('training-operation-failed-'+failed_id+'.json'))
        if operation_file.exists(): operation=json.loads(operation_file.read_text())['operationLocation']
        else:
            body={'classifierId':MODEL,'description':'Synthetic seven-class POC; frozen split stage-e-v1','docTypes':{c:{'azureBlobSource':{'containerUrl':BLOB.rstrip('/'),'prefix':'stage-e-v1/'+c+'/'}} for c in manifest['classes']}}
            write('training-request.json',body)
            intent=OUT/'training-submit-intent.json'
            if intent.exists():raise RuntimeError('Prior training POST has no operation record; reconcile it before resubmitting')
            write('training-submit-intent.json',{'classifierId':MODEL,'submittedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
            status,headers,result=request('POST',ENDPOINT+'/documentintelligence/documentClassifiers:build?api-version='+API,'https://cognitiveservices.azure.com/',body)
            assert status==202
            operation=next(v for k,v in headers.items() if k.lower()=='operation-location')
            write('training-operation.json',{'operationLocation':operation,'submittedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
            intent.unlink()
        assert operation.startswith(ENDPOINT+'/documentintelligence/operations/')
        for attempt in range(180):
            result=json.loads(request('GET',operation,'https://cognitiveservices.azure.com/')[2])
            if attempt%6==0:print('Classifier training: '+result['status'],flush=True)
            if result['status'] in ('succeeded','failed','canceled'):
                write('training-result.json',result)
                if result['status']!='succeeded':raise RuntimeError('Training failed; see safe service result')
                break
            time.sleep(10)
        else:raise RuntimeError('Training polling timed out; resume recorded operation')
    finally:
        arm('PATCH',STORAGE,{'properties':{'publicNetworkAccess':before['publicNetworkAccess'],'networkAcls':before['networkAcls']}})
        restored=arm('GET',STORAGE)['properties']
        # Remove setup roles even if a later verification detects a cleanup discrepancy.
        for rid in temporary:az('role','assignment','delete','--ids',rid)
        write('training-cleanup.json',{'storagePublicNetworkAccess':restored['publicNetworkAccess'],'networkAcls':restored['networkAcls'],'removedTemporaryRoleAssignments':temporary,'verifiedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
        assert restored['publicNetworkAccess']=='Disabled' and not restored['networkAcls'].get('resourceAccessRules')
        print('Storage restored to private-only; temporary training role assignments removed.',flush=True)
if __name__=='__main__':main()
