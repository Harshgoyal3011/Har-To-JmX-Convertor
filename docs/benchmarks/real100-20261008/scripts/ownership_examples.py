"""Concrete source provenance versus final variables; supplemental scoped review."""
import hashlib,json
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parent
read=lambda n:json.loads((ROOT/n).read_text(encoding='utf-8'))
save=lambda n,v:(ROOT/n).write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
m=read('REAL100_CORPUS_MANIFEST.json');examples=[]
for bid,ci,explanation in [
 ('REAL100-001',538,'Create-course POST responds Location /course/view.php?id=5. Final course consumer uses newsitems CSV because that separate configuration input also equals 5.'),
 ('REAL100-004',26,'Create-experiment POST responds Location /api/v2/experiments/28. Native edit consumer uses CSV id, so new experiment issuance is frozen as test data.'),
 ('REAL100-005',105,'Patient save response explicitly assigns window.location with set_pid=22. Demographics consumer uses CSV set_pid rather than its created-patient producer.'),
 ('REAL100-007',123,'Customer save JSON data.id=9. Native customer stats URL uses CSV customers, retaining captured ID rather than new customer issuance.'),
 ('REAL100-023',171,'Chore save JSON created_object_id=7. Native calculate-next-assignments body uses CSV chore_id instead of the server-created value.')]:
 row=next(r for r in m['records'] if r['benchmark_id']==bid);har=json.loads(Path(row['raw_har']).read_text(encoding='utf-8'))['log']['entries'];pi=row['completion_evidence']['source_request_index']
 d=read(f'baseline/{bid}/engine_decisions.json');indices=[i for t in d['transactions'] for i in t['request_indices'] if not d['requests'][i]['excluded'] and i not in d['redirect_execution'].get('automatic_targets',[])];samples=list(ET.parse(d['jmx']).getroot().iter('HTTPSamplerProxy'));s=samples[indices.index(ci)]
 examples.append({'benchmark_id':bid,'producer_request_index':pi,'producer_url':har[pi]['request']['url'],
  'producer_response_location_header':[h['value'] for h in har[pi]['response']['headers'] if h['name'].lower()=='location'],
  'producer_response_body_excerpt':har[pi]['response']['content'].get('text','')[:1000],
  'consumer_request_index':ci,'consumer_url':har[ci]['request']['url'],'final_path':s.findtext("stringProp[@name='HTTPSampler.path']"),
  'final_body_arguments':[a.findtext("stringProp[@name='Argument.value']") for a in s.findall(".//elementProp[@elementType='HTTPArgument']")],
  'classification':'SERVER_RUNTIME_VALUE_BOUND_TO_CSV','explanation':explanation,'known_defect':True,
  'scorecard_policy':'Supplemental exact source review; does not rewrite frozen primary truth or its denominator.'})
save('CREATED_RUNTIME_CSV_OWNERSHIP_EXAMPLES.json',{'workflows':5,'examples':examples})
root=read('REAL100_ROOT_CAUSE_ANALYSIS.json');root['root_causes'].append({'root_cause':'occurrence ownership / runtime state bound to CSV','affected_workflows':5,
 'workflows':[e['benchmark_id'] for e in examples],'finding_count':5,'examples':examples,
 'source_location':'src/har2jmx/classify/value_engine.py; src/har2jmx/lineage/graph.py; src/har2jmx/parameterize/intent.py; src/har2jmx/emit/bindings.py',
 'already_known':True,'new':False,'blast_radius':'Created IDs equal to input/catalog values or read-back values can be assigned an unrelated CSV owner. Captured-value replay masks the error.'})
save('REAL100_ROOT_CAUSE_ANALYSIS.json',root)
path=ROOT/'REAL100_FAILURE_INVENTORY.csv'
import csv
with path.open('a',encoding='utf-8',newline='') as f:
 w=csv.writer(f)
 for e in examples:w.writerow([e['benchmark_id'],'occurrence ownership / runtime state bound to CSV',e['consumer_request_index'],e['explanation'],True,True])
report=ROOT/'REAL100_EXECUTIVE_REPORT.md';text=report.read_text(encoding='utf-8')
text += '''
## Concrete created-ID ownership failures

A supplemental exact source review confirms five workflows where server-created IDs receive CSV owners. This review preserves the frozen primary truth totals and is not folded into recall denominators. See `CREATED_RUNTIME_CSV_OWNERSHIP_EXAMPLES.json` for source responses and final expressions.

- Moodle: created course `id=5` is emitted as `${newsitems}`. The captured course ID and a separate news-items setting happen to be equal.
- eLabFTW: newly issued experiment ID is emitted as CSV `${id}`.
- OpenEMR: a save-response JavaScript redirect issues the patient ID, but the demographics consumer uses CSV `${set_pid}`.
- InvoiceShelf: newly created customer `data.id` is emitted as CSV `${customers}` in its stats request.
- Grocy: newly created chore ID is emitted as CSV `${chore_id}` in the next-assignment request.

These failures demonstrate why correct captured values and successful local response replay do not prove fresh runtime ownership. They reinforce occurrence-scoped semantic ownership and approved producer/consumer binding as the next repair.
'''
report.write_text(text,encoding='utf-8')
hashes=read('DELIVERABLE_HASH_REPORT.json')
for n in hashes['deliverables']:hashes['deliverables'][n]=hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
save('DELIVERABLE_HASH_REPORT.json',hashes)
print('Five exact created-runtime CSV ownership examples recorded; truth/source unchanged.')
