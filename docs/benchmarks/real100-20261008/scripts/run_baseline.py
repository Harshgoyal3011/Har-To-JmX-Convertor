"""Frozen engine observations. Source-only truth files are never rewritten here."""
import hashlib,json,sys,time,traceback
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent;REPO=WORK/'Har-To-JmX-Convertor'
sys.path.insert(0,str(REPO/'src'))
from har2jmx.engine import analyze
from har2jmx.emit import emit_jmx,validate_plan
from har2jmx.emit.redirects import redirect_execution
from har2jmx.emit.jmx import _replayable_header
from har2jmx.webreport import _correlation_implementation

def serial(v):
 if isinstance(v,dict):return {str(k):serial(x) for k,x in v.items()}
 if isinstance(v,(set,frozenset)):return sorted((serial(x) for x in v),key=lambda x:json.dumps(x,sort_keys=True))
 if isinstance(v,(list,tuple)):return [serial(x) for x in v]
 if hasattr(v,'value'):return v.value
 return v
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
def verify():
 freeze=read(ROOT/'ENGINE_FREEZE.json')
 assert all(hashlib.sha256((REPO/k).read_bytes()).hexdigest()==v for k,v in freeze['source_and_test_sha256'].items()),'Engine changed'
 manifest=read(ROOT/'REAL100_CORPUS_MANIFEST.json');assert manifest['status']=='FROZEN' and len(manifest['records'])==100
 assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in manifest['truth_sha256'].items()),'Truth changed'
 return manifest
manifest=verify();phase=sys.argv[1] if len(sys.argv)>1 else 'baseline';rows=manifest['records']
if phase=='regression':
 rows=[{'benchmark_id':r['id'],'raw_har':r['path'],'sha256':r['sha256'],'set':r['set']} for r in read(WORK/'request-fidelity-20261007/VALIDATION_INPUT_MANIFEST.json')['inputs']]
summary=[]
for n,row in enumerate(rows):
 bid=row['benchmark_id'];folder=ROOT/phase/bid;start=time.monotonic()
 try:
  raw=Path(row['raw_har']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['sha256']
  result=analyze(raw);before=serial(asdict(result.parameterization));redirects=redirect_execution(result,_replayable_header)
  path,csvs,reviews=emit_jmx(result,folder,{'threads':'1','loops':'2','ramp':'0','thinktime':'0'},name=bid)
  data={'benchmark_id':bid,'set':row.get('set'),'success':True,'jmx':str(path),'csv_files':[str(p) for p in csvs],
   'engine_metrics':result.metrics,'parameterization_before_emit':before,'parameterization':serial(asdict(result.parameterization)),
   'correlations':serial([asdict(c) for c in result.correlations]),'correlation_audit':serial(asdict(result.correlation_audit)),
   'classification':serial(asdict(result.classification)),'auth':serial(asdict(result.auth)),'transactions':serial([asdict(t) for t in result.transactions]),
   'extractor_checks':serial([asdict(c) for c in result.extractor_checks]),'redirect_execution':serial(asdict(redirects)),
   'requests':[{'index':r.index,'role':r.classification.role.value,'excluded':r.classification.excluded,'method':r.method,'path':r.path,'body_kind':r.request.body.kind.value} for r in result.capture.requests],
   'ir_requests':serial([asdict(r.request) for r in result.capture.requests]),'engine_validate_issues':validate_plan(result,path.read_bytes()),
   'materialization':_correlation_implementation(result,path.read_bytes()),'engine_output_is_ground_truth':False}
 except Exception as exc:data={'benchmark_id':bid,'set':row.get('set'),'success':False,'error':str(exc),'traceback':traceback.format_exc()}
 save(folder/'engine_decisions.json',data);summary.append({'id':bid,'set':row.get('set'),'success':data['success'],'seconds':round(time.monotonic()-start,3)})
 if (n+1)%10==0 or not data['success'] or n+1==len(rows):print(phase,n+1,'/',len(rows),'PASS' if data['success'] else data['error'],flush=True)
save(ROOT/(phase.upper()+'_CONVERSION_RESULTS.json'),summary);verify()
