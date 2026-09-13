"""Generate REST Layout sidecars required by custom classifier training; cache all operations."""
import base64, concurrent.futures, json, time, urllib.error, hashlib, socket
from pathlib import Path
from train_stage_e import DATA,OUT,ENDPOINT,API,BLOB,request,token,write
CACHE=DATA.parent/'training-layout';CACHE.mkdir(exist_ok=True)
def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)
def prepare(r):
    file=DATA/r['path'];digest=r['sha256']; resultfile=CACHE/(file.name+'.ocr.json');operationfile=CACHE/(file.name+'.operation.json')
    if not resultfile.exists():
        if operationfile.exists():
            saved=json.loads(operationfile.read_text());assert saved['sha256']==digest
            if not saved.get('operationLocation'):raise RuntimeError('Uncertain prior POST; manual reconciliation needed')
            operation=saved['operationLocation']
        else:
            data=file.read_bytes();assert hashlib.sha256(data).hexdigest()==digest
            save(operationfile,{'sha256':digest,'pages':r['pages'],'state':'Submitting'})
            status,headers,_=request('POST',ENDPOINT+'/documentintelligence/documentModels/prebuilt-layout:analyze?api-version='+API,'https://cognitiveservices.azure.com/',{'base64Source':base64.b64encode(data).decode()})
            assert status==202
            operation=next(v for k,v in headers.items() if k.lower()=='operation-location')
            save(operationfile,{'sha256':digest,'pages':r['pages'],'state':'Running','operationLocation':operation})
        assert operation.startswith(ENDPOINT+'/documentintelligence/documentModels/prebuilt-layout/analyzeResults/')
        for attempt in range(180):
            result=json.loads(request('GET',operation,'https://cognitiveservices.azure.com/')[2])
            if result['status']=='succeeded':
                assert result['analyzeResult']['apiVersion']==API
                assert len(result['analyzeResult']['pages'])==r['pages']
                save(resultfile,result);break
            if result['status'] in ('failed','canceled'):save(resultfile.with_suffix('.failed.json'),result);raise RuntimeError('Training OCR failed')
            time.sleep(3)
        else:raise RuntimeError('Training OCR polling timed out')
    url=BLOB+'stage-e-v1/'+r['label']+'/'+file.name+'.ocr.json'
    data=resultfile.read_bytes()
    try:request('PUT',url,'https://storage.azure.com/',data,{'x-ms-version':'2023-11-03','x-ms-blob-type':'BlockBlob','Content-Type':'application/json','If-None-Match':'*'})
    except urllib.error.HTTPError as e:
        if e.code not in (409,412):raise  # Read-back equality below is the acceptance condition.
    assert request('GET',url,'https://storage.azure.com/',headers={'x-ms-version':'2023-11-03'})[2]==data
    return r['pages']
if __name__=='__main__':
    train=[r for r in json.loads((DATA/'manifest.json').read_text())['records'] if r['split']=='train']
    assert len(train)==70 and sum(r['pages'] for r in train)==77
    assert all(a[4][0].startswith('10.84.1.') for a in socket.getaddrinfo(ENDPOINT.split('/')[2],443,type=socket.SOCK_STREAM))
    token('https://cognitiveservices.azure.com/');token('https://storage.azure.com/')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pages=0
        for i,future in enumerate(concurrent.futures.as_completed([pool.submit(prepare,r) for r in train])):
            pages+=future.result();print(f'Training Layout sidecars verified: {i+1}/70; pages: {pages}',flush=True)
    write('training-layout-summary.json',{'documents':70,'pages':pages,'apiVersion':API,'modelId':'prebuilt-layout','privateRuntimeRequests':True,'sidecarCache':str(CACHE)})
