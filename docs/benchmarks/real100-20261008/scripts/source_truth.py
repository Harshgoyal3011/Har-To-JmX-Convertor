"""Evidence labels from original HAR and recorded UI actions, without converter access."""
import base64,csv,json,re
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qsl,urlsplit,unquote
ROOT=Path(__file__).resolve().parent

def scalars(value,path='$'):
 if isinstance(value,dict):
  for k,v in value.items():yield from scalars(v,path+'['+json.dumps(k)+']')
 elif isinstance(value,list):
  for i,v in enumerate(value):yield from scalars(v,path+f'[{i}]')
 elif value is not None:yield path,value,type(value).__name__

def body_occurrences(request):
 post=request.get('postData',{});text=post.get('text','');mime=post.get('mimeType','').lower()
 if 'json' in mime:
  try:
   for path,value,kind in scalars(json.loads(text)):yield 'request.body'+path[1:],value,kind
  except ValueError:pass
 elif 'x-www-form-urlencoded' in mime:
  for i,(k,v) in enumerate(parse_qsl(text,keep_blank_values=True)):yield f'request.form[{i}].{k}',v,'str'
 elif 'multipart/' in mime:
  # Chromium Windows HAR text may use doubled CR. Inspection normalization only;
  # raw HAR remains untouched and fidelity checks retain original bytes separately.
  raw=text.replace('\r\r\n','\r\n').encode()
  msg=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+post.get('mimeType','')+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
  if msg.is_multipart():
   for i,p in enumerate(msg.iter_parts()):
    name=p.get_param('name',header='content-disposition');value=p.get_payload(decode=True)
    if name and value is not None and not p.get_filename():yield f'request.multipart[{i}].{name}',value.decode('utf-8',errors='replace'),'str'

def request_occurrences(request):
 for i,(k,v) in enumerate(parse_qsl(urlsplit(request['url']).query,keep_blank_values=True)):yield f'request.query[{i}].{k}',v,'str'
 yield from body_occurrences(request)
 for i,h in enumerate(request.get('headers',[])):yield f'request.headers[{i}].{h["name"]}',h['value'],'str'
 for i,c in enumerate(request.get('cookies',[])):yield f'request.cookies[{i}].{c["name"]}',c['value'],'str'

def write_csv(filename,rows,fields):
 with (ROOT/filename).open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

manifest=json.loads((ROOT/'REAL100_CORPUS_MANIFEST.json').read_text(encoding='utf-8'))
inputs=[];runtime=[];unassessed=[]
for record in manifest['records']:
 bid=record['benchmark_id'];har=json.loads(Path(record['raw_har']).read_text(encoding='utf-8'));entries=har['log']['entries'];cap=json.loads(Path(record['capture_metadata']).read_text(encoding='utf-8'))
 occurrences=[list(request_occurrences(e['request'])) for e in entries]
 if cap.get('capture_method','').startswith('Native browser navigation'):
  for action in cap['actions']:
   indexes=[i for i,e in enumerate(entries) if e['request']['url']==action['url'] and e['response']['status']==action['status']]
   if not indexes:continue
   i=indexes[0];selection=action.get('selection')
   intended=[(k,v,'USER_INPUT',None) for k,v in action.get('inputs',{}).items()]
   if selection:intended.append(('selected_response_identity',selection.get('consumer_spelling',selection['value']),selection['classification'],selection))
   for slot,value,classification,evidence in intended:
    matches=[(loc,v,kind) for loc,v,kind in occurrences[i] if loc.startswith('request.query') and str(v)==str(value)]
    if not matches:
     matches=[(f'request.path.segment[{n}]',v,'str') for n,v in enumerate(urlsplit(action['url']).path.split('/')) if unquote(v)==str(value)]
    if not matches:
     # Documented action explicitly binds this source into a compound query/path.
     # Retain that component location rather than inventing an equality alias.
     matches=[(loc,v,'str') for loc,v,kind in occurrences[i] if loc.startswith('request.query') and str(value) in str(v)]
     if not matches and str(value) in unquote(urlsplit(action['url']).path):
      matches=[('request.path.component:'+str(slot),value,'str')]
    if not matches and evidence and str(value)==action['url']:
      matches=[('request.url.response_selected',value,'str')]
    if not matches and evidence and str(value).startswith('https://') and action['url'].startswith(str(value).rstrip('/')+'/'):
     matches=[('request.path.response_selected_prefix',value,'str')]
    if not matches:
     unassessed.append({'benchmark_id':bid,'action_index':action['index'],'slot':slot,'value':value,'reason':'Documented API input encoding/path requires manual location review'});continue
    for location,v,kind in matches:
     if classification=='SERVER_RUNTIME_STATE':
      previous=evidence['source_url'];pi=next(n for n,e in enumerate(entries) if e['request']['url']==previous)
      runtime.append({'benchmark_id':bid,'dependency_id':f'{bid}:{pi}:{evidence["source_response_path"]}:{i}:{location}',
       'producer_request_index':pi,'producer_response_location':'response.body'+''.join('['+json.dumps(k)+']' for k in evidence['source_response_path']),
       'producer_url':previous,'value':evidence['value'],'consumer_request_index':i,'consumer_request_location':location,'consumer_url':action['url'],
       'known_transform':evidence.get('known_transform','identity'),'assessment':'CONFIRMED','reason':'Documented API explicitly issues session token; next native request explicitly selects that source token.'})
     else:
      inputs.append({'benchmark_id':bid,'logical_input_group':f'{bid}:api-action:{action["index"]}:{slot}',
       'classification':classification,'action_index':action['index'],'ui_slot':slot,'value':v,
       'source_request_index':i,'source_request_url':action['url'],'source_response_index':i if not evidence else next(n for n,e in enumerate(entries) if e['request']['url']==evidence['source_url']),
       'exact_location':location,'downstream_consumer_request_index':i,'original_type':kind,'assessment':'CONFIRMED' if len(matches)==1 else 'REVIEW',
       'reason':'Recorded documented API action intent and exact request slot; '+(json.dumps(evidence,ensure_ascii=False) if evidence else 'Explicit search/filter or entity input, independent of converter output.')})
  continue
 # UI action is authoritative for intent. Matching spelling only locates candidates
 # after that action within the same application and submission context.
 for action in cap['actions']:
  if action['op'] not in {'fill','select','check'}:continue
  ev=action.get('element_evidence',{});value=ev.get('value',action.get('value'));atype=ev.get('type','');slot=ev.get('name') or ev.get('id') or action['selector']
  if atype=='[REDACTED:5e884898da28]' or any(word in slot.lower() for word in ['[REDACTED:5e884898da28]','clearpass','_username','authuser']):classification='CREDENTIAL_INPUT'
  elif action['op']=='select':classification='SELECTED_EXISTING_DATA'
  else:classification='USER_INPUT'
  action_time=datetime.fromisoformat(action['started_utc']);matches=[]
  for i,e in enumerate(entries):
   if urlsplit(e['request']['url']).hostname!=urlsplit(cap['steps'][0]['url']).hostname:continue
   if datetime.fromisoformat(e['startedDateTime'].replace('Z','+00:00'))<action_time:continue
   if e['request']['method'] not in {'POST','PUT','PATCH'}:continue
   for location,v,kind in occurrences[i]:
    if location.startswith(('request.headers','request.cookies')):continue
    if str(v)==str(value):matches.append((i,location,kind))
   if matches:break
  group=f'{bid}:action:{action["index"]}:{slot}'
  if not matches:
   # UI monetary and duration widgets document an explicit representation.
   transforms={('REAL100-014',9):('price',12550,'currency-major-to-minor'),('REAL100-015',10):('default_rate',15000,'currency-major-to-minor'),('REAL100-015',11):('budget_minutes',1200,'hours-to-minutes')}
   known=transforms.get((bid,action['index']))
   if known:
    field,expected,transform=known
    for i,e in enumerate(entries):
     if e['request']['method']!='POST':continue
     for location,v,kind in occurrences[i]:
      if location.endswith('['+json.dumps(field)+']') and v==expected:matches.append((i,location,kind));value=v
   if not matches:
    unassessed.append({'benchmark_id':bid,'action_index':action['index'],'slot':slot,'value':value,'reason':'UI input not located unambiguously in a subsequent business submission'});continue
  # More than one equal occurrence needs field/context review, never forced consolidation.
  exact=[m for m in matches if m[1].endswith('.'+str(ev.get('name',''))) or ('['+json.dumps(ev.get('name',''))+']') in m[1]] if ev.get('name') else []
  chosen=exact if exact else matches
  for i,location,kind in chosen:
   inputs.append({'benchmark_id':bid,'logical_input_group':group,'classification':classification,'action_index':action['index'],
    'ui_slot':slot,'value':value,'source_request_index':i,'source_request_url':entries[i]['request']['url'],'source_response_index':i,
    'exact_location':location,'downstream_consumer_request_index':i,'original_type':kind,
    'assessment':'CONFIRMED' if len(chosen)==1 else 'REVIEW','reason':'Explicit recorded user fill/selection and subsequent same-host submission; action identity preserves independent ownership.'})
 # Independent positive runtime evidence: actual issued cookie, native CSRF token,
 # documented auth response token, and workflow create response -> native consumer.
 def dependency(pi,pl,value,reason,consumer_predicate=None,representation='identity'):
  found=[]
  for ci in range(pi+1,len(entries)):
   if consumer_predicate and not consumer_predicate(ci):continue
   for loc,v,kind in occurrences[ci]:
    # Authorization has a known Bearer representation; it is not an equality alias.
    equal=str(v)==str(value);bearer=str(v)=='Bearer '+str(value)
    if equal or bearer:found.append((ci,loc,'bearer-prefix' if bearer else representation))
  for ci,loc,transform in found:
   if pl.startswith('response.html.input'):
    source_name=json.loads(pl.split('name=',1)[1].split(']@value',1)[0])
    if not loc.endswith('.'+source_name):
     continue
   runtime.append({'benchmark_id':bid,'dependency_id':f'{bid}:{pi}:{pl}:{ci}:{loc}','producer_request_index':pi,
    'producer_response_location':pl,'producer_url':entries[pi]['request']['url'],'value':value,
    'consumer_request_index':ci,'consumer_request_location':loc,'consumer_url':entries[ci]['request']['url'],
    'known_transform':transform,'assessment':'CONFIRMED','reason':reason})
 for pi,e in enumerate(entries):
  host=urlsplit(e['request']['url']).hostname
  if host!=urlsplit(cap['steps'][0]['url']).hostname:continue
  res=e['response'];text=res.get('content',{}).get('text','')
  if res.get('content',{}).get('encoding')=='base64':
   try:text=base64.b64decode(text).decode()
   except Exception:continue
  for n,c in enumerate(res.get('cookies',[])):
   if c.get('value'):dependency(pi,f'response.cookies[{n}].{c["name"]}',c['value'],'Server-issued cookie consumed by browser cookie occurrence on the same origin.',lambda i:urlsplit(entries[i]['request']['url']).hostname==host)
  # Credential/session semantic source, not dynamic-looking/entropy evidence.
  if '/login' in urlsplit(e['request']['url']).path or '/token/refresh' in e['request']['url']:
   try:data=json.loads(text)
   except ValueError:data={}
   if isinstance(data,dict) and data.get('token'):dependency(pi,'response.body["token"]',data['token'],'Explicit login/refresh token response followed by native Authorization consumer.',lambda i:urlsplit(entries[i]['request']['url']).hostname==host)
  for match in re.finditer(r'<input\b[^>]*>',text,re.I):
   attrs={k.lower():v for k,_,v in re.findall(r'([\w-]+)\s*=\s*([\"\'])(.*?)\2',match.group())}
   name=attrs.get('name','');value=attrs.get('value','')
   if value and any(w in name.lower() for w in ['csrf','sesskey','logintoken','_token']):
    dependency(pi,f'response.html.input[name={json.dumps(name)}]@value:offset:{match.start()}',value,'Native hidden CSRF/session form token consumed by subsequent same-origin form/query/header.',lambda i:urlsplit(entries[i]['request']['url']).hostname==host)
 # Object IDs need a known creation operation and explicit native follow-up.
 ci=record['completion_evidence']['source_request_index'];ce=entries[ci];source=ce['response'];locations=[h['value'] for h in source.get('headers',[]) if h['name'].lower()=='location']
 try:created=json.loads(source.get('content',{}).get('text',''))
 except ValueError:created={}
 object_ids=[]
 if isinstance(created,dict):
  for path,val,kind in scalars(created):
   if path in ['$["id"]','$["data"]["id"]']:object_ids.append((path,val))
 for location in locations:
  u=urlsplit(location)
  for key,value in parse_qsl(u.query):
   if key in ['id','set_pid']:object_ids.append(('response.headers.Location.query.'+key,value))
  last=u.path.rstrip('/').rsplit('/',1)[-1]
  if re.fullmatch(r'\d+|[0-9a-f-]{36}',last):object_ids.append(('response.headers.Location.path.last',last))
 for pl,value in object_ids:
  response_location=locations[0] if locations else None
  expected_resource_path=urlsplit(response_location).path.rstrip('/') if response_location else urlsplit(ce['request']['url']).path.rstrip('/')+'/'+str(value)
  for c in range(ci+1,len(entries)):
   req=entries[c]['request'];u=urlsplit(req['url'])
   if u.hostname!=urlsplit(ce['request']['url']).hostname:continue
   if str(value) in u.path.split('/') and (u.path.rstrip('/')==expected_resource_path or u.path.startswith(expected_resource_path+'/')):
    runtime.append({'benchmark_id':bid,'dependency_id':f'{bid}:{ci}:{pl}:{c}:path','producer_request_index':ci,
     'producer_response_location':pl,'producer_url':ce['request']['url'],'value':value,'consumer_request_index':c,
     'consumer_request_location':f'request.path.segment[{u.path.split("/").index(str(value))}]','consumer_url':req['url'],
     'known_transform':'identity','assessment':'CONFIRMED','reason':'This workflow created the object; native subsequent request follows its explicit response ID/Location on the same origin.'})
   for loc,v,kind in occurrences[c]:
    if loc.startswith(('request.body','request.query','request.form')) and str(v)==str(value):
     runtime.append({'benchmark_id':bid,'dependency_id':f'{bid}:{ci}:{pl}:{c}:{loc}','producer_request_index':ci,
      'producer_response_location':pl,'producer_url':ce['request']['url'],'value':value,'consumer_request_index':c,
      'consumer_request_location':loc,'consumer_url':req['url'],'known_transform':'identity','assessment':'REVIEW',
      'reason':'Created object ID candidate in subsequent scalar; exact contextual ownership requires manual review, equality is insufficient.'})

# Repeated issuance is not one global producer. Cookie scope/name permits the
# nearest matching Set-Cookie issuer; repeated form/token issuers remain REVIEW.
by_consumer={}
for row in runtime:
 key=(row['benchmark_id'],row['consumer_request_index'],row['consumer_request_location'],str(row['value']))
 by_consumer.setdefault(key,[]).append(row)
for rows in by_consumer.values():
 producers={(r['producer_request_index'],r['producer_response_location']) for r in rows}
 if len(producers)>1:
  cookies=[r for r in rows if r['producer_response_location'].startswith('response.cookies') and r['consumer_request_location'].startswith('request.cookies') and r['producer_response_location'].split('].',1)[-1]==r['consumer_request_location'].split('].',1)[-1]]
  if len(cookies)==len(rows):
   nearest=max(r['producer_request_index'] for r in cookies)
   for row in rows:
    if row['producer_request_index']!=nearest:row['assessment']='SUPERSEDED_ISSUER'
  else:
   for row in rows:row['assessment']='REVIEW';row['reason']+=' Multiple exact source occurrences issue equal captured values; equality cannot prove which issuer owns this consumer.'
for row in runtime:
 if row['producer_response_location'].startswith('response.cookies'):
  if not row['consumer_request_location'].startswith('request.cookies') or row['producer_response_location'].split('].',1)[-1]!=row['consumer_request_location'].split('].',1)[-1]:
   row['assessment']='REVIEW';row['reason']+=' Cookie name/scope is not proven for this representation.'
for row in unassessed:
 if row['benchmark_id'] in {'REAL100-003','REAL100-016','REAL100-017','REAL100-018'}:
  record=next(r for r in manifest['records'] if r['benchmark_id']==row['benchmark_id']);i=record['completion_evidence']['source_request_index']
  inputs.append({'benchmark_id':row['benchmark_id'],'logical_input_group':f'{row["benchmark_id"]}:action:{row["action_index"]}:{row["slot"]}',
   'classification':'USER_INPUT','action_index':row['action_index'],'ui_slot':row['slot'],'value':row['value'],'source_request_index':i,
   'source_request_url':record['completion_evidence']['path'],'source_response_index':i,'exact_location':'request.body:CAPTURE_NOT_AVAILABLE',
   'downstream_consumer_request_index':i,'original_type':'str','assessment':'CAPTURE_LIMITED','reason':'Recorded native user input and successful created-object response; Chromium HAR omitted outbound body, so exact request slot and parameter binding cannot be assessed.'})
fields=['benchmark_id','logical_input_group','classification','action_index','ui_slot','value','source_request_index','source_request_url','source_response_index','exact_location','downstream_consumer_request_index','original_type','assessment','reason']
write_csv('REAL100_GROUND_TRUTH_INPUTS.csv',inputs,fields)
fields=['benchmark_id','dependency_id','producer_request_index','producer_response_location','producer_url','value','consumer_request_index','consumer_request_location','consumer_url','known_transform','assessment','reason']
write_csv('REAL100_GROUND_TRUTH_RUNTIME.csv',runtime,fields)
(ROOT/'GROUND_TRUTH_LABEL_REVIEW.json').write_text(json.dumps({'status':'PARTIAL_SOURCE_LABELS_REVIEW_REQUIRED','workflows':len(manifest['records']),'input_occurrences':len(inputs),'runtime_evidence_rows':len(runtime),'unassessed_ui_actions':unassessed,
 'limitations':'Created-object non-runtime/catalog labels, JS-issued IDs, cookie freshness/repeated issuer lineage, and cross-representation ambiguity need independent manual review. These preliminary rows are not benchmark denominator totals.'},indent=2),encoding='utf-8')
print('Source labels',len(inputs),'input candidates;',len(runtime),'runtime evidence rows;',len(unassessed),'UI actions unassessed; no converter imported')
