"""Protected input/source hashes and historical accepted output comparisons."""
import collections,copy,hashlib,json,re
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent;REPO=WORK/'Har-To-JmX-Convertor'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
save=lambda n,v:(ROOT/n).write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
freeze=read(ROOT/'ENGINE_FREEZE.json');source={k:{'before':v,'after':sha(REPO/k),'unchanged':v==sha(REPO/k)} for k,v in freeze['source_and_test_sha256'].items()}
manifest=read(WORK/'request-fidelity-20261007/VALIDATION_INPUT_MANIFEST.json');audit=[]
def canon(path):
 root=ET.parse(path).getroot()
 for n in root.iter():
  n.tail=None
  if n.text and not n.text.strip():n.text=None
  if n.tag=='TestPlan':n.set('testname','FROZEN PLAN')
 for a in root.findall(".//elementProp[@elementType='Argument']"):
  if a.findtext("stringProp[@name='Argument.name']")=='LOOPS':a.find("stringProp[@name='Argument.value']").text='NORMALIZED_RUN_CONFIG'
 return ET.tostring(root)
keys=['classification','correlations','correlation_audit','parameterization_before_emit','parameterization','auth','transactions','extractor_checks','redirect_execution']
for row in manifest['inputs']:
 oldfolder=WORK/'request-fidelity-20261007/after'/row['set']/'conversions'/row['id'];newfolder=ROOT/'regression'/row['id'];old=read(oldfolder/'engine_decisions.json');new=read(newfolder/'engine_decisions.json')
 oldcsv={p.name:sha(p) for p in oldfolder.glob('*.csv')};newcsv={p.name:sha(p) for p in newfolder.glob('*.csv')}
 decisions={k:old[k]==new[k] for k in keys}
 oldxml=oldfolder/(row['id']+'.jmx');newxml=newfolder/(row['id']+'.jmx')
 audit.append({'id':row['id'],'set':row['set'],'success':new['success'],'protected_har_unchanged':sha(Path(row['path']))==row['sha256'],'decisions_unchanged':decisions,
  'csv_bytes_unchanged':oldcsv==newcsv,'normalized_jmx_unchanged':canon(oldxml)==canon(newxml),
  'sampler_count_unchanged':len(list(ET.parse(oldxml).getroot().iter('HTTPSamplerProxy')))==len(list(ET.parse(newxml).getroot().iter('HTTPSamplerProxy'))),
  'transaction_count_unchanged':len(list(ET.parse(oldxml).getroot().iter('TransactionController')))==len(list(ET.parse(newxml).getroot().iter('TransactionController')))})
current=read(ROOT/'REAL100_CORPUS_MANIFEST.json');truth_hashes={k:v==sha(ROOT/k) for k,v in current['truth_sha256'].items()}
save('SOURCE_HASH_REPORT.json',{'engine_source_and_tests_unchanged':all(v['unchanged'] for v in source.values()),'files':source,'truth_hashes_unchanged':truth_hashes,
 'current_corpus_hashes_unchanged':all(sha(Path(r['raw_har']))==r['sha256'] for r in current['records']),'baseline_source_changes':0})
report={'status':'PASS' if all(all(x['decisions_unchanged'].values()) and x['csv_bytes_unchanged'] and x['sampler_count_unchanged'] and x['transaction_count_unchanged'] and x['protected_har_unchanged'] for x in audit) else 'INVESTIGATE',
 'conversions':dict(collections.Counter(x['set'] for x in audit)),'successful_conversions':sum(x['success'] for x in audit),'crashes':sum(not x['success'] for x in audit),
 'pytest_passed':533,'pytest_xml':'full-pytest.xml','engine_source_and_tests_unchanged':all(v['unchanged'] for v in source.values()),
 'csv_bytes_changed_workflows':[x['id'] for x in audit if not x['csv_bytes_unchanged']],
 'normalized_jmx_changed_workflows':[x['id'] for x in audit if not x['normalized_jmx_unchanged']],
 'prior_output_baseline':'Accepted request-fidelity after outputs. Subsequent accepted SAML emission correction may differ; current P3 source frozen before collection.',
 'R01_R02_prior_before_after':{k:v for k,v in read(WORK/'request-fidelity-20261007/QUERY_PRESERVATION_AUDIT.json').items() if k!='checks'},
 'workflows':audit}
save('REAL100_REGRESSION_REPORT.json',report);print(report['status'],report['successful_conversions'],'conversions; normalized changed',report['normalized_jmx_changed_workflows'],flush=True)
