"""Publish benchmark evidence without browser session/credential material."""
import base64,csv,hashlib,json,re,shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent;REPO=WORK/'Har-To-JmX-Convertor'
DEST=REPO/'docs/benchmarks/real100-20261008'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
manifest=read(ROOT/'REAL100_CORPUS_MANIFEST.json');sensitive=set()
key_sensitive=re.compile(r'[REDACTED:5e884898da28]|passwd|clearpass|csrf|xsrf|token|authorization|session|sesskey|logintoken|secret',re.I)
def remember(value):
 if isinstance(value,str) and value:sensitive.add(value)
def json_secrets(value):
 if isinstance(value,dict):
  for k,v in value.items():
   if key_sensitive.search(k):remember(v)
   json_secrets(v)
 elif isinstance(value,list):
  for v in value:json_secrets(v)
class HiddenTokens(HTMLParser):
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='input' and key_sensitive.search(a.get('name','')+' '+a.get('id','')):remember(a.get('value'))
for row in manifest['records']:
 entries=read(Path(row['raw_har']))['log']['entries'];capture=read(Path(row['capture_metadata']))
 for action in capture['actions']:
  ev=action.get('element_evidence',{})
  if ev.get('type')=='[REDACTED:5e884898da28]' or key_sensitive.search(ev.get('name','')+' '+ev.get('id','')):remember(ev.get('value'));remember(action.get('value'))
 for entry in entries:
  for side in ['request','response']:
   obj=entry[side]
   for cookie in obj.get('cookies',[]):remember(cookie.get('value'))
   for header in obj.get('headers',[]):
    name=header['name'].lower();value=header['value']
    if name in {'authorization','proxy-authorization'}:
     remember(value);remember(value.split(' ',1)[-1])
    elif name=='cookie':
     for pair in value.split(';'):
      if '=' in pair:remember(pair.split('=',1)[1].strip())
    elif name=='set-cookie':remember(value.split(';',1)[0].split('=',1)[-1])
    elif key_sensitive.search(name):remember(value)
   for key,value in parse_qsl(entry['request']['url'].partition('?')[2],keep_blank_values=True):
    if key_sensitive.search(key):remember(value)
   content=obj.get('postData',{}) if side=='request' else obj.get('content',{})
   text=content.get('text','');mime=content.get('mimeType','')
   if content.get('encoding')=='base64':
    try:text=base64.b64decode(text).decode('utf-8',errors='replace')
    except ValueError:continue
   if 'json' in mime:
    try:json_secrets(json.loads(text))
    except ValueError:pass
   if 'x-www-form-urlencoded' in mime:
    for key,value in parse_qsl(text,keep_blank_values=True):
     if key_sensitive.search(key):remember(value)
   if 'html' in mime:
    try:HiddenTokens().feed(text)
    except Exception:pass
# Preserve numerical IDs and short static values; only identifiable long session
# material is replaced inside prose. Exact scalar credentials are also removed.
long_values=sorted((v for v in sensitive if len(v)>=8),key=len,reverse=True)
substrings=re.compile('|'.join(re.escape(v) for v in long_values)) if long_values else None
def token(value):return '[REDACTED:'+hashlib.sha256(value.encode()).hexdigest()[:12]+']'
def redact(text):
 if text in sensitive:return token(text)
 if substrings:text=substrings.sub(lambda m:token(m[0]),text)
 return text.replace(str(WORK),'[WORKSPACE]').replace(WORK.as_posix(),'[WORKSPACE]')
def clean(value):
 if isinstance(value,dict):return {redact(str(k)):clean(v) for k,v in value.items()}
 if isinstance(value,list):return [clean(v) for v in value]
 if isinstance(value,str):return redact(value)
 return value
names=[
 'REAL100_CORPUS_MANIFEST.json','REAL100_DUPLICATE_AUDIT.json','REAL100_GROUND_TRUTH_INPUTS.csv','REAL100_GROUND_TRUTH_RUNTIME.csv',
 'REAL100_PARAMETERIZATION_SCORECARD.json','REAL100_CORRELATION_SCORECARD.json','REAL100_MATERIALIZATION_AUDIT.json',
 'REAL100_REQUEST_FIDELITY.json','REAL100_JSON_REPRESENTATION.json','REAL100_REPLAY_READINESS.csv','REAL100_FAILURE_INVENTORY.csv',
 'REAL100_ROOT_CAUSE_ANALYSIS.json','REAL100_FINAL_JMX_AUDIT.json','REAL100_REGRESSION_REPORT.json','REAL100_EXECUTIVE_REPORT.md',
 'REAL100_EXECUTIVE_SCORECARD.json','CREATED_RUNTIME_CSV_OWNERSHIP_EXAMPLES.json','NATURAL_OCCURRENCE_COLLISION_AUDIT.json',
 'SOURCE_HASH_REPORT.json','ENGINE_FREEZE.json','GROUND_TRUTH_LABEL_REVIEW.json','WIRE_SMOKE_EXECUTION.json','JMETER_INSPECTION_RESULTS.json',
 'BASELINE_CONVERSION_RESULTS.json','REGRESSION_CONVERSION_RESULTS.json','DELIVERABLE_HASH_REPORT.json','full-pytest.xml']
scripts=['prepare.py','admit.py','source_truth.py','run_baseline.py','capture_browser.py','capture_apis.py','inspect_demos.py','probe_apis.py',
 'wire_smoke.py','audit.py','regression_report.py','finish_report.py','ownership_examples.py','JMeterInspect.java','export_github.py']
DEST.mkdir(parents=True,exist_ok=True);hashes={};changed=[]
for name in names:
 source=ROOT/name;target=DEST/name
 if source.suffix=='.json':out=json.dumps(clean(read(source)),indent=2,ensure_ascii=False)+'\n'
 elif source.suffix=='.csv':
  with source.open(encoding='utf-8',newline='') as f:records=list(csv.reader(f))
  with target.open('w',encoding='utf-8',newline='') as f:csv.writer(f).writerows([[redact(v) for v in row] for row in records])
  out=None
 else:out=redact(source.read_text(encoding='utf-8'))
 if out is not None:target.write_text(out,encoding='utf-8')
 hashes[name]={'original_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'published_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
 if hashes[name]['original_sha256']!=hashes[name]['published_sha256']:changed.append(name)
scriptdir=DEST/'scripts';scriptdir.mkdir(exist_ok=True)
for name in scripts:
 if (ROOT/name).exists():(scriptdir/name).write_text(redact((ROOT/name).read_text(encoding='utf-8')),encoding='utf-8')
# Small action records support the source-only labeling without uploading raw HARs.
actionsdir=DEST/'capture-actions';actionsdir.mkdir(exist_ok=True)
for row in manifest['records']:
 cap=read(Path(row['capture_metadata']));cap={k:v for k,v in cap.items() if k not in {'inspection'}}
 (actionsdir/(row['benchmark_id']+'.json')).write_text(json.dumps(clean(cap),indent=2,ensure_ascii=False),encoding='utf-8')
publication={'published_report_count':len(names),'published_action_records':100,'redacted_session_or_credential_values':len(sensitive),
 'policy':'Captured credentials, CSRF/auth tokens and cookie/session values replaced with stable hash markers; raw HAR/browser HTML/screenshots/wire header dumps are local only.',
 'raw_har_local_only':{'count':100,'bytes':sum(Path(r['raw_har']).stat().st_size for r in manifest['records']),'sha256_manifest':'REAL100_CORPUS_MANIFEST.json'},
 'report_hashes':hashes,'redaction_or_format_changed_files':changed,
 'reproducibility':'Reports retain original evidence hashes and indexed locations. Redacted published files cannot replace original raw data for runtime replay. Scripts are archived in their original workspace-layout context; raw corpora/dependencies are not bundled.'}
(DEST/'PUBLICATION_AUDIT.json').write_text(json.dumps(publication,indent=2),encoding='utf-8')
(DEST/'README.md').write_text('''# REAL100 correlation and parameterization baseline

Read [the executive report](REAL100_EXECUTIVE_REPORT.md) for measured results and remaining assessment gaps. The unchanged engine converted 100 new HARs from 55 applications; protected regression converted 202 inputs and all 533 repository tests passed.

This directory contains the fifteen requested reports, supplemental scorecards, source/hash evidence, pytest XML, validation scripts and 100 recorded UI/API action records.

The reports describe the actual frozen local working tree, including accepted repairs that were uncommitted at collection time. `ENGINE_FREEZE.json` and `SOURCE_HASH_REPORT.json` identify it; the parent Git commit alone does not reproduce that working tree.

Captured credentials, session cookies and authentication/CSRF token values are redacted with stable hash markers. Raw HARs (340 MB), browser HTML/screenshots, generated request bundles and wire header dumps remain in the original local benchmark directory. Their original hashes and source locations remain in the reports. `PUBLICATION_AUDIT.json` maps original report hashes to published hashes. CSV files here are audit evidence, not live replay data.

The scripts are archived from the original workspace layout. Running them requires the original corpora, Python/browser/JMeter dependencies, explicit permitted application access and path adaptation. They are not a standalone public replay harness.

Overall parameter precision and fresh/live runtime readiness remain unassessed. This publication does not claim that all requested validation is complete or that the engine is replay-ready.
''',encoding='utf-8')
# Ensure long secret literals do not remain in any published file.
for path in DEST.rglob('*'):
 if path.is_file():
  text=path.read_text(encoding='utf-8')
  assert not substrings or not substrings.search(text),f'Session material retained in {path.name}'
print('Prepared',sum(p.is_file() for p in DEST.rglob('*')),'published files; raw HARs local; session material redacted.',flush=True)
