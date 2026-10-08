"""Independent source labels versus final JMX and recorded wire observations."""
import base64,collections,csv,hashlib,json,re
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.parse import parse_qsl,urlsplit,quote_plus,unquote,unquote_plus
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent;REPO=WORK/'Har-To-JmX-Convertor'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def save(n,v):(ROOT/n).write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
def rows(n):return list(csv.DictReader((ROOT/n).open(encoding='utf-8',newline='')))
def csvout(n,records,fields):
 with (ROOT/n).open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(records)
def prop(n,k):return n.findtext(f".//*[@name='{k}']") or ''
def scalars(v,path='request.body'):
 if isinstance(v,dict):
  for k,x in v.items():yield from scalars(x,path+'['+json.dumps(k)+']')
 elif isinstance(v,list):
  for i,x in enumerate(v):yield from scalars(x,path+f'[{i}]')
 elif v is not None:yield path,v,type(v).__name__
def fields(mime,body):
 if 'x-www-form-urlencoded' in mime:return parse_qsl(body,keep_blank_values=True)
 if 'multipart/' in mime:
  msg=BytesParser(policy=default).parsebytes(('Content-Type: '+mime+'\r\n\r\n').encode()+body.replace('\r\r\n','\r\n').encode())
  if msg.is_multipart():return [(p.get_param('name',header='content-disposition'),p.get_payload(decode=True).decode('utf-8',errors='replace')) for p in msg.iter_parts() if not p.get_filename()]
 return []
def refs(text):return set(re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',text or ''))
def resolve(text,values):
 text=text or ''
 for _ in range(8):
  old=text;text=re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}',lambda m:str(values.get(m[1],m[0])),text)
  text=re.sub(r'\$\{__urlencode\(([^{}]*)\)\}',lambda m:quote_plus(m[1]),text)
  if text==old:break
 return text
manifest=read(ROOT/'REAL100_CORPUS_MANIFEST.json');inputs=rows('REAL100_GROUND_TRUTH_INPUTS.csv');truth=rows('REAL100_GROUND_TRUTH_RUNTIME.csv')
java={r['id']:r for r in read(ROOT/'JMETER_INSPECTION_RESULTS.json')};wire=read(ROOT/'WIRE_RAW_REQUESTS.json')
findings=[];plans=[];parameters=[];column_audit=[];material=[];dependency_audit=[];fidelity=[];types=[];wire_checks=[];readiness=[];collision=[]
def finding(bid,category,reason,index=None,known=True,blocking=True):
 findings.append({'benchmark_id':bid,'category':category,'request_index':index,'reason':reason,'already_known':known,'blocking':blocking})
for workflow in manifest['records']:
 bid=workflow['benchmark_id'];d=read(ROOT/'baseline'/bid/'engine_decisions.json');har=read(Path(workflow['raw_har']))['log']['entries'];root=ET.parse(d['jmx']).getroot();parents={c:p for p in root.iter() for c in p}
 def adjacent(n):s=list(parents[n]);return s[s.index(n)+1]
 indices=[i for t in d['transactions'] for i in t['request_indices'] if not d['requests'][i]['excluded'] and i not in d['redirect_execution'].get('automatic_targets',[])]
 samplers=dict(zip(indices,root.iter('HTTPSamplerProxy')));values={};declared=[];runtime=[];request_used=set();csvdata={};columns={}
 for a in root.findall(".//elementProp[@elementType='Argument']"):
  values[prop(a,'Argument.name')]=prop(a,'Argument.value')
 for dataset in d['parameterization']['datasets']:
  for c in dataset['columns']:columns[c['name']]={'dataset':dataset['name'],**c}
 for ds in root.iter('CSVDataSet'):
  names=prop(ds,'variableNames').split(',');declared.extend(names);path=Path(prop(ds,'filename'))
  if not path.is_absolute():path=Path(d['jmx']).parent/path
  with path.open(encoding='utf-8-sig',newline='') as f:data=list(csv.reader(f))
  row=data[1] if len(data)>1 else []
  csvdata[path.name]={'headers':data[0] if data else [],'declared_names':names,'rows':len(data)-1,'widths':sorted({len(r) for r in data}),'header_matches':bool(data) and names==data[0]}
  for name,v in zip(names,row):values[name]=v
 for c in d['correlations']:
  if c['extractor']!='cookie_manager':values[c['variable']]=c['value']
 for p in root.iter('stringProp'):
  if p.get('name') in {'JSONPostProcessor.referenceNames','RegexExtractor.refname'}:runtime.extend((p.text or '').split(';'))
 for n in d['redirect_execution'].get('explicit_targets',[]):
  pass
 globals=[]
 for hm in root.iter('HeaderManager'):
  if not any(hm is child for s in samplers.values() for child in adjacent(s).iter('HeaderManager')):
   globals += [(prop(a,'Header.name'),prop(a,'Header.value')) for a in hm.findall(".//elementProp[@elementType='Header']")]
 occ={};requests={}
 for i,s in samplers.items():
  args=[(prop(a,'Argument.name'),prop(a,'Argument.value')) for a in s.findall(".//elementProp[@elementType='HTTPArgument']")]
  path=prop(s,'HTTPSampler.path');query=parse_qsl(path.partition('?')[2],keep_blank_values=True);headers=globals+[(prop(a,'Header.name'),prop(a,'Header.value')) for hm in adjacent(s).iter('HeaderManager') for a in hm.findall(".//elementProp[@elementType='Header']")]
  content=next((v for k,v in reversed(headers) if k.lower()=='content-type'),'');raw=prop(s,'HTTPSampler.postBodyRaw')=='true';body=args[0][1] if raw and args else ''
  request_used.update(refs(path+'\n'+body+'\n'+'\n'.join(v for k,v in args+headers)))
  occurrences={}
  for n,(k,v) in enumerate(query):occurrences[f'request.query[{n}].{k}']=(v,unquote_plus(resolve(v,values)),'str')
  for n,v in enumerate(urlsplit(path).path.split('/')):occurrences[f'request.path.segment[{n}]']=(v,unquote(resolve(v,values)),'str')
  if raw:
   try:
    before=dict((p,(v,k)) for p,v,k in scalars(json.loads(body)));after=dict((p,(v,k)) for p,v,k in scalars(json.loads(resolve(body,values))))
    for p,(v,k) in before.items():occurrences[p]=(str(v),after.get(p,(None,None))[0],after.get(p,(None,None))[1])
   except ValueError:occurrences['request.raw_body']=(body,resolve(body,values),'str')
  else:
   form_name='multipart' if prop(s,'HTTPSampler.DO_MULTIPART_POST')=='true' else 'form'
   for n,(k,v) in enumerate(args):occurrences[f'request.{form_name}[{n}].{k}']=(v,resolve(v,values),'str')
  for n,(k,v) in enumerate(headers):occurrences[f'request.headers[{n}].{k}']=(v,resolve(v,values),'str')
  occ[i]=occurrences;requests[i]={'path':path,'resolved_path':resolve(path,values),'args':args,'headers':headers,'content_type':resolve(content,values),'raw':raw,'body':body,'resolved_body':resolve(body,values),'sampler':s}
  original=har[i]['request'];post=original.get('postData',{});omime=post.get('mimeType','');obody=post.get('text','');oquery=parse_qsl(urlsplit(original['url']).query,keep_blank_values=True)
  qresolved=parse_qsl(resolve(path,values).partition('?')[2],keep_blank_values=True);redirect=path.startswith('${__har2jmx_redirect_')
  query_ok=redirect or qresolved==oquery
  if not query_ok:finding(bid,'request fidelity','Recorded query differs from final resolved query; encoding/binding must be checked.',i)
  expected_fields=fields(omime,obody);actual_fields=[(k,resolve(v,values)) for k,v in args] if not raw else []
  form_ok=not expected_fields or actual_fields==expected_fields
  body_ok=True
  if 'json' in omime and obody:
   try:
    before=json.loads(obody);after=json.loads(resolve(body,values));body_ok=before==after
    left=dict((p,(v,k)) for p,v,k in scalars(before));right=dict((p,(v,k)) for p,v,k in scalars(after))
    for p,(v,k) in left.items():
     v2,k2=right.get(p,(None,None));types.append({'benchmark_id':bid,'request_index':i,'location':p,'original_type':k,'emitted_type':k2,'value_preserved':v==v2,'type_preserved':k==k2})
     if k!=k2:finding(bid,'JSON/type serialization',f'{p}: {k} becomes {k2}',i)
   except (ValueError,TypeError):body_ok=False;finding(bid,'JSON/type serialization','Resolved JSON body is absent or invalid.',i)
  elif omime and not expected_fields and obody:body_ok=resolve(body,values)==obody
  mime_ok=not omime or omime.split(';')[0]==resolve(content,values).split(';')[0]
  if expected_fields and not form_ok:finding(bid,'request fidelity','Recorded form/multipart fields differ from resolved final body arguments.',i)
  if not mime_ok:finding(bid,'request fidelity','Recorded and generated content types differ.',i)
  fidelity.append({'benchmark_id':bid,'request_index':i,'method':original['method'],'body_kind':d['requests'][i]['body_kind'],
   'recorded_url':original['url'],'final_path':path,'resolved_path':resolve(path,values),'query_preserved':query_ok,'query_in_body':bool(oquery) and not redirect and len(actual_fields)>len(expected_fields) and all(p in actual_fields for p in oquery),
   'form_body_preserved':form_ok,'body_preserved':body_ok,'content_type_preserved':mime_ok,'recorded_body_fields':expected_fields,'final_arguments':args})
 # Match exact independent input occurrence to final request occurrence.
 local_inputs=[r for r in inputs if r['benchmark_id']==bid]
 for t in local_inputs:
  i=int(t['source_request_index']);loc=t['exact_location'];entry=occ.get(i,{}).get(loc)
  if entry is None and loc.startswith('request.headers'):
   key=loc.split('].',1)[-1];entry=next((x for p,x in occ.get(i,{}).items() if p.startswith('request.headers') and p.endswith('.'+key)),None)
  if entry is None and i in requests and loc.startswith(('request.path.component','request.path.response_selected','request.url.response_selected')):
   path=requests[i]['path'];entry=(path,resolve(path,values),'str')
  owned=refs(entry[0])&set(declared) if entry else set()
  expected=t['value']
  if loc.startswith('request.path.segment'):expected=unquote(expected)
  if loc.startswith(('request.path.response_selected','request.url.response_selected')) and expected.startswith('https://'):expected=urlsplit(expected).path
  right=entry is not None and (str(entry[1])==expected or (loc.startswith(('request.path.component','request.path.response_selected','request.url.response_selected')) and expected in unquote(str(entry[1]))))
  assessed=t['assessment']=='CONFIRMED';correct=assessed and bool(owned) and right
  parameters.append({**t,'csv_owners':sorted(owned),'final_expression':entry[0] if entry else None,'resolved_value':entry[1] if entry else None,'correctly_parameterized':correct,'sample_binding_correct':right,'assessed':assessed})
  if assessed and not correct:finding(bid,'parameter discovery' if not owned else 'sample binding',f'Meaningful input group {t["logical_input_group"]} lacks correct final CSV binding at {loc}.',i)
 for name,c in columns.items():
  associated=[p for p in parameters if p['benchmark_id']==bid and name in p['csv_owners'] and p['assessed']]
  ambiguous=[p for p in parameters if p['benchmark_id']==bid and name in p['csv_owners'] and not p['assessed']]
  necessary=bool(associated);used=name in request_used
  column_audit.append({'benchmark_id':bid,'column':name,'dataset':c['dataset'],'sample':values.get(name),'necessary':necessary,'unassessed':bool(ambiguous),'unused':not used,'truth_groups':sorted({p['logical_input_group'] for p in associated}),
   'engine_intent':c.get('intent'),'slots':c.get('slots',[]),'classification':'NECESSARY' if necessary else 'UNASSESSED' if ambiguous else 'NOT_SUPPORTED_BY_RECORDED_ACTIONS'})
  if len({p['logical_input_group'] for p in associated})>1:
   collision.append({'benchmark_id':bid,'column':name,'groups':sorted({p['logical_input_group'] for p in associated}),'assessment':'REVIEW','reason':'Multiple independent source-action owners use one column; logical consolidation requires evidence beyond spelling.'})
 for num,c in enumerate(d['correlations']):
  producer=c['producer_index'];var=c['variable'];j=java.get(f'{bid}:extractor:{num}',{});impl=d['materialization'].get(var,{})
  confirmed=[t for t in truth if t['benchmark_id']==bid and t['assessment']=='CONFIRMED' and int(t['producer_request_index'])==producer and int(t['consumer_request_index']) in c['consumers'] and t['value']==str(c['value'])]
  # Catalog selection is authoritative source intent, not a literal equality guess.
  cap=read(Path(workflow['capture_metadata']));selections=[a for a in cap['actions'] if a.get('selection') and a['selection']['classification']=='SELECTED_EXISTING_DATA']
  false_catalog=any(str(a['selection']['value'])==str(c['value']) and har[producer]['request']['url']==a['selection']['source_url'] and any(har[ci]['request']['url']==a['url'] for ci in c['consumers']) for a in selections)
  # Original RPC action explicitly reads an existing recent-items catalog. Its
  # module type/name is not newly issued state; no runtime identity is inferred.
  false_catalog=false_catalog or (bid=='REAL100-001' and c['variable'] in {'modname','modname2','modname3','name'} and 'block_recentlyaccesseditems_get_recent_items' in har[producer]['request']['url'])
  resolved=j.get('resolved');selected=resolved[0] if isinstance(resolved,list) and resolved else resolved
  expression_ok=c['extractor']=='cookie_manager' or (j.get('success',False) and j.get('matched',True) and str(selected)==str(c['value']))
  complete=bool(impl.get('implemented')) and expression_ok
  assessment='FALSE_CATALOG_CORRELATION' if false_catalog else 'CONFIRMED_RUNTIME' if confirmed else 'REVIEW'
  row={'benchmark_id':bid,'correlation_index':num,'variable':var,'producer_request_index':producer,'producer_location':c['producer_location'],'value':c['value'],
   'consumers':c['consumers'],'extractor':c['extractor'],'expression':c['expression'],'expression_check':j,'source_expression_resolves':expression_ok,'jmx_implementation':impl,
   'materialized_capture_check':complete,'ground_truth_assessment':assessment,'confirmed_evidence_rows':len(confirmed)};material.append(row)
  if false_catalog:finding(bid,'lifecycle classification','Explicit selected existing catalog identity was correlated as runtime.',producer)
  if not complete:finding(bid,'materialization' if expression_ok else 'extractor generation',f'Accepted {var} lacks complete resolving producer/extractor/consumer materialization.',producer)
 # Ground truth dependencies count exact edges, not all matching literal uses.
 for t in [r for r in truth if r['benchmark_id']==bid and r['assessment']=='CONFIRMED']:
  pi=int(t['producer_request_index']);ci=int(t['consumer_request_index']);candidate=[r for r in material if r['benchmark_id']==bid and r['producer_request_index']==pi and ci in r['consumers'] and str(r['value'])==t['value']]
  loc=t['consumer_request_location'];entry=occ.get(ci,{}).get(loc)
  cookie=loc.startswith('request.cookies') and t['producer_response_location'].startswith('response.cookies')
  correct=[]
  for c in candidate:
   if cookie and c['extractor']=='cookie_manager' and t['producer_response_location'].split('].',1)[-1]==c['producer_location'].split(':',1)[-1]:correct.append(c)
   elif entry and c['variable'] in refs(entry[0]) and str(entry[1]) in {t['value'],'Bearer '+t['value']} and c['source_expression_resolves']:correct.append(c)
  # Excluded static/polling consumers are not required workload dependencies.
  retained=ci in samplers
  dependency_audit.append({**t,'retained_consumer':retained,'discovered':bool(candidate),'correctly_correlated':bool(correct) and retained,
   'miss_category':None if correct else 'materialization' if candidate else 'discovery_or_lifecycle','matching_variables':[c['variable'] for c in correct]})
 undefined=sorted(request_used-set(declared)-set(runtime)-set(values)-{'COOKIE_'+c['variable'] for c in d['correlations'] if c['extractor']=='cookie_manager'})
 undefined=[v for v in undefined if not v.startswith(('COOKIE_','__har2jmx_redirect_'))];dead=sorted(set(runtime)-request_used)
 duplicate=sorted(n for n,c in collections.Counter(declared).items() if c>1);namespace=sorted(set(declared)&set(runtime))
 for v in undefined:finding(bid,'materialization',f'Undefined request variable {v}.')
 for v in dead:finding(bid,'materialization',f'Dead extractor {v}: no final request reference.')
 local_f=[x for x in fidelity if x['benchmark_id']==bid];local_p=[p for p in parameters if p['benchmark_id']==bid];local_d=[t for t in dependency_audit if t['benchmark_id']==bid and t['retained_consumer']]
 limited=bool(workflow.get('capture_limitations'));blocked=any(f['benchmark_id']==bid and f['blocking'] for f in findings)
 category='CAPTURE_LIMITED' if limited else 'MANUAL_REPAIR_REQUIRED' if blocked else 'READY_WITH_REVIEW'
 # No unmodified real two-iteration business replay was performed. Never promote
 # captured-response smoke or HTTP status success alone to REPLAY_READY.
 readiness.append({'benchmark_id':bid,'application':workflow['application'],'workflow':workflow['workflow_description'],'readiness':category,
  'reason':'Source capture lacks outbound body' if limited else 'Measured final request/input/runtime defect' if blocked else 'Static and local checks do not prove fresh business-state or independent live VU replay'})
 plans.append({'benchmark_id':bid,'conversion_success':d['success'],'jmeter_load_success':java.get(bid,{}).get('loaded',False),'sampler_count':len(samplers),'transactions':len(list(root.iter('TransactionController'))),
  'assertions':len(list(root.iter('ResponseAssertion'))),'extractors':len(runtime),'csv_columns':len(declared),'csv_structure':csvdata,
  'undefined_variables':undefined,'dead_extractors':dead,'csv_runtime_collisions':namespace,'duplicate_csv_names':duplicate,
  'request_indices':indices,'request_retention':d['requests'],'headers_audited':True,'redirect_execution':d['redirect_execution'],'cookies':'Manager declaration/source scope checked; live session freshness unproven'})
 for actual in [r for r in wire if r['benchmark_id']==bid]:
  i=actual['request_index'];original=har[i]['request'];post=original.get('postData',{});mime=post.get('mimeType','');body=post.get('text','');expected_fields=fields(mime,body);actual_fields=[tuple(x) for x in actual['parsed_body_fields']]
  q=urlsplit(original['url']).query;query_ok=q==actual['raw_query'];form_ok=not expected_fields or expected_fields==actual_fields
  if expected_fields:body_ok=form_ok
  elif body:
   if 'json' in mime:
    try:body_ok=json.loads(body)==json.loads(actual['raw_body'])
    except ValueError:body_ok=False
   else:body_ok=body==actual['raw_body']
  else:body_ok=not actual['raw_body']
  wire_checks.append({'benchmark_id':bid,'request_index':i,'query_exact':query_ok,'body_semantics_equal':body_ok,'form_fields_equal':form_ok,
   'query_semantics_equal':parse_qsl(q,keep_blank_values=True)==parse_qsl(actual['raw_query'],keep_blank_values=True),
   'content_type_equal':not mime or mime.split(';')[0]==actual['content_type'].split(';')[0],
   'har_query':q,'received_query':actual['raw_query'],'har_body':body,'received_body':actual['raw_body'],'received_content_type':actual['content_type'],
   'difference_class':'CAPTURE_OR_TRANSPORT_REVIEW' if original['method']!=actual['method'] else 'RUNTIME_OR_REPRESENTATION' if not body_ok or not query_ok else 'NO_FAILURE_OBSERVED'})

confirmed_p=[p for p in parameters if p['assessed']];groups={p['logical_input_group'] for p in confirmed_p};correct_groups={p['logical_input_group'] for p in confirmed_p if p['correctly_parameterized']}
necessary=[c for c in column_audit if c['necessary']];supported_denominator=[c for c in column_audit if not c['unassessed']]
retained=[t for t in dependency_audit if t['retained_consumer']];true_c=[c for c in material if c['ground_truth_assessment']=='CONFIRMED_RUNTIME'];false_c=[c for c in material if c['ground_truth_assessment'].startswith('FALSE')]
save('REAL100_PARAMETERIZATION_SCORECARD.json',{'status':'ASSESSED_SOURCE_ACTION_SCORECARD','meaningful_input_occurrences':len(confirmed_p),'meaningful_logical_input_groups':len(groups),
 'source_input_review_occurrences':sum(p['assessment']=='REVIEW' for p in parameters),'capture_limited_input_occurrences':sum(p['assessment']=='CAPTURE_LIMITED' for p in parameters),
 'correctly_parameterized_groups':len(correct_groups),'inputs_missed':len(groups-correct_groups),'parameter_recall':len(correct_groups)/len(groups) if groups else None,
 'csv_columns_generated':len(column_audit),'necessary_csv_columns':len(necessary),'unsupported_by_recorded_actions_columns':sum(not c['necessary'] and not c['unassessed'] for c in column_audit),
 'unnecessary_csv_columns':None,'parameter_precision_confirmed_action_lower_bound':len(necessary)/len(column_audit) if column_audit else None,
 'parameter_precision':None,'precision_limit':'UI defaults and implicit business selections were not exhaustively independently labeled; unsupported columns require review and cannot all be called unnecessary.',
 'unused_csv_columns':sum(c['unused'] for c in column_audit),'csv_identity_collisions_proven':sum(bool(p['duplicate_csv_names']) for p in plans),
 'cross_step_input_collapse_review':collision,'slot_binding_mismatches':sum(p['assessed'] and not p['sample_binding_correct'] for p in parameters),
 'input_audit':parameters,'column_audit':column_audit,'protocol_leakage_status':'Observed examples in unsupported columns; full necessary/unnecessary labeling incomplete.'})
save('REAL100_CORRELATION_SCORECARD.json',{'status':'CONFIRMED_RETAINED_EDGE_SCORECARD','confirmed_source_runtime_edges':len(dependency_audit),'confirmed_runtime_dependencies_in_retained_workload':len(retained),
 'excluded_source_consumers':len(dependency_audit)-len(retained),'correctly_discovered_edges':sum(t['discovered'] for t in retained),
 'correctly_correlated_edges':sum(t['correctly_correlated'] for t in retained),'correlation_recall':sum(t['correctly_correlated'] for t in retained)/len(retained) if retained else None,
 'accepted_correlations':len(material),'true_runtime_correlations_with_confirmed_evidence':len(true_c),'false_correlations_confirmed':len(false_c),
 'accepted_correlations_unassessed':len(material)-len(true_c)-len(false_c),'correlation_precision_assessed':len(true_c)/(len(true_c)+len(false_c)) if true_c or false_c else None,
 'correlation_precision':len(true_c)/(len(true_c)+len(false_c)) if true_c or false_c else None,
 'precision_limit':'Only sufficiently evidenced accepted decisions assessed; equality and converter classification are not ground truth. Unassessed accepted decisions excluded.',
 'materialization_rate_capture_resolution':sum(c['materialized_capture_check'] for c in material)/len(material) if material else None,
 'materialization_rate_fresh_runtime':None,'fresh_runtime_limit':'Captured values/response smoke verifies expression and declared consumers, not newly issued live values.',
 'dead_extractors':sum(len(p['dead_extractors']) for p in plans),'undefined_variables':sum(len(p['undefined_variables']) for p in plans),
 'runtime_review_rows':sum(t['assessment']=='REVIEW' for t in truth),'miss_classification':dict(collections.Counter(t['miss_category'] for t in retained if not t['correctly_correlated'])),'edges':dependency_audit})
save('REAL100_MATERIALIZATION_AUDIT.json',{'accepted_correlations':len(material),'checks':material,'authority':'Final JMX producer placement and downstream references plus JMeter Java expression resolution against original response; exact consumer evidence assessed separately.'})
save('REAL100_FINAL_JMX_AUDIT.json',{'workflows':plans,'all_100_jmeter_loaded':all(p['jmeter_load_success'] for p in plans),'source_to_jmx_inputs':parameters,'runtime_edges':dependency_audit})
save('REAL100_REQUEST_FIDELITY.json',{'samplers_audited':len(fidelity),'static_query_preservation_failures':sum(not x['query_preserved'] for x in fidelity),
 'R01_lost_query_candidates':sum(bool(urlsplit(x['recorded_url']).query) and '?' not in x['final_path'] and not x['final_path'].startswith('${__har2jmx_redirect_') for x in fidelity),
 'R02_query_in_body_candidates':sum(x['query_in_body'] for x in fidelity),'form_body_failures':sum(not x['form_body_preserved'] for x in fidelity),
 'content_type_failures':sum(not x['content_type_preserved'] for x in fidelity),'checks':fidelity,
 'wire_workflows':len({x['benchmark_id'] for x in wire_checks}),'wire_request_count':len(wire_checks),'wire_query_differences':sum(not x['query_exact'] for x in wire_checks),
 'wire_body_differences':sum(not x['body_semantics_equal'] for x in wire_checks),'wire_checks':wire_checks,
 'limits':'Query/body ownership audited separately from changed runtime/binding representations. XML/SOAP/file multipart not exercised. Duplicate wire iterations counted individually.'})
save('REAL100_JSON_REPRESENTATION.json',{'scalar_checks':len(types),'numeric_to_string':sum(x['original_type'] in {'int','float'} and x['emitted_type']=='str' for x in types),
 'boolean_to_string':sum(x['original_type']=='bool' and x['emitted_type']=='str' for x in types),'type_failures':sum(not x['type_preserved'] for x in types),
 'jsonpath_failures':sum(c['extractor']=='json' and not c['source_expression_resolves'] for c in material),'jsonpath_exercised':sum(c['extractor']=='json' for c in material),
 'states':{'numeric_JSON':'OBSERVED' if any(not x['type_preserved'] for x in types) else 'NO FAILURE OBSERVED','SOAP':'NOT EXERCISED','GraphQL_request':'NOT EXERCISED','multipart_files':'NOT EXERCISED',
  'dotted_JSON_keys':'NOT EXERCISED','nested_JSON':'NO FAILURE OBSERVED' if all(x['type_preserved'] for x in types if x['location'].count('[')>1) else 'OBSERVED'},'checks':types})
csvout('REAL100_REPLAY_READINESS.csv',readiness,['benchmark_id','application','workflow','readiness','reason'])
csvout('REAL100_FAILURE_INVENTORY.csv',findings,['benchmark_id','category','request_index','reason','already_known','blocking'])
locations={'request fidelity':'src/har2jmx/emit/jmx.py','JSON/type serialization':'src/har2jmx/emit/jmx.py','parameter discovery':'src/har2jmx/parameterize/intent.py; src/har2jmx/parameterize/decide.py',
 'sample binding':'src/har2jmx/emit/bindings.py; src/har2jmx/emit/jmx.py','materialization':'src/har2jmx/emit/jmx.py; src/har2jmx/correlate/decide.py',
 'extractor generation':'src/har2jmx/correlate/decide.py; src/har2jmx/validate/extractors.py','lifecycle classification':'src/har2jmx/classify/lifecycle.py; src/har2jmx/classify/value_engine.py'}
causes=[]
for cat in sorted({f['category'] for f in findings}):
 fs=[f for f in findings if f['category']==cat];bids=sorted({f['benchmark_id'] for f in fs});causes.append({'root_cause':cat,'affected_workflows':len(bids),'workflows':bids,'finding_count':len(fs),'examples':fs[:5],
  'source_location':locations.get(cat),'already_known':all(f['already_known'] for f in fs),'new':not all(f['already_known'] for f in fs),'blast_radius':'Any unfamiliar application exercising this representation/semantic owner; not application-specific.'})
causes.sort(key=lambda x:(-x['affected_workflows'],-x['finding_count']))
save('REAL100_ROOT_CAUSE_ANALYSIS.json',{'root_causes':causes,'no_source_repairs':True,'identity_testing_limit':'Natural equal-value occurrences retained with provenance; ambiguous edges REVIEW. This corpus does not establish exhaustive identity behavior or fresh runtime ownership.'})
print('AUDIT',len(plans),'plans',len(findings),'findings',len(groups),'assessed input groups',len(correct_groups),'correct groups',len(retained),'retained runtime edges',flush=True)
