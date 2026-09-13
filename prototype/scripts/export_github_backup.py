"""Export synthetic runtime evidence; never copy login caches, AzCopy job files or credentials."""
import hashlib,json,sqlite3
from pathlib import Path
P=Path(__file__).resolve().parents[2];R=Path.home()/'Documents/BmgPocRuntime';O=P/'archive/runtime'
records=[]
for source in R.rglob('*'):
 if not source.is_file():continue
 relative=source.relative_to(R)
 if any(part in ('azure','azcopy','logs','bin','obj','__pycache__') for part in relative.parts):continue
 if source.suffix.lower() not in ('.pdf','.json','.db'):continue
 target=O/relative;target.parent.mkdir(parents=True,exist_ok=True)
 if source.suffix=='.db':
  with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db:
   with sqlite3.connect(target) as backup:db.backup(backup)
 else:target.write_bytes(source.read_bytes())
 records.append(dict(path=target.relative_to(P).as_posix(),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
(P/'archive/runtime-manifest.json').write_text(json.dumps(dict(files=records,excluded=['Azure login and identity runtime state','private keys/certificates','AzCopy job plans and logs','build/dependency caches'],syntheticDataOnly=True),indent=2))
print(json.dumps(dict(exportedFiles=len(records),bytes=sum(r['bytes'] for r in records))))
