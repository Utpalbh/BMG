"""Read the same Cost Management data surfaced by Azure portal; retain scope and lag caveats."""
import argparse,datetime,json,urllib.error
from pathlib import Path
from train_stage_e import SUB,request
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[2]/'outputs/overnight');args=parser.parse_args()
OUT=args.output;OUT.mkdir(parents=True,exist_ok=True)
now=datetime.datetime.now(datetime.timezone.utc)
results={}
for label,scope,timeframe,group in [('poc',f'/subscriptions/{SUB}/resourceGroups/rg-bmg-poc','Custom','ServiceName'),('subscriptionMonthToDate',f'/subscriptions/{SUB}','MonthToDate','ResourceGroupName')]:
    body={'type':'ActualCost','timeframe':timeframe,'dataset':{'granularity':'None','aggregation':{'totalCost':{'name':'Cost','function':'Sum'}},'grouping':[{'type':'Dimension','name':group}]}}
    if timeframe=='Custom':body['timePeriod']={'from':'2026-09-10T00:00:00Z','to':now.isoformat()}
    try:
        raw=json.loads(request('POST','https://management.azure.com'+scope+'/providers/Microsoft.CostManagement/query?api-version=2023-11-01','https://management.azure.com/',body,{'ClientType':'GitHubCopilotForAzure'})[2])
        (OUT/(label+'-latest-bill-raw.json')).write_text(json.dumps(raw,indent=2))
        cols=[c['name'] for c in raw['properties']['columns']];rows=[dict(zip(cols,r)) for r in raw['properties']['rows']]
        results[label]={'scope':scope,'timeframe':timeframe,'reportedTotal':sum(r['Cost'] for r in rows),'currencies':list({r['Currency'] for r in rows}),'breakdown':rows,'hasMorePages':bool(raw['properties'].get('nextLink'))}
    except urllib.error.HTTPError as e:
        results[label]={'available':False,'httpStatus':e.code};break
result={'queriedUtc':now.isoformat(),'dataMayLag':True,'notFinalInvoice':True,**results}
(OUT/'latest-bill-summary.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
