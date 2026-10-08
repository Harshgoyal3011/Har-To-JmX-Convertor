"""Publish evidence and limitations, never convert unknowns into success claims."""
import base64,collections,csv,hashlib,json,re
from pathlib import Path
from urllib.parse import parse_qsl,urlsplit,unquote
ROOT=Path(__file__).resolve().parent
read=lambda n:json.loads((ROOT/n).read_text(encoding='utf-8'))
save=lambda n,v:(ROOT/n).write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
m=read('REAL100_CORPUS_MANIFEST.json');p=read('REAL100_PARAMETERIZATION_SCORECARD.json');c=read('REAL100_CORRELATION_SCORECARD.json');f=read('REAL100_REQUEST_FIDELITY.json');j=read('REAL100_JSON_REPRESENTATION.json');a=read('REAL100_FINAL_JMX_AUDIT.json');reg=read('REAL100_REGRESSION_REPORT.json');smoke=read('WIRE_SMOKE_EXECUTION.json');root=read('REAL100_ROOT_CAUSE_ANALYSIS.json')
raw_requests=read('WIRE_RAW_REQUESTS.json')
f['wire_query_semantic_differences']=sum(not x['query_semantics_equal'] for x in f['wire_checks'])
f['wire_encoding_only_query_differences']=sum(not x['query_exact'] and x['query_semantics_equal'] for x in f['wire_checks'])
f['wire_semantic_query_difference_review']='Twenty receiver observations follow retained third-party LinkedIn automatic redirects and add liSync=true. These are redirect-chain/source-mapping differences, not query/body crossing evidence.'
f['R01']='NO FAILURE OBSERVED: zero lost-query candidates in 737 final samplers'
f['R02']='NO FAILURE OBSERVED: zero query-to-form-body crossings in 737 final samplers; representative native form bodies verified on wire'
save('REAL100_REQUEST_FIDELITY.json',f)
j['invalid_jsonpath_syntax']=sum(x['extractor']=='json' and not x['expression_check'].get('success',False) for x in read('REAL100_MATERIALIZATION_AUDIT.json')['checks'])
j['wrong_jsonpath_selected_values']=sum(x['extractor']=='json' and x['expression_check'].get('success',False) and not x['source_expression_resolves'] for x in read('REAL100_MATERIALIZATION_AUDIT.json')['checks'])
save('REAL100_JSON_REPRESENTATION.json',j)
smoke['sample_count']=sum(x.get('samples',0) for x in smoke['results']);smoke['failed_samples_including_transaction_parents']=sum(x.get('failed_samples',0) for x in smoke['results'])
smoke['failure_interpretation']={'Nautobot':'Captured third-party automatic redirect chain cannot be faithfully identified by the loopback mapping; not proof of new converter auth/redirect failure.',
 'Vikunja':'Captured WebSocket upgrade is not supported by the deterministic HTTP receiver; local timeout is not a converter correlation defect.',
 'Sylius':'Captured intermediate component request already returned HTTP 422; final customer save succeeded. Status assertion on intermediate capture is not business replay proof.',
 'Booked group':'Local response/parser IllegalArgumentException needs inspection; not assigned to converter without isolation.'}
save('WIRE_SMOKE_EXECUTION.json',smoke)
# Natural occurrence inspection, independent source paths/types. Equal literal
# candidates are evidence buckets, never asserted runtime producer identities.
def scalar(v,path='$'):
 if isinstance(v,dict):
  for k,x in v.items():yield from scalar(x,path+'['+json.dumps(k)+']')
 elif isinstance(v,list):
  for n,x in enumerate(v):yield from scalar(x,path+f'[{n}]')
 elif v is not None:yield path,v,type(v).__name__
buckets=collections.defaultdict(list)
for row in m['records']:
 h=json.loads(Path(row['raw_har']).read_text(encoding='utf-8'))['log']['entries']
 for i,e in enumerate(h):
  for side in ['request','response']:
   part=e[side];post=part.get('postData',{}) if side=='request' else part.get('content',{});text=post.get('text','');mime=post.get('mimeType','')
   if 'json' not in mime or not text:continue
   if post.get('encoding')=='base64':text=base64.b64decode(text).decode('utf-8',errors='replace')
   try:data=json.loads(text)
   except ValueError:continue
   for path,value,kind in scalar(data):
    normalized=str(value).strip()
    if normalized in {'','0','1','True','False'}:continue
    buckets[normalized].append({'benchmark_id':row['benchmark_id'],'request_index':i,'side':side,'host':urlsplit(e['request']['url']).hostname,'location':path,'original_type':kind,'value':value})
selected=[]
for value,occ in buckets.items():
 if len(occ)<2:continue
 dims={'hosts':len({o['host'] for o in occ}),'requests':len({(o['benchmark_id'],o['request_index']) for o in occ}),
  'locations':len({o['location'] for o in occ}),'types':len({o['original_type'] for o in occ}),'array_positions':len({o['location'] for o in occ if re.search(r'\[\d+\]',o['location'])})}
 selected.append({'compatibility_literal':value,'occurrence_count':len(occ),'dimensions':dims,'examples':occ[:6],'assessment':'CANDIDATE_ONLY: no logical identity inferred'})
selected.sort(key=lambda x:-x['occurrence_count'])
save('NATURAL_OCCURRENCE_COLLISION_AUDIT.json',{'equal_literal_buckets':len(selected),'cross_host_buckets':sum(x['dimensions']['hosts']>1 for x in selected),
 'cross_request_buckets':sum(x['dimensions']['requests']>1 for x in selected),'different_type_buckets':sum(x['dimensions']['types']>1 for x in selected),
 'array_position_buckets':sum(x['dimensions']['array_positions']>1 for x in selected),'inventory':selected[:250],
 'not_exhaustively_proven':['Repeated retry logical ownership','Same runtime logical value across header/body','Encoded/decoded false identity merges','Unrelated entities with specifically equal created IDs'],
 'scope':'Source occurrence inventory only. No synthetic HAR, forced producer links, or source repair.'})
readiness=list(csv.DictReader((ROOT/'REAL100_REPLAY_READINESS.csv').open(encoding='utf-8')));counts=collections.Counter(x['readiness'] for x in readiness)
top=root['root_causes'][:5]
score={'convert_success':100,'meaningful_inputs_confirmed':p['meaningful_logical_input_groups'],'parameter_recall_confirmed':p['parameter_recall'],
 'parameter_precision':None,'parameter_precision_lower_bound':p['parameter_precision_confirmed_action_lower_bound'],'unnecessary_csv_columns':None,
 'confirmed_retained_runtime_dependencies':c['confirmed_runtime_dependencies_in_retained_workload'],'correlation_recall_confirmed':c['correlation_recall'],
 'correlation_precision_assessed_only':c['correlation_precision'],'materialization_capture_resolution':c['materialization_rate_capture_resolution'],
 'false_correlations_confirmed':c['false_correlations_confirmed'],'dead_extractors':c['dead_extractors'],'undefined_variables':c['undefined_variables'],
 'query_body_crossings':f['R02_query_in_body_candidates'],'lost_queries':f['R01_lost_query_candidates'],'json_type_failures':j['type_failures'],
 'invalid_jsonpath_syntax':j['invalid_jsonpath_syntax'],'wrong_jsonpath_selected_values':j['wrong_jsonpath_selected_values'],
 'replay_ready_proven':0,'manual_repair_workflows':counts['MANUAL_REPAIR_REQUIRED'],'ready_with_review':counts['READY_WITH_REVIEW'],'capture_limited':counts['CAPTURE_LIMITED'],
 'top_five_root_causes':[{'cause':x['root_cause'],'workflows':x['affected_workflows']} for x in top],
 'new_defects':'No independently isolated new source root cause proven; manifestations of known defects observed.',
 'next_fix_recommendation':'Occurrence-scoped semantic ownership and approved exact producer/consumer binding, while keeping discovery/lifecycle policy thresholds frozen. Complete P2-4B evidence scope, then isolate downstream binding; do not repair by increasing correlations.',
 'benchmark_completion':'100-capture execution complete; exhaustive ground truth, full parameter precision, fresh runtime materialization and live replay readiness remain unassessed. Do not call the entire requested benchmark fully validated.'}
save('REAL100_EXECUTIVE_SCORECARD.json',score)
percent=lambda v:f'{100*v:.2f}%' if v is not None else 'UNASSESSED'
table=[('Conversions', '100/100'),('Applications','55'),('Confirmed meaningful input groups',str(p['meaningful_logical_input_groups'])),
 ('Correctly parameterized / confirmed recall',f'{p["correctly_parameterized_groups"]}/{p["meaningful_logical_input_groups"]} — {percent(p["parameter_recall"])}'),
 ('Parameter precision','UNASSESSED; '+percent(p['parameter_precision_confirmed_action_lower_bound'])+' confirmed-action lower bound'),
 ('CSV columns / necessary confirmed',f'{p["csv_columns_generated"]} / {p["necessary_csv_columns"]}'),
 ('Unnecessary CSV columns','UNASSESSED; 103 unsupported by recorded explicit actions need review'),
 ('Confirmed runtime edges in retained workload',str(c['confirmed_runtime_dependencies_in_retained_workload'])),
 ('Correct runtime edges / confirmed recall',f'{c["correctly_correlated_edges"]}/{c["confirmed_runtime_dependencies_in_retained_workload"]} — {percent(c["correlation_recall"])}'),
 ('Assessed correlation precision',percent(c['correlation_precision'])+'; 100 confirmed / 104 assessed, 145 accepted unassessed'),
 ('Capture-resolution materialization',percent(c['materialization_rate_capture_resolution'])+'; fresh runtime rate UNASSESSED'),
 ('Confirmed false correlations',str(c['false_correlations_confirmed'])),('Dead extractors / undefined variables',f'{c["dead_extractors"]} / {c["undefined_variables"]}'),
 ('R01 lost queries / R02 query-body crossings','0 / 0 observed in 737 final samplers'),('JSON type failures',str(j['type_failures'])),
 ('JSONPath syntax / wrong selected value',f'{j["invalid_jsonpath_syntax"]} / {j["wrong_jsonpath_selected_values"]}'),
 ('Replay-ready proven / manual repair',f'0 / {counts["MANUAL_REPAIR_REQUIRED"]}'),('Ready with review / capture limited',f'{counts["READY_WITH_REVIEW"]} / {counts["CAPTURE_LIMITED"]}'),
 ('Protected regressions / tests','202/202 conversions; 533 tests passed')]
text='''# REAL100 independent baseline report

The unchanged engine converted all 100 newly recorded HARs and JMeter loaded every plan. Correctness and replay readiness remain materially below conversion success. This report contains measured assessed subsets; it does not claim complete independent ground truth or 100 replay-ready workflows.

The frozen corpus contains 31 native browser business workflows and 69 documented public API journeys across 55 applications. Historical application aliases, business origins, HAR hashes and business request sequences were excluded before admission. Raw HARs and UI/API action records are preserved. Four completed Vikunja operations have missing outbound bodies in the browser HAR and are capture-limited. Most API journeys are read/catalog flows. SOAP, GraphQL request bodies, file uploads and exhaustive retry/transformation scenarios were not exercised.

## Executive scorecard

| Measure | Result |
| --- | --- |
'''
text+=''.join(f'| {k} | {v} |\n' for k,v in table)
text+='''
## What the evidence proves

Source-only labels were frozen before the first converter run. Exact producer/consumer locations and original types remain in the truth CSVs. Equality only locates evidence candidates; ambiguous repeated issuers remain REVIEW. There are 241 confirmed input groups, 11 input occurrence rows requiring review and four capture-limited input rows. The source audit identifies 2,466 confirmed runtime edge observations; 618 consumers are retained in the generated workload. Excluded resource consumers are reported separately. Session/cookie edges are included; these totals must not be mistaken for created-business-object dependencies alone.

Parameter recall is for confirmed recorded input groups. A full precision figure is unavailable because default controls, implicit selections and all generated columns were not independently adjudicated. The 103 columns unsupported by explicit recorded actions cannot all be declared unnecessary. Correlation precision applies only to 104 evidenced accepted decisions. The other 145 remain unassessed. Four confirmed false correlations treat an existing Moodle recent-items catalog's module/name values as runtime state.

Final XML checks cover 737 samplers, CSV structure, references, extractor placement, URLs, bodies, headers, cookie declarations and redirect plans. JMeter's own SaveService loaded all 100 plans. Its JSONPath evaluator checked generated expressions against original responses. A JSONPath containing an unquoted space is invalid; three broad paths select a first array value different from the intended captured value. Eight numeric JSON scalars become strings across four workflows. These are known representation/identity/extraction issues, not repaired by this benchmark.

## Wire and replay evidence

Twenty generated workflows ran through a deterministic local receiver with one user and two iterations, preserving actual CSV files and generated processors. Destination and cookie scope were adapted for loopback. The receiver served captured responses; it did not issue fresh business IDs or establish independent live sessions. This is a smoke validation, not a load test or a live business replay.

The receiver observed 620 HTTP requests. JMeter recorded 738 samples including transaction parents, with 18 failures. Captured WebSocket upgrades, third-party redirect mapping, existing intermediate HTTP 422 responses and a local parser error account for smoke failures that require review; they are not automatically converter defects. Six query differences are encoding-only. Twenty further observations follow third-party redirect targets that add liSync=true, so exact HAR source mapping is limited. Ten body differences include numeric representation changes. R01/R02 ownership checks show zero query loss or query-to-form-body crossing; this does not erase those separate representation/redirect findings.

No workflow is marked REPLAY_READY from XML loading, captured-response replay or status assertions alone. Forty require review, 56 require manual repair from assessed defects, and four are capture-limited. Fresh-state and permitted live two-iteration replay remain unassessed.

## Systemic causes

'''
for x in top:text+=f'- **{x["root_cause"]}**: {x["affected_workflows"]} workflows; {x["finding_count"]} findings. Source: `{x["source_location"]}`.\n'
text+='''
The categories can overlap. Counts are observed affected workflows, not estimates of every latent failure. No new source root cause has been independently isolated; observed failures manifest already known parameter discovery, materialization, lifecycle/identity, numeric typing and JSONPath weaknesses.

The next engineering repair should establish occurrence-scoped semantic ownership and exact approved producer/consumer binding. It addresses a high-impact prerequisite for runtime correctness and independent input ownership. Parameter discovery has the largest observed workflow count, but increasing parameter or correlation counts would not resolve wrong ownership. Preserve the existing policies and validate each exact final consumer after the scoped repair.

## Regression protection

The protected 52 + 76 + 74 inputs were not modified. All 202 converted, decisions and CSV bytes matched accepted historical outputs, and sampler/transaction counts stayed unchanged. After normalizing timestamps and this benchmark's loop count, EX-073 alone differs in final JMX because the current engine already contains the accepted SAML consumer correction. The recorded R01 before/after audit is linked in the regression JSON. All 533 repository tests passed. Engine source and test hashes match the pre-collection freeze.

## Remaining work and limits

Exhaustive input/non-runtime ground truth, necessary-versus-unnecessary CSV adjudication, fresh runtime materialization, all identity collision scenarios and permitted live smoke replay are incomplete. Overall parameter precision, fresh runtime materialization rate and proven live replay readiness are therefore unassessed. Do not interpret zeros for undefined variables or R01/R02 ownership failures as evidence that lifecycle, identity, JSON numeric typing, JSONPath, extraction health or business replay defects are solved.

The requested fifteen deliverables and raw evidence are in this directory. Supplemental files include source hashes, the executive scorecard, natural occurrence inventory, JMeter expression results, wire observations, smoke logs and full pytest XML. No converter source changes were made.
'''
(ROOT/'REAL100_EXECUTIVE_REPORT.md').write_text(text,encoding='utf-8')
print('Executive report generated; incomplete measurements explicitly unassessed.',flush=True)
