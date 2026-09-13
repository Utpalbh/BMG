"""Build and check planning contracts. Does not create or modify Azure resources."""
from pathlib import Path
from copy import deepcopy
import json
import sys
sys.path.insert(0, str(Path(__file__).parent / 'python-packages'))
from jsonschema import Draft202012Validator, FormatChecker

root = Path.cwd()
out = root / 'outputs' / 'stage-a'
policy = json.loads((out / 'metadata-policy.json').read_text(encoding='utf-8'))
names = list(policy['fields'])
value_properties = {name: {'type': ['string', 'null'], 'minLength': 1} for name in names}
value_properties['closingDate']['format'] = 'date'
for name, rule in policy['fields'].items():
    if 'allowedValues' in rule:
        value_properties[name]['enum'] = rule['allowedValues'] + [None]

schema = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'BMG POC result returned at diagram step 10',
    'description': 'Application result contract, not the LLM API schema. Business and evidence validation still run in code.',
    'type': 'object', 'additionalProperties': False,
    'required': ['schemaVersion', 'submissionId', 'revision', 'status', 'metadata', 'provenance', 'validationErrors'],
    'properties': {
        'schemaVersion': {'const': 'poc-1'},
        'submissionId': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$'},
        'revision': {'type': 'integer', 'minimum': 1},
        'status': {'enum': ['Validated', 'ManualException']},
        'metadata': {'type': 'object', 'additionalProperties': False, 'required': names, 'properties': value_properties},
        'provenance': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['field', 'sourceKind', 'documentId', 'page', 'evidenceText', 'modelId', 'promptVersion'],
            'properties': {
                'field': {'enum': names}, 'sourceKind': {'enum': ['Document', 'Manifest']},
                'documentId': {'type': ['string', 'null']},
                'page': {'type': ['integer', 'null'], 'minimum': 1},
                'evidenceText': {'type': 'string', 'minLength': 1},
                'modelId': {'type': ['string', 'null']},
                'promptVersion': {'type': ['string', 'null']}
            },
            'allOf': [{
                'if': {'properties': {'sourceKind': {'const': 'Document'}}},
                'then': {'properties': {'documentId': {'type': 'string', 'minLength': 1}, 'page': {'type': 'integer', 'minimum': 1}, 'modelId': {'type': 'string', 'minLength': 1}, 'promptVersion': {'type': 'string', 'minLength': 1}}},
                'else': {'properties': {'documentId': {'type': 'null'}, 'page': {'type': 'null'}}}
            }]
        }},
        'validationErrors': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}
    },
    'allOf': [{
        'if': {'properties': {'status': {'const': 'Validated'}}},
        'then': {'properties': {
            'metadata': {'properties': {name: {'type': 'string', 'minLength': 1} for name in names}},
            'provenance': {'minItems': len(names)}, 'validationErrors': {'maxItems': 0}
        }},
        'else': {'properties': {'validationErrors': {'minItems': 1}}}
    }],
    '$comment': 'Application must additionally check evidence coverage for every selected field, uniqueness, real source existence, text support, page bounds, normalization, conflicts, classification and replay state. Provenance array size alone is not proof of evidence coverage.'
}
(out / 'result.schema.json').write_text(json.dumps(schema, indent=2) + '\n', encoding='utf-8')

manifest_schema = json.loads((out / 'submission.schema.json').read_text(encoding='utf-8'))
for item in [schema, manifest_schema]:
    Draft202012Validator.check_schema(item)
result_validator = Draft202012Validator(schema, format_checker=FormatChecker())
manifest_validator = Draft202012Validator(manifest_schema, format_checker=FormatChecker())
checked = 0
for folder in sorted((root / 'BMG_MVP_Synthetic_Test_Data' / 'synthetic-data').glob('submission-*')):
    original = json.loads((folder / 'submission.json').read_text())
    expected = json.loads((folder / 'expected-invoice-metadata.json').read_text())
    manifest = {
        'schemaVersion': 'poc-1', 'submissionId': original['submissionId'], 'revision': 1,
        'source': 'LocalStagingPoC', 'submissionType': original['submissionType'],
        'documents': [{'documentId': f'doc-{i+1:03}', 'fileName': d['fileName'], 'sha256': d['sha256']} for i, d in enumerate(original['documents'])]
    }
    manifest_validator.validate(manifest)
    result = {
        'schemaVersion': 'poc-1', 'submissionId': original['submissionId'], 'revision': 1,
        'status': 'Validated', 'metadata': {n: expected['invoiceMetadata'][n] for n in names},
        'provenance': [
            {'field': n, 'sourceKind': 'Manifest' if n == 'submissionType' else 'Document',
             'documentId': None if n == 'submissionType' else 'doc-001', 'page': None if n == 'submissionType' else 1,
             'evidenceText': 'SCHEMA TEST FIXTURE ONLY; not verified extraction',
             'modelId': None if n == 'submissionType' else 'SCHEMA-TEST',
             'promptVersion': None if n == 'submissionType' else 'SCHEMA-TEST'} for n in names
        ], 'validationErrors': []
    }
    result_validator.validate(result)
    checked += 1

rejections = []
def must_reject(validator, candidate, label):
    if validator.is_valid(candidate):
        raise AssertionError(f'Expected rejection: {label}')
    rejections.append(label)

bad = deepcopy(manifest); bad['documents'][0]['documentType'] = 'Note'
must_reject(manifest_validator, bad, 'Classifier label in runtime manifest')
bad = deepcopy(manifest); bad['documents'][0]['fileName'] = '../escape.pdf'
must_reject(manifest_validator, bad, 'Relative path traversal')
bad = deepcopy(result); bad['metadata']['loanNumber'] = None
must_reject(result_validator, bad, 'Validated result with missing required value')
bad = deepcopy(result); bad['metadata']['closingDate'] = '2026-02-30'
must_reject(result_validator, bad, 'Invalid calendar date')
bad = deepcopy(result); bad['validationErrors'] = ['Conflict']
must_reject(result_validator, bad, 'Validated result containing errors')
bad = deepcopy(result); bad['provenance'] = []
must_reject(result_validator, bad, 'Validated result without provenance')

hours = [3, 10]
estimates = []
for h in hours:
    lines = {
        'VPN gateway': 20.0647 * h,
        'DNS resolver inbound endpoint': 17198.325 / 720 * h,
        'Five private endpoints': .9555 * 5 * h,
        'One standard public IPv4': .4777 * h,
        'Five private DNS zones allowance for two billing days': 47.7731 * 5 * 2 / 30,
        'Layout allowance including training preprocessing': 955.4625 * 240 / 1000,
        'Classification allowance': 286.6388 * 120 / 1000,
        'LLM usage allowance, not a quoted tariff': 150,
        'Cosmos one million RU allowance': 23.8866,
        'Blob, vault, DNS queries, transfer and logging allowance': 30
    }
    subtotal = sum(lines.values())
    estimates.append({'cloudHours': h, 'lineItemsINR': {k: round(v, 2) for k, v in lines.items()},
                      'subtotalINR': round(subtotal, 2), 'contingencyPercent': 20,
                      'illustrativeTaxPercent': 18,
                      'planningTotalINR': round(subtotal * 1.2 * 1.18, 2)})
(out / 'cost-estimate.json').write_text(json.dumps({
    'currency': 'INR', 'rateDate': '2026-09-10', 'region': 'eastus2',
    'source': 'https://prices.azure.com/api/retail/prices',
    'note': 'Estimate, not a spending guarantee. DNS resolver uses a 720-hour September month; zones reserve two daily billing units. LLM and miscellaneous entries are allowances, not verified unit tariffs. Tax is illustrative only. No assumed free credits. Usage allowances include retries. No paid neural extraction training is planned.',
    'scenarios': estimates
}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'schemaFixturesAccepted': checked, 'negativeChecksRejected': rejections, 'estimatedTotals': estimates}, indent=2))
