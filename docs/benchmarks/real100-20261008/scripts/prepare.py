"""Freeze current engine and inspect historical exclusion evidence without importing it."""
import hashlib,importlib.util,json,re,shutil,subprocess
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent;REPO=WORK/'Har-To-JmX-Convertor'
def sha(data):return hashlib.sha256(data).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(n,v):(ROOT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
spec=importlib.util.spec_from_file_location('historical_fingerprints',WORK/'unseen-business-benchmark-20261004/audit_previous.py')
fingerprint=importlib.util.module_from_spec(spec);spec.loader.exec_module(fingerprint)
manifest=read(WORK/'request-fidelity-20261007/VALIDATION_INPUT_MANIFEST.json')
prior=read(WORK/'unseen-business-benchmark-20261004/PREVIOUS_CORPUS_EXCLUSION_MANIFEST.json')
aliases=read(WORK/'unseen-business-benchmark-20261004/PREVIOUS_APPLICATION_ALIASES.json')
new52=read(WORK/'unseen-business-benchmark-20261004/NEW_CORPUS_MANIFEST.json')
prior76=read(WORK/'real-world-benchmark/CAPTURE_MANIFEST.json')
manifests=[]
for path in WORK.rglob('*MANIFEST*.json'):
 if any(p in path.parts for p in ['node_modules','conversions','parent-engine','real100-benchmark-20261008']):continue
 try:
  raw=path.read_bytes();data=json.loads(raw)
  manifests.append({'path':str(path),'sha256':sha(raw),'bytes':len(raw),'root_kind':type(data).__name__})
 except (PermissionError,ValueError):continue
protected=[]
for row in manifest['inputs']:
 path=Path(row['path']);raw=path.read_bytes();assert sha(raw)==row['sha256']
 har=json.loads(raw);endpoints=[fingerprint.endpoint(e) for e in har['log']['entries']]
 business=[e for e in endpoints if fingerprint.is_business(e)]
 signature=[{k:v for k,v in e.items() if k not in {'url_sha256','host','domain','response_content_type'}} for e in business]
 protected.append({**row,'request_count':len(endpoints),'hosts':sorted({e['host'] for e in endpoints}),
   'business_hosts':sorted({e['host'] for e in business}),
   'sequence_sha256':sha(json.dumps(signature,sort_keys=True).encode()),'business_sequence':signature})
apps=set(prior['applications'])|set(new52['summary']['applications'])|{r['application'] for r in prior76}
apps.update(a['application'] for a in aliases['aliases'])
hosts=set(prior['excluded_business_hosts']);domains=set(prior['excluded_source_domains'])
for row in protected:hosts.update(row['business_hosts'])
for a in aliases['aliases']:hosts.update(a.get('hosts',[]));apps.update(a.get('aliases',[]))
domains.update(fingerprint.domain(h) for h in hosts)
save('HARD_EXCLUSION_SET.json',{'created_utc':datetime.now(timezone.utc).isoformat(),
 'policy':'Exclude historical applications/families/aliases, exact HAR hashes, same objective and near-identical business endpoint sequences; all previous failed attempts excluded conservatively.',
 'protected_counts':dict(Counter(r['set'] for r in protected)),'protected_inputs':protected,
 'all_historical_hashes':sorted({r['sha256'] for r in prior['har_inventory']}|{r['sha256'] for r in protected}),
 'excluded_applications':sorted(apps),'excluded_business_hosts':sorted(hosts),'excluded_domains':sorted(domains),
 'historical_inventory_count':len(prior['har_inventory']),'prior_manifests_inspected':manifests,
 'historical_workflow_records':[{'application':r.get('application'),'workflow':r.get('flow'),'id':r.get('workflow_id'),'status':r.get('status')} for r in prior76]
   +[{'application':r['application'],'workflow':r['workflow_name'],'id':r['benchmark_id']} for r in new52['records']],
 'prior_additional_capture':{'path':str(WORK.parent/'STD_flow_HAR_7Oct.har'),'sha256':sha((WORK.parent/'STD_flow_HAR_7Oct.har').read_bytes()),'application':'Wolters Kluwer / PingFederate SSO','excluded':True}})
source={}
for base in ['src','tests']:
 for path in (REPO/base).rglob('*'):
  if not path.is_file() or '__pycache__' in path.parts:continue
  rel=path.relative_to(REPO);source[rel.as_posix()]=sha(path.read_bytes())
  if base=='src':
   target=ROOT/'frozen-engine'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
git=['git','-c',f'safe.directory={REPO.as_posix()}']
save('ENGINE_FREEZE.json',{'frozen_utc':datetime.now(timezone.utc).isoformat(),'git_head':subprocess.check_output(git+['rev-parse','HEAD'],cwd=REPO,text=True).strip(),
 'git_status':subprocess.check_output(git+['status','--porcelain'],cwd=REPO,text=True),
 'source_and_test_sha256':source,'baseline':'Current working-tree engine after completed URL/query repair and subsequent accepted SAML/username fixes; no rollback.',
 'converter_has_not_been_run_for_real100':True})
save('REAL100_CORPUS_MANIFEST.json',{'status':'COLLECTION_PENDING','target':100,'accepted_count':0,'records':[],
 'engine_freeze':'ENGINE_FREEZE.json','hard_exclusions':'HARD_EXCLUSION_SET.json','ground_truth_policy':'Original HAR and action evidence only; ambiguity REVIEW/UNASSESSED; no converter-defined truth.'})
print('Prepared',len(protected),'protected inputs;',len(manifests),'historical manifests;',len(apps),'excluded names;',len(source),'frozen source/test files')
