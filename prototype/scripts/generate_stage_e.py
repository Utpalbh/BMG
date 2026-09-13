"""Reproducible synthetic classifier corpus. Gold labels never enter runtime manifests."""
import hashlib, json, subprocess, uuid
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from pypdf import PdfReader
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work/stage-e/dataset'
POP = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'
CLASSES = {
 'Note': ('PROMISSORY NOTE', 'Promise to pay', 'The borrower promises to pay the principal sum to the lender, with interest. Monthly installments are due on the first day of each month. Late charges apply after fifteen days. The unpaid balance may be accelerated following default.'),
 'DeedOfTrust': ('DEED OF TRUST', 'Conveyance in trust', 'The grantor conveys the described property to the trustee in trust, with power of sale, to secure repayment of the indebtedness. The beneficiary holds the security interest. This instrument shall be recorded in the county land records.'),
 'TitleCommitment': ('COMMITMENT FOR TITLE INSURANCE', 'Schedule A and Schedule B', 'The title insurer commits to issue a loan policy subject to the requirements and exceptions listed below. Vesting is fee simple. Requirements include recording the security instrument and payment of outstanding taxes. Easements of record are excepted from coverage.'),
 'Survey': ('BOUNDARY SURVEY', 'Surveyor certification', 'A field survey establishes the boundaries of the parcel. Bearings and distances are shown on the plat. Found iron rods mark the corners. The surveyor certifies that the depicted improvements and easements reflect the observed conditions. This is not a title opinion.'),
 'ClosingInstructions': ('LENDER CLOSING INSTRUCTIONS', 'Instructions to settlement agent', 'The settlement agent must verify borrower identity, obtain signed loan documents, and disburse funds only after authorization. Return the executed package to the lender. Resolve all outstanding conditions before recording. Do not fund if the final figures differ from the approved statement.'),
 'Rider': ('ADJUSTABLE RATE RIDER', 'Amendment to security instrument', 'This rider is incorporated into the security instrument and supplements the note. The interest rate may change on each adjustment date based on the index plus margin, subject to periodic and lifetime caps. In the event of conflict these additional covenants control.'),
 'Other': ('COMMUNITY ACTIVITY RECORD', 'Administrative record', 'This record concerns a community activity. It does not create a loan, convey property, insure title, certify a survey, direct a closing or amend a security instrument.')}

def make_pdf(path, label, split, index, extra_rows=None):
    title, heading, prose = CLASSES[label]
    family = ('A','B')[index%2] if split=='train' else ('C','D')[index%2]
    person = f'{"Avery" if split=="train" else "Morgan"} {"Cedar" if split=="train" else "Willow"}{index+1}'
    loan = f'{"71" if split=="train" else "92"}{index+1:06d}'
    address = f'{100+index*17} {"Birch" if split=="train" else "Juniper"} Lane, Austin, TX 78701'
    rows = [('Loan number',loan),('Borrower',person),('Property address',address),('Lender','Fictional Prairie Lending'),('Principal amount',f'${240000+index*12500:,.2f}')]
    if label=='Other':
        topics=['LIBRARY CHECKOUT RECEIPT','GARDEN CLUB MINUTES','WEATHER OBSERVATION LOG','CAFETERIA MENU','BOOKSTORE INVOICE'] if split=='train' else ['MUSEUM ADMISSION TICKET','SWIMMING LESSON SCHEDULE','EQUIPMENT REPAIR RECEIPT','COMMUNITY BUS TIMETABLE']
        title=topics[index%len(topics)]; heading='Activity details'
        prose='Reference record for local community services. Keep this copy for your records. Items and attendance were checked by the service desk. Please contact the coordinator for questions about dates and opening hours.'
        rows=[('Reference',loan),('Visitor',person),('Location','Fictional Community Center'),('Date','September 11, 2026'),('Record status','Confirmed')]
    if extra_rows:
        rows += extra_rows
    path.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(path),pagesize=(612,792),invariant=1)
    pages=2 if index==0 else 1
    for page in range(pages):
        c.setFillColorRGB(.12,.22,.29); c.setFont('Helvetica-Bold',9)
        c.drawString(45,755,'BMG SYNTHETIC TEST MATERIAL - NOT FOR EXECUTION')
        font='Times-Roman' if family in ('B','D') else 'Helvetica'
        c.setFillColorRGB(0,0,0); c.setFont(font,18)
        y=716
        for line in simpleSplit(title + (' - CONTINUATION' if page else ''),font,18,510): c.drawString(45,y,line); y-=22
        y-=20
        if family in ('A','C'):
            ordered=rows if family=='A' else list(reversed(rows))
            for key,value in ordered:
                c.setFont('Helvetica-Bold',10); c.drawString(45,y,key.upper() if family=='C' else key)
                c.setFont(font,11); c.drawString(190,y,value); y-=28
        else:
            text=('This instrument identifies ' if family=='B' else 'Record particulars: ')+'; '.join(f'{k}: {v}' for k,v in rows)+'.'
            c.setFont(font,11)
            for line in simpleSplit(text,font,11,510): c.drawString(45,y,line); y-=17
            y-=22
        c.setFont('Helvetica-Bold',12); c.drawString(45,y,heading); y-=24
        c.setFont(font,11)
        for line in simpleSplit(prose if split=='train' else 'Review the following provisions carefully. '+prose.replace('The ','This ').replace('must ','shall '),font,11,510):
            c.drawString(45,y,line); y-=18
        if label=='Survey':
            y-=115; c.rect(90,y,280,90); c.line(90,y,370,y+90)
            c.setFont('Helvetica',9); c.drawString(120,y+100,'N 89 30 E - 120.00 feet'); c.drawString(390,y+45,'Iron rod')
        y-=38; c.setFont(font,10); c.drawString(45,y,'Authorized representative: __________________    Date: ______________')
        c.setFont('Helvetica',8); c.drawString(45,32,f'Synthetic only | Page {page+1} of {pages} | No legal effect')
        c.showPage()
    c.save()
    scanned=index%5==1 if split=='train' else index==1
    preview=path.with_suffix('')
    if scanned:
        subprocess.run([str(POP),'-r','150','-gray','-png',str(path),str(preview)],check=True,capture_output=True)
        images=[]
        for p in sorted(path.parent.glob(preview.name+'-*.png')):
            with Image.open(p) as img: images.append(img.convert('RGB').rotate(.25,fillcolor='white'))
            p.unlink()
        images[0].save(path,'PDF',resolution=150,save_all=True,append_images=images[1:])
        for img in images: img.close()
    assert len(PdfReader(path).pages)==pages
    return dict(label=label,split=split,index=index,layoutFamily=family,scanned=scanned,pages=pages,path=str(path.relative_to(OUT)).replace('\\','/'),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),anchors=[loan,person],gold={'loanNumber':loan,'borrowerName':person,'propertyAddress':address})

def main():
    if (OUT/'manifest.json').exists(): raise SystemExit('Dataset already exists; do not overwrite the frozen split.')
    records=[]
    for split,count in [('train',10),('test',4)]:
        for label in CLASSES:
            for i in range(count):
                name=str(uuid.uuid5(uuid.NAMESPACE_URL,f'bmg-stage-e-v1/{split}/{label}/{i}'))+'.pdf'
                records.append(make_pdf(OUT/split/label/name,label,split,i))
    assert len({r['sha256'] for r in records})==98
    manifest={'version':'stage-e-v1','classificationThreshold':0.8,'classes':list(CLASSES),'records':records,'limitations':['Synthetic documents only; no client accuracy claim.','Template families and identities are disjoint; class-specific vocabulary overlaps by design.','Other is a sampled negative class, not universal out-of-distribution detection.']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    qa=OUT.parent/'qa'; qa.mkdir(exist_ok=True)
    tiles=[]
    for label in CLASSES:
        for split,i in [('train',0),('train',1),('test',0),('test',1)]:
            r=next(r for r in records if r['label']==label and r['split']==split and r['index']==i)
            dest=qa/f'{label}-{split}-{i}'
            subprocess.run([str(POP),'-f','1','-singlefile','-scale-to','650','-png',str(OUT/r['path']),str(dest)],check=True,capture_output=True)
            with Image.open(dest.with_suffix('.png')) as im:
                tile=Image.new('RGB',(510,690),'white'); im.thumbnail((510,650)); tile.paste(im,((510-im.width)//2,30)); ImageDraw.Draw(tile).text((10,8),f'{label} {split} {r["layoutFamily"]} scan={r["scanned"]}',fill='black'); tiles.append(tile)
    for n in range(7):
        sheet=Image.new('RGB',(2040,690),'white')
        for i,tile in enumerate(tiles[n*4:n*4+4]): sheet.paste(tile,(i*510,0))
        sheet.save(qa/f'contact-{n}.png')
    print(json.dumps({'documents':len(records),'trainPages':sum(r['pages'] for r in records if r['split']=='train'),'testPages':sum(r['pages'] for r in records if r['split']=='test'),'manifest':str(OUT/'manifest.json')}))
if __name__=='__main__': main()
