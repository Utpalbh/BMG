"""Read-only POC inventory and cost snapshot; does not delete or change cloud resources."""
import json,datetime,urllib.error
from pathlib import Path
from train_stage_e import az,request,SUB,STORAGE,arm
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/overnight';OUT.mkdir(exist_ok=True)
def save(name,data):(OUT/name).write_text(json.dumps(data,indent=2),encoding='utf-8')
resources=az('resource','list','-g','rg-bmg-poc')
save('resource-inventory.json',resources)
save('openai-deployments.json',az('cognitiveservices','account','deployment','list','-g','rg-bmg-poc','-n','oai-bmg-wjsvyjg25vqiy'))
now=datetime.datetime.now(datetime.timezone.utc)
body={'type':'ActualCost','timeframe':'Custom','timePeriod':{'from':'2026-09-10T00:00:00Z','to':now.isoformat()},'dataset':{'granularity':'None','aggregation':{'totalCost':{'name':'Cost','function':'Sum'}},'grouping':[{'type':'Dimension','name':'ServiceName'}]}}
try:
    raw=request('POST',f'https://management.azure.com/subscriptions/{SUB}/resourceGroups/rg-bmg-poc/providers/Microsoft.CostManagement/query?api-version=2023-11-01','https://management.azure.com/',body,{'ClientType':'GitHubCopilotForAzure'})[2]
    cost=json.loads(raw);save('reported-costs.json',cost)
except urllib.error.HTTPError as e:
    save('reported-costs.json',{'available':False,'httpStatus':e.code,'note':'No retry loop; reporting may be unavailable or throttled.'})
stoptypes=['Microsoft.Compute/virtualMachines','Microsoft.Compute/virtualMachineScaleSets','Microsoft.ContainerService/managedClusters','Microsoft.Web/sites','Microsoft.ContainerInstance/containerGroups']
save('overnight-review.json',{'checkedUtc':now.isoformat(),'resourceGroup':'rg-bmg-poc','stoppableComputeResources':[r['name'] for r in resources if r['type'] in stoptypes],
    'networkPauseAvailable':False,'referenceNetworkInrPerHour':49.21,'referenceOnlyNotLiveBill':True,'preserveNetworkUnlessDeletionApproved':True,
    'actionAfterStageE':'Stop local POC processing; retain synthetic data and trained model; shut down laptop as requested. No further application calls while off.',
    'continuingCharges':'Provisioned VPN gateway, DNS resolver endpoint, private endpoints, public IP, DNS zones and stored data continue billing unless deleted.',
    'costReportingMayLag':True})
print('Saved overnight resource inventory and reported-cost snapshot. No stoppable compute resources:',not any(r['type'] in stoptypes for r in resources))
