"""Scan tracked backup bytes for credential patterns and record hashes without printing matches."""
import hashlib,json,re,subprocess,zipfile
from pathlib import Path
P=Path(__file__).resolve().parents[2]
paths=subprocess.check_output(['git','ls-files','-z'],cwd=P).decode().split('\0');paths=[p for p in paths if p]
paths=[p for p in paths if p not in ('outputs/github-backup/security-review.json','outputs/github-backup/file-manifest.json')]
patterns={
 'private_key':rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----',
 'github_token':rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,})\b',
 'jwt':rb'\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}',
 'sas_signature':rb'[?&](?:amp;)?sig=[A-Za-z0-9%+/=]{20,}',
 'storage_account_key':rb'AccountKey=[A-Za-z0-9+/]{40,}={0,2}',
 'literal_credential':rb'"(?:clientSecret|accessToken|refreshToken|secretText|password)"\s*:\s*"[^"\r\n]{12,}"'
}
findings=[];inventory=[]
for relative in paths:
 path=P/relative;payload=path.read_bytes()
 if path.suffix.lower() in ('.pfx','.p12','.key','.pem','.publishsettings'):findings.append(dict(path=relative,rule='forbidden_credential_file'))
 if len(payload)>=100*1024*1024:findings.append(dict(path=relative,rule='github_size_limit'))
 parts=[('',payload)]
 if path.suffix.lower() in ('.docx','.pptx','.xlsx'):
  with zipfile.ZipFile(path) as z:parts += [(n,z.read(n)) for n in z.namelist() if n.endswith(('.xml','.rels'))]
 for member,content in parts:
  for name,pattern in patterns.items():
   if re.search(pattern,content):findings.append(dict(path=relative,member=member,rule=name))
 inventory.append(dict(path=relative,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest()))
report=dict(filesScanned=len(paths),bytes=sum(p['bytes'] for p in inventory),findings=findings,excludedCredentials=True,limitations='Pattern scan is not a guarantee; intended contents and file exclusions were also reviewed.')
out=P/'outputs/github-backup';out.mkdir(exist_ok=True)
(out/'security-review.json').write_text(json.dumps(report,indent=2))
(out/'file-manifest.json').write_text(json.dumps(dict(files=inventory),indent=2))
print(json.dumps(report))
raise SystemExit(1 if findings else 0)
