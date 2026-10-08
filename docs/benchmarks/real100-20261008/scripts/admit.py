"""Independent source-capture review. No converter imports or output access."""
import hashlib, importlib.util, json, re, shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('source_fingerprints',ROOT.parent/'unseen-business-benchmark-20261004/audit_previous.py')
fp=importlib.util.module_from_spec(spec);spec.loader.exec_module(fp)
sha=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
exclude=read(ROOT/'HARD_EXCLUSION_SET.json')
reviews=[
 ('candidate-moodle-course','Education','Course creation','Session cookie + form login','POST','/course/edit.php',303,'Created course view follows response Location'),
 ('candidate-[REDACTED:6f0309fea1db]-tenant','Network inventory','Business tenant creation','Session cookie + CSRF','POST','/tenancy/tenants/add/',302,'Created tenant UUID Location followed by detail request'),
 ('candidate-vikunja-project','Project management','Project creation','JWT access + refresh tokens','POST','/api/v2/projects',201,'Created project ID and view ID followed by project and view-task reads'),
 ('candidate-elab-experiment-v6','Laboratory','Experiment creation','Session cookie + CSRF','POST','/api/v2/experiments',201,'Created experiment Location followed by editor and API reads'),
 ('candidate-openemr-patient-v3','Healthcare','Patient registration','Session cookie + session URL + CSRF','POST','/openemr/interface/new/new_comprehensive_save.php',200,'Native duplicate-check confirmation followed by demographics set_pid'),
 ('candidate-frontaccounting-customer','Accounting','Financial customer creation','Session cookie + CSRF','POST','/sales/manage/customers.php',200,'Source response explicitly confirms a new customer and default branch; saved form retains input values'),
 ('candidate-invoiceshelf-customer-v2','Billing','Billing customer creation','Session cookie + XSRF header','POST','/api/v1/customers',200,'Response data.id consumed by subsequent customer stats request'),
 ('candidate-sylius-customer','Commerce','Commerce customer creation','Session cookie + CSRF','POST','/admin/customers/new',302,'Native customer save and redirected customer detail view'),
 ('candidate-[REDACTED:6f0309fea1db]-tenantgroup','Network inventory','Tenant group creation','Session cookie + CSRF','POST','/tenancy/tenant-groups/add/',302,'New hierarchical ownership group with independent structured source location'),
 ('candidate-[REDACTED:6f0309fea1db]-manufacturer','Network inventory','Hardware manufacturer creation','Session cookie + CSRF','POST','/dcim/manufacturers/add/',302,'Independent hardware manufacturer registry operation, distinct from tenant ownership'),
 ('candidate-[REDACTED:6f0309fea1db]-devicerole','Network inventory','Device-role configuration','Session cookie + CSRF','POST','/extras/roles/add/',302,'Explicit selected DCIM content type and new role, followed by new object detail'),
 ('candidate-[REDACTED:6f0309fea1db]-namespace','Network inventory','IP address namespace creation','Session cookie + CSRF','POST','/ipam/namespaces/add/',302,'Independent address namespace ownership object with new issued UUID'),
 ('candidate-[REDACTED:6f0309fea1db]-platform','Network inventory','Network operating-platform configuration','Session cookie + CSRF','POST','/dcim/platforms/add/',302,'Independent platform registry operation followed by saved configuration detail'),
 ('candidate-invoiceshelf-item','Billing','Priced service catalog item creation','Session cookie + XSRF','POST','/api/v1/items',200,'Native priced-item save followed by saved item listing; decimal price recorded'),
 ('candidate-invoiceshelf-project','Billing','Billable project budget creation','Session cookie + XSRF','POST','/api/v1/tasks-projects/projects',201,'New project with hourly rate and hour budget, followed by project listing'),
 ('candidate-vikunja-task','Project management','Task creation in selected project','JWT access + refresh','POST','/api/v2/projects/1/tasks/bulk',201,'Native task submission followed by created task detail; outbound HAR body completeness requires review'),
 ('candidate-vikunja-label','Project management','Task label creation','JWT access + refresh','POST','/api/v2/labels',201,'Native independent label creation and resulting UI; outbound body capture requires review'),
 ('candidate-vikunja-team','Project management','Team ownership creation','JWT access + refresh','POST','/api/v2/teams',201,'Native independent team creation and resulting UI; outbound body capture requires review'),
 ('candidate-grocy-task','Inventory','Assigned inventory task creation','Public auto-login session','POST','/api/objects/tasks',200,'Native task with explicit selected category saved and read back'),
 ('candidate-grocy-location','Inventory','Storage location creation','Public auto-login session','POST','/api/objects/locations',200,'Independent storage location configuration saved and read back'),
 ('candidate-grocy-product','Inventory','Stock product configuration','Public auto-login session','POST','/api/objects/products',200,'Product inventory lifecycle configuration with quantity/location selections'),
 ('candidate-grocy-shop','Inventory','Purchasing supplier configuration','Public auto-login session','POST','/api/objects/shopping_locations',200,'Independent purchasing source registry save'),
 ('candidate-grocy-chore','Inventory','Recurring warehouse chore configuration','Public auto-login session','POST','/api/objects/chores',200,'Recurring schedule and assignment policy save'),
 ('candidate-grocy-battery','Inventory','Equipment battery configuration','Public auto-login session','POST','/api/objects/batteries',200,'Independent equipment charge interval configuration save'),
 ('candidate-grocy-quantityunit','Inventory','Stock receipt unit configuration','Public auto-login session','POST','/api/objects/quantity_units',200,'Independent quantity unit singular/plural configuration save'),
 ('candidate-easyappointments-service','Scheduling','Appointment service pricing configuration','Session cookie + CSRF','POST','/index.php/services/store',200,'Service save acknowledged success and issued service ID; saved service appears in catalog'),
 ('candidate-easyappointments-category','Scheduling','Appointment service category creation','Session cookie + CSRF','POST','/index.php/service_categories/store',200,'Category save acknowledged success and issued ID; saved category appears in catalog'),
 ('candidate-booked-group','Facilities','Reservation ownership group creation','Session cookie + CSRF','POST','/Web/admin/groups/index.php',200,'Native administration save followed by saved ownership group display'),
 ('candidate-booked-announcement','Facilities','Reservation dashboard notice configuration','Session cookie + CSRF','POST','/Web/admin/manage_announcements.php',200,'Native sandbox dashboard configuration save followed by saved notice display'),
 ('candidate-booked-schedule','Facilities','Resource reservation schedule configuration','Session cookie + CSRF','POST','/Web/admin/manage_schedules.php',200,'Native schedule save followed by saved schedule display'),
 ('candidate-booked-accessory-v2','Facilities','Reservable presentation accessory stock configuration','Session cookie + CSRF','POST','/Web/admin/manage_accessories.php',200,'Explicit finite accessory quantity saved and displayed in resource accessory catalog'),
]
records=[];audits=[];attempts=[]
for path in sorted((ROOT/'staging').glob('*/capture.json')):
 r=read(path);attempts.append({k:r.get(k) for k in ['id','application','workflow','status','error','sha256','request_count']})
for name,domain,workflow,auth,method,path,status,reason in reviews:
 folder=ROOT/'staging'/name
 if not (folder/'capture.json').exists():continue
 cap=read(folder/'capture.json');raw=(folder/'raw.har').read_bytes();har=json.loads(raw);entries=har['log']['entries']
 business_host=urlsplit(cap['steps'][0]['url']).hostname
 operation=[(i,e) for i,e in enumerate(entries) if e['request']['method']==method and urlsplit(e['request']['url']).path.rstrip('/')==path.rstrip('/') and e['response']['status']==status]
 if not operation:
  audits.append({'capture':name,'admitted':False,'reason':'Required original business operation not found'});continue
 if name.startswith('candidate-frontaccounting'):
  assert 'A new customer has been added.' in operation[-1][1]['response']['content'].get('text','')
 if name.startswith('candidate-openemr'):
  assert any('/summary/demographics.php' in e['request']['url'] and 'set_pid=' in e['request']['url'] for e in entries)
 checks={'har_sha_new':sha(raw) not in exclude['all_historical_hashes'],
   'additional_capture_sha_new':sha(raw)!=exclude['prior_additional_capture']['sha256'],
   'application_new':cap['application'].lower() not in {a.lower() for a in exclude['excluded_applications']},
   'business_host_new':business_host not in exclude['excluded_business_hosts'],
   'business_domain_new':fp.domain(business_host) not in exclude['excluded_domains']}
 signature=[fp.endpoint(e) for e in entries if urlsplit(e['request']['url']).hostname==business_host and fp.is_business(fp.endpoint(e))]
 signature=[{k:v for k,v in e.items() if k not in {'url_sha256','host','domain','response_content_type'}} for e in signature]
 sequence_hash=sha(json.dumps(signature,sort_keys=True).encode())
 checks['historical_sequence_new']=sequence_hash not in {p['sequence_sha256'] for p in exclude['protected_inputs']}
 checks['new_corpus_sequence_new']=sequence_hash not in {r['sequence_sha256'] for r in records}
 assert all(checks.values()), (name,checks)
 # Never count alternate recordings of an already admitted journey.
 assert (cap['application'],workflow) not in {(r['application'],r['workflow_description']) for r in records}
 bid=f'REAL100-{len(records)+1:03d}';target=ROOT/'corpus'/bid;target.mkdir(parents=True,exist_ok=True)
 for filename in ['raw.har','capture.json','final.png','final.html']:
  source=folder/filename
  if source.exists():shutil.copyfile(source,target/filename)
 record={'benchmark_id':bid,'application':cap['application'],'business_domain':domain,'workflow_description':workflow,
  'completion_status':'COMPLETED','completion_evidence':{'source_request_index':operation[-1][0],'method':method,'path':path,'status':status,'reason':reason},
  'request_count':len(entries),'representation_types':cap['representation_types'],'authentication_style':auth,
  'sha256':sha(raw),'sequence_sha256':sequence_hash,'business_sequence':signature,'raw_har':str(target/'raw.har'),
  'capture_metadata':str(target/'capture.json'),'source_permission':cap['permission_url'],
  'captured_utc':cap['started_utc'],'ui_action_record':str(target/'capture.json')}
 records.append(record);audits.append({'benchmark_id':bid,'capture':name,'admitted':True,'checks':checks,
  'within_application_distinct_journey':workflow,'within_application_sequence_policy':'Exclude static assets, then review operation/object paths and business objective; shared authentication prefix is not a distinct journey.'})

for capture_path in sorted((ROOT/'staging').glob('api*/capture.json')):
 if len(records)>=100:break
 cap=read(capture_path)
 if cap['status']!='COMPLETED_PENDING_INDEPENDENT_AUDIT':continue
 folder=capture_path.parent;raw=(folder/'raw.har').read_bytes();entries=json.loads(raw)['log']['entries'];actions=cap['actions']
 business_host=urlsplit(actions[0]['url']).hostname
 checks={'har_sha_new':sha(raw) not in exclude['all_historical_hashes'],
  'additional_capture_sha_new':sha(raw)!=exclude['prior_additional_capture']['sha256'],
  'application_new':cap['application'].lower() not in {a.lower() for a in exclude['excluded_applications']},
  'business_host_new':business_host not in exclude['excluded_business_hosts'],
  'business_domain_new':fp.domain(business_host) not in exclude['excluded_domains'],
  'all_documented_steps_captured':len(actions)==len(cap['steps']) and all(any(e['request']['url']==a['url'] and e['response']['status']==a['status'] for e in entries) for a in actions),
  'all_documented_steps_successful':all(200<=a['status']<300 for a in actions),
  'new_workflow_objective':(cap['application'],cap['workflow']) not in {(r['application'],r['workflow_description']) for r in records}}
 signature=[fp.endpoint(e) for e in entries if urlsplit(e['request']['url']).hostname==business_host and fp.is_business(fp.endpoint(e))]
 signature=[{k:v for k,v in e.items() if k not in {'url_sha256','host','domain','response_content_type'}} for e in signature]
 sequence_hash=sha(json.dumps(signature,sort_keys=True).encode())
 checks['historical_sequence_new']=sequence_hash not in {p['sequence_sha256'] for p in exclude['protected_inputs']}
 checks['new_corpus_sequence_new']=sequence_hash not in {r['sequence_sha256'] for r in records}
 if not all(checks.values()):
  audits.append({'capture':cap['id'],'admitted':False,'checks':checks});continue
 bid=f'REAL100-{len(records)+1:03d}';target=ROOT/'corpus'/bid;target.mkdir(parents=True,exist_ok=True)
 for filename in ['raw.har','capture.json','final.png']:
  if (folder/filename).exists():shutil.copyfile(folder/filename,target/filename)
 records.append({'benchmark_id':bid,'application':cap['application'],'business_domain':cap.get('domain','Public API reference workflow'),
  'workflow_description':cap['workflow'],'completion_status':'COMPLETED','completion_evidence':{'reason':'All documented real API read actions completed successfully; response-derived selection paths recorded before converter access','actions':actions},
  'request_count':len(entries),'representation_types':cap['representation_types'],'authentication_style':'Documented public API; no private credentials',
  'sha256':sha(raw),'sequence_sha256':sequence_hash,'business_sequence':signature,'raw_har':str(target/'raw.har'),
  'capture_metadata':str(target/'capture.json'),'source_permission':cap['permission_url'],'captured_utc':cap['started_utc'],'ui_action_record':str(target/'capture.json')})
 audits.append({'benchmark_id':bid,'capture':cap['id'],'admitted':True,'checks':checks,'within_application_distinct_journey':cap['workflow']})

manifest={'status':'COLLECTING_NOT_FROZEN','target':100,'accepted_count':len(records),'applications':sorted({r['application'] for r in records}),
 'records':records,'engine_freeze':'ENGINE_FREEZE.json','hard_exclusions':'HARD_EXCLUSION_SET.json',
 'freeze_gate':'Exactly 100 independent reviewed captures and independent ground truth must exist before any REAL100 converter run.'}
(ROOT/'REAL100_CORPUS_MANIFEST.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
(ROOT/'REAL100_DUPLICATE_AUDIT.json').write_text(json.dumps({'status':'PARTIAL_COLLECTION_AUDIT','protected_inputs':202,'admitted':len(records),'audits':audits,'attempts':attempts},indent=2,ensure_ascii=False),encoding='utf-8')
print('Independently admitted:',len(records),'applications:',len(manifest['applications']),'baseline not started')
